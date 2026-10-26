"""AG-UI bridge: exposes the thread_smith agent to the ThreadBoard frontend.

Run from threadsmith/:  uv run --project .. uvicorn backend.main:app --port 8010
"""

import logging
import pathlib

from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

log = logging.getLogger(__name__)

load_dotenv(pathlib.Path(__file__).parent / "thread_smith" / ".env")

from backend.thread_smith import db  # noqa: E402  (needs .env first)
from backend.thread_smith.agent import app as adk_app  # noqa: E402

app = FastAPI(title="threadsmith AG-UI backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3010"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local only: in-memory sessions, which is all a single-user demo needs.
adk_agent = ADKAgent.from_app(adk_app, user_id="threadsmith-user")
add_adk_fastapi_endpoint(app, adk_agent, path="/api/adk")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/threads")
def threads() -> dict:
    """Threads sent to Buffer (or dry-run), newest first."""
    return {"threads": db.list_threads()}
