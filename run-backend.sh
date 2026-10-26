#!/usr/bin/env bash
# ThreadSmith AG-UI backend on :8010. Uses the parent repo's uv environment.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --project ..
exec uv run --project .. uvicorn backend.main:app --port 8010 --reload --reload-dir backend
