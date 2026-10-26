"""Thread tools: measure and stage a thread, then publish it to X via Buffer.

The thread lives in session state as structured data (state["thread"]), never
as free text the model re-types at publish time. save_thread writes it,
the frontend's ThreadBoard renders it, and publish_thread reads it back to
build Buffer's payload deterministically. The model never constructs the
nested metadata.twitter.thread argument itself: a large nested argument is
exactly what produced MALFORMED_FUNCTION_CALL in the parent project (see
docs/LEARNINGS.md).
"""

import datetime
import json
import logging
import os
from typing import Optional

from google.adk.tools.tool_context import ToolContext

log = logging.getLogger(__name__)

X_LIMIT = 280
MIN_POSTS = 2
MAX_POSTS = 12

BUFFER_MCP_URL = "https://mcp.buffer.com/mcp"


# --- Measuring ---------------------------------------------------------------
def measure_thread(posts: list[str]) -> dict:
    """Pure check of a thread against X's rules. No state, no network."""
    measured = []
    problems = []
    for i, raw in enumerate(posts, start=1):
        text = (raw or "").strip()
        length = len(text)
        within = 0 < length <= X_LIMIT
        measured.append(
            {
                "index": i,
                "text": text,
                "length": length,
                "within_limit": within,
                "over_by": max(0, length - X_LIMIT),
            }
        )
        if length == 0:
            problems.append(f"Post {i} is empty.")
        elif length > X_LIMIT:
            problems.append(f"Post {i} is {length - X_LIMIT} characters over {X_LIMIT}.")
    if len(posts) < MIN_POSTS:
        problems.append(f"A thread needs at least {MIN_POSTS} posts, got {len(posts)}.")
    if len(posts) > MAX_POSTS:
        problems.append(f"Keep threads to {MAX_POSTS} posts or fewer, got {len(posts)}.")
    return {"posts": measured, "ok": not problems, "problems": problems}


def _numbered(posts: list[dict]) -> str:
    return "\n\n".join(f"{p['index']}/{len(posts)}: {p['text']}" for p in posts)


def save_thread(posts: list[str], tool_context: ToolContext) -> dict:
    """Saves the full thread as the current draft and checks every post.

    Always pass the COMPLETE thread, in order, even when only one post
    changed. Each post must be 280 characters or fewer; the result says
    exactly which ones are over so you can fix just those and call again.

    Args:
        posts: Every post in the thread, in order, as plain text.

    Returns:
        dict with 'status', 'ok', per-post 'posts' (index, length,
        within_limit, over_by) and a list of 'problems' to fix.
    """
    result = measure_thread(posts)
    tool_context.state["thread"] = result["posts"]
    tool_context.state["thread_ok"] = result["ok"]
    tool_context.state["thread_text"] = _numbered(result["posts"])
    # A changed thread is a new draft: any earlier publish result no longer
    # describes it, and the UI must not show it as already scheduled.
    tool_context.state["thread_status"] = "draft"
    return {"status": "success", **result}


# --- Publishing --------------------------------------------------------------
def build_buffer_payload(texts: list[str], channel_id: str, due_at: Optional[str]) -> dict:
    """Buffer create_post arguments for an X thread.

    Buffer's own tool description: set BOTH the outer text and
    metadata.twitter.thread, include ALL items, and match the outer text to
    the first item's text.
    """
    payload = {
        "channelId": channel_id,
        "schedulingType": "automatic",
        "text": texts[0],
        "metadata": {"twitter": {"thread": [{"text": t} for t in texts]}},
    }
    if due_at:
        payload["mode"] = "customScheduled"
        payload["dueAt"] = due_at
    else:
        payload["mode"] = "addToQueue"
    return payload


async def _buffer_call(tool: str, args: dict) -> dict:
    """One Buffer MCP call, its JSON result decoded. Patched out in tests."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    key = os.environ.get("BUFFER_API_KEY", "").strip()
    transport = StreamableHttpTransport(
        BUFFER_MCP_URL, headers={"Authorization": f"Bearer {key}"}
    )
    async with Client(transport, timeout=30) as client:
        result = await client.call_tool(tool, args)
    text = result.content[0].text if result.content else "{}"
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"raw": text}


async def _resolve_x_channel() -> str:
    account = await _buffer_call("get_account", {})
    orgs = account.get("organizations") or account.get("account", {}).get("organizations") or []
    if not orgs:
        raise LookupError("Buffer account has no organizations.")
    channels = await _buffer_call("list_channels", {"organizationId": orgs[0]["id"]})
    if isinstance(channels, dict):
        channels = channels.get("channels", [])
    x_channels = [c for c in channels if c.get("service") == "twitter"]
    if not x_channels:
        raise LookupError("No X (twitter) channel is connected in Buffer.")
    return x_channels[0]["id"]


def _due_at() -> Optional[str]:
    minutes = int(os.environ.get("BUFFER_REVIEW_DELAY_MINUTES", "60"))
    if minutes <= 0:
        return None
    due = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    return due.strftime("%Y-%m-%dT%H:%M:%S+00:00")


async def publish_thread(tool_context: ToolContext) -> dict:
    """Publishes the CURRENT saved thread to X through Buffer, as one real
    X thread. Takes no arguments: it always sends exactly the thread the user
    was shown, read from the saved draft.

    Returns:
        dict with 'status' ('dry_run', 'scheduled', 'queued' or 'error'),
        and 'dueAt' / 'post_id' when Buffer accepted it.
    """
    thread = tool_context.state.get("thread") or []
    if not thread:
        return {"status": "error", "error": "There is no saved thread to publish."}
    texts = [p["text"] for p in thread]
    check = measure_thread(texts)
    if not check["ok"]:
        return {"status": "error", "error": "Thread fails X's rules.", "problems": check["problems"]}

    due_at = _due_at()
    if os.environ.get("DRY_RUN", "true").lower() != "false":
        tool_context.state["thread_status"] = "dry_run"
        return {
            "status": "dry_run",
            "note": "DRY_RUN is on: NOTHING was sent to Buffer or X.",
            "would_send": build_buffer_payload(texts, "<x-channel-id>", due_at),
        }

    if not os.environ.get("BUFFER_API_KEY", "").strip():
        return {"status": "error", "error": "BUFFER_API_KEY is not set."}
    try:
        channel_id = await _resolve_x_channel()
        result = await _buffer_call("create_post", build_buffer_payload(texts, channel_id, due_at))
    except Exception as e:  # surface Buffer errors to the model as a tool result
        log.exception("Buffer create_post failed")
        return {"status": "error", "error": str(e)}

    post = result.get("post", result)
    status = "scheduled" if due_at else "queued"
    tool_context.state["thread_status"] = status
    tool_context.state["thread_due_at"] = post.get("dueAt") or due_at
    log.info("Buffer thread result: %s", result)
    return {
        "status": status,
        "buffer_status": post.get("status"),
        "dueAt": post.get("dueAt") or due_at,
        "post_id": post.get("id"),
        "posts": len(texts),
    }
