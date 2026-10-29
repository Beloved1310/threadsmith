"""Guardrails: Model Armor on every model call, DLP on the thread before it is saved.

Layers (LAYERS, not alternatives: different layers catch different attacks):

  content_config()     Model Armor, applied INLINE by Agent Platform on each Gemini call
                       (GenerateContentConfig.model_armor_config), both directions
  friendly_block       after_model_callback: turns a Model Armor block into a
                       readable refusal instead of an empty turn
  redact_thread_posts  DLP de-identify on save_thread's posts (before_tool_callback
                       on thread_writer), so the draft the user sees and approves
                       is already redacted and publish_thread sends exactly that

agent.py wires the Model Armor layers onto all three agents; redact_thread_posts
is not wired yet. Model Armor is a no-op if MODEL_ARMOR_TEMPLATE_ID is unset or
"off"; DLP is a no-op unless PII_REDACTION=on.
So ungoverned behaviour is reproducible by flipping one var each.

WHY INLINE, NOT A SANITIZE API CALL (verified 2026-09-21 in the parent project,
docs/LEARNINGS.md there): calling the Model Armor sanitize API from agent code
works locally (your user ADC) and returns 401 inside Agent Runtime, with plain
REST AND with the client library, because the agent runs as its own Agent
Identity. Google's guidance for that case is inline enforcement, which Agent
Platform performs with ITS OWN service agent. Constraints, each learnt by hitting it:
  * the Gemini call must use a REGIONAL location (GOOGLE_CLOUD_LOCATION=us-central1,
    not the `global` in .env.example). Against `global` the template is "not found",
    whichever template you use;
  * STREAMING calls are not screened at all: an injection sails through with no
    block and no error. ag_ui_adk's ADKAgent defaults to StreamingMode.SSE, so
    main.py passes a run_config_factory with StreamingMode.NONE when this is on;
  * `global` templates cannot be created; use us-central1, the same region as deploys;
  * Agent Platform's own service agent needs roles/modelarmor.user, and the
    modelarmor and dlp APIs must be enabled (not yet in gcp-setup.sh);
  * Agent Platform's template lookup fails at random ("The template named ... was not
    found"). Fixed by retry options on the ADK model object (model() below): 15 of
    15 deployed checks passed with it, most failed without. The same options in
    the request config are ignored inside the deployed agent.
Why not call the sanitize API from a callback after all? It CAN work: the 401 is
google-auth's "prevent agent token sharing" default, and setting
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False lets both REST and
the client library through (verified). But Google warns against relaxing it in
production, so inline enforcement it is.
DLP is called with the DLP client library (google-cloud-dlp, not yet a dependency)
on the global endpoint.
"""

import logging
import os
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import Gemini
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types as genai_types

from .tools import save_thread

log = logging.getLogger(__name__)

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
# DLP wants the project ID *string* and rejects the project NUMBER ("Malformed
# parent field"), but inside Agent Runtime GOOGLE_CLOUD_PROJECT is the number.
# Set PROJECT_ID on the deployment.
DLP_PROJECT = os.environ.get("PROJECT_ID") or PROJECT  # also used for the Model Armor template path
# Where the TEMPLATE lives. Use the same region as Gemini (us-central1);
# `global` templates cannot be created.
MA_REGION = os.environ.get("MODEL_ARMOR_REGION", "us-central1")
# "off" (or blank) disables the Model Armor layers. A deployed engine cannot take
# an empty env var (the API rejects it), so "off" is the switch there.
MA_TEMPLATE = os.environ.get("MODEL_ARMOR_TEMPLATE_ID", "")
if MA_TEMPLATE.strip().lower() in ("off", "none", "disabled"):
    MA_TEMPLATE = ""
# Responses get a second template WITHOUT the prompt-injection filter: that
# filter fires on a model reply that merely DISCUSSES injection, and a thread
# about AI security is exactly that, so outputs are screened on the
# responsible-AI filters only.
MA_OUTPUT_TEMPLATE = os.environ.get(
    "MODEL_ARMOR_OUTPUT_TEMPLATE_ID", f"{MA_TEMPLATE}-output" if MA_TEMPLATE else ""
)

# PII redaction has its OWN switch, independent of Model Armor: "on" runs DLP on
# every saved thread. Off by default so a local run needs no DLP setup.
PII_REDACTION = os.environ.get("PII_REDACTION", "off").strip().lower() in ("on", "true", "1")

REFUSAL = (
    "I can't help with that request — it was flagged by our content safety "
    "checks. Happy to help with your next thread idea instead."
)

_dlp_client = None


def _dlp():
    # Imported lazily, like fastmcp in tools.py: google-cloud-dlp is only needed
    # when PII_REDACTION is on, and importing this module must not require it.
    global _dlp_client
    if _dlp_client is None:
        from google.cloud import dlp_v2

        _dlp_client = dlp_v2.DlpServiceClient()
    return _dlp_client


def _template(template_id: str) -> str:
    # The project ID, not the number Agent Runtime provides: in testing the deployed
    # agent (number in the path) hit "template not found" far more often than a
    # local run (ID in the path).
    return f"projects/{DLP_PROJECT}/locations/{MA_REGION}/templates/{template_id}"


def content_config(screen_input: bool = True) -> Optional[genai_types.GenerateContentConfig]:
    """GenerateContentConfig that makes Agent Platform screen this agent's model calls.

    screen_input=False for research_agent and thread_writer: they are called as
    AgentTools, so their input is text the orchestrator wrote, not the user's,
    and only the reply is screened.
    Returns None when guardrails are off. If GOOGLE_CLOUD_LOCATION is `global`
    the calls will fail with "template not found": deliberately left loud
    (fail closed) rather than silently dropping the guardrail.
    """
    if not MA_TEMPLATE:
        return None
    if os.environ.get("GOOGLE_CLOUD_LOCATION", "global") == "global":
        log.error(
            "Model Armor is on but GOOGLE_CLOUD_LOCATION is global: Gemini calls "
            "will be rejected (template not found). Use a regional location."
        )
    return genai_types.GenerateContentConfig(
        model_armor_config=genai_types.ModelArmorConfig(
            prompt_template_name=_template(MA_TEMPLATE) if screen_input else None,
            response_template_name=_template(MA_OUTPUT_TEMPLATE),
        )
    )


def model(name: str) -> Gemini:
    """The model for an agent (RESEARCH_MODEL, WRITER_MODEL, ORCHESTRATOR_MODEL).
    When Model Armor is on, wrap it in ADK's Gemini class with retry options:
    Agent Platform's template lookup fails at random ("template ... was not found",
    roughly half of guarded calls in testing) and a retry usually succeeds. The
    retry must live on the ADK model object; the same options in the request
    config were ignored inside the deployed agent."""
    if not MA_TEMPLATE:
        # No Model Armor: still retry 429/503. Agent Platform answers bursts
        # with 429 RESOURCE_EXHAUSTED even on GA models, and an unretried one
        # inside thread_writer kills the whole turn.
        return Gemini(
            model=name,
            retry_options=genai_types.HttpRetryOptions(
                attempts=5, initial_delay=2, max_delay=30, exp_base=2,
                http_status_codes=[429, 503],
            ),
        )
    return Gemini(
        model=name,
        # 400 = the random "template not found". 429 = Agent Platform saying the regional
        # Gemini model is out of (shared) capacity. A ThreadSmith turn makes several model
        # calls (orchestrator, research, writer, every save_thread retry) and a retry is
        # another, so back off properly.
        retry_options=genai_types.HttpRetryOptions(
            attempts=8, initial_delay=0.3, max_delay=8.0, exp_base=2.0, jitter=0.3,
            http_status_codes=[400, 429],
        ),
    )


def friendly_block(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """after_model_callback: a Model Armor block arrives as error_code MODEL_ARMOR
    with no content. Replace it with a readable refusal."""
    if llm_response.error_code == "MODEL_ARMOR":
        log.warning("Model Armor blocked a call: %s", llm_response.error_message)
        return LlmResponse(
            content=genai_types.Content(
                role="model", parts=[genai_types.Part.from_text(text=REFUSAL)]
            )
        )
    return None


# --- DLP ----------------------------------------------------------------------

# Two thresholds, because the two families fail in opposite ways. Names and
# locations are fuzzy: at DLP's default POSSIBLE tier a capitalized product or
# project noun (e.g. "Agent Substrate") reads as PERSON_NAME, so they need
# LIKELY. Phones and emails are structured, and DLP rates a phone number
# POSSIBLE whenever it sits inside a sentence ("...or +44 7911 123456 if you
# want the slides"), so a blanket LIKELY silently leaked it. Structured types
# therefore run at POSSIBLE.
# No LOCATION: DLP reads any city as one, and "a thread about our London event"
# would lose the one word that matters, for little privacy gain.
_DLP_PASSES = [
    (["EMAIL_ADDRESS", "PHONE_NUMBER"], "POSSIBLE"),
    (["PERSON_NAME"], "LIKELY"),
]


def _deidentify(text: str, info_types: list[str], min_likelihood: str) -> str:
    resp = _dlp().deidentify_content(
        request={
            "parent": f"projects/{DLP_PROJECT}/locations/global",
            "inspect_config": {
                "info_types": [{"name": t} for t in info_types],
                "min_likelihood": min_likelihood,
            },
            "deidentify_config": {
                "info_type_transformations": {
                    "transformations": [
                        {"primitive_transformation": {"replace_with_info_type_config": {}}}
                    ]
                }
            },
            "item": {"value": text},
        },
        timeout=15,
    )
    return resp.item.value or text


def redact_pii(text: str) -> str:
    """De-identifies PII via Cloud DLP, replacing each finding with its type
    (e.g. "[PERSON_NAME]"). Raises if DLP fails."""
    if not text or not text.strip():
        return text
    for info_types, likelihood in _DLP_PASSES:
        text = _deidentify(text, info_types, likelihood)
    return text


def redact_thread_posts(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    """before_tool_callback for thread_writer: DLP each post before save_thread
    stores it.

    Redacting here rather than at publish_thread keeps the approval honest: the
    ThreadBoard shows, and the user approves, the redacted thread, and
    save_thread measures the redacted text (a "[PERSON_NAME]" placeholder can
    push a post over 280, which the writer then fixes as usual).
    Mutating args in place changes what the tool actually receives; returning
    None lets the call proceed. If DLP fails the save is refused with an error
    result rather than letting unredacted posts through (fail closed) or raising
    (a raising callback kills the whole turn).
    """
    if not PII_REDACTION or tool.name != save_thread.__name__:
        return None
    posts = args.get("posts")
    if not isinstance(posts, list):
        return None
    try:
        redacted = [redact_pii(p) if isinstance(p, str) else p for p in posts]
    except Exception as e:  # noqa: BLE001
        log.warning("redact_thread_posts: DLP unavailable, thread not saved: %s", e)
        return {
            "status": "error",
            "ok": False,
            "problems": [
                f"PII redaction is unavailable ({type(e).__name__}); the thread was NOT saved."
            ],
        }
    if redacted != posts:
        log.warning("DLP redacted PII from the thread draft")
        args["posts"] = redacted
    return None
