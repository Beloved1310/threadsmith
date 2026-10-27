# Backend image for Agent Runtime: the AG-UI bridge (backend/main.py) on :8080.
# The frontend is deployed separately to Cloud Run.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/

WORKDIR /code

COPY ./pyproject.toml ./README.md ./uv.lock ./
RUN uv sync --frozen --no-dev

# agent.py loads skills/ from the project root, two levels above itself.
COPY ./skills ./skills
COPY ./backend ./backend

ARG AGENT_VERSION=0.0.0
ENV AGENT_VERSION=${AGENT_VERSION}

EXPOSE 8080

CMD ["uv", "run", "--no-dev", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
