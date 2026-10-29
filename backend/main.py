"""AG-UI bridge: exposes the thread_smith agent to the ThreadBoard frontend.

Run from threadsmith/:  uv run --project .. uvicorn backend.main:app --port 8010
"""

import logging
import pathlib
from typing import Optional

from ag_ui.core import RunAgentInput
from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.memory import BaseMemoryService, VertexAiMemoryBankService
from google.adk.sessions import (
    BaseSessionService,
    InMemorySessionService,
    VertexAiSessionService,
)

log = logging.getLogger(__name__)

load_dotenv(pathlib.Path(__file__).parent / "thread_smith" / ".env")

from backend.thread_smith import db, guardrails  # noqa: E402  (needs .env first)
from backend.thread_smith.agent import app as adk_app  # noqa: E402
from backend.thread_smith.engine import agent_engine  # noqa: E402

app = FastAPI(title="threadsmith AG-UI backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3010"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def _session_service() -> BaseSessionService:
    """Agent Engine sessions on Agent Runtime, in-memory locally.

    A deployed container is wiped on scale-to-zero, so in-memory sessions
    would lose the thread draft between requests.
    """
    engine = agent_engine()
    if engine is None:
        return InMemorySessionService()
    log.info("Using VertexAiSessionService for engine %s", engine.engine_id)
    return VertexAiSessionService(
        project=engine.project,
        location=engine.location,
        agent_engine_id=engine.engine_id,
    )


def _memory_service() -> Optional[BaseMemoryService]:
    """Agent Engine Memory Bank on Agent Runtime; none locally.

    ADKAgent saves each session to memory when it is cleaned up, which is
    what load_memory later searches.
    """
    engine = agent_engine()
    if engine is None:
        return None
    log.info("Using VertexAiMemoryBankService for engine %s", engine.engine_id)
    return VertexAiMemoryBankService(
        project=engine.project,
        location=engine.location,
        agent_engine_id=engine.engine_id,
    )


def _unstreamed_run_config(input: RunAgentInput) -> RunConfig:
    """ADKAgent's default run config with streaming off.

    ADKAgent streams (SSE) by default, and Model Armor does not screen streamed
    Gemini calls: an injection passes with no block and no error.
    """
    default = adk_agent._default_run_config(input)
    return default.model_copy(update={"streaming_mode": StreamingMode.NONE})


adk_agent = ADKAgent.from_app(
    adk_app,
    user_id="threadsmith-user",
    session_service=_session_service(),
    memory_service=_memory_service(),
    run_config_factory=_unstreamed_run_config if guardrails.MA_TEMPLATE else None,
)
add_adk_fastapi_endpoint(app, adk_agent, path="/api/adk")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/threads")
def threads() -> dict:
    """Threads sent to Buffer (or dry-run), newest first."""
    return {"threads": db.list_threads()}
