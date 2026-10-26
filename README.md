# ThreadSmith

Turn an idea or a link into a researched X thread, checked post by post,
approved by you, then sent to X as one real thread through Buffer.

A sibling of Social Spark (the parent repo): same ADK multi-agent shape, same
AG-UI + CopilotKit frontend stack, specialised for one format.

## How it differs from Social Spark

| | Social Spark | ThreadSmith |
|---|---|---|
| Output | one post (LinkedIn or X) | a thread of 2-12 X posts |
| Draft lives in | the model's reply text | session state: `state["thread"]`, structured per post |
| 280-char check | model is told to call `check_text_length` | `save_thread` measures every post in code; `publish_thread` refuses any over |
| Publishing tool | Buffer's raw MCP `create_post` (model builds args) | `publish_thread()`: zero args, payload built from the approved state |
| Buffer dry run | none: every approved post is real | `DRY_RUN=true` by default, shows the exact payload, sends nothing |
| UI | stepper + gallery | ThreadBoard: X-style cards, char rings, per-post quick edits |

## Layout

```
threadsmith/
  backend/
    main.py                 AG-UI bridge on :8010, plus /api/threads
    thread_smith/           the ADK agent package (adk web discovers it)
      agent.py              thread_smith -> research_agent, thread_writer, publish_thread
      tools.py              measure_thread, save_thread, publish_thread, Buffer payload
      db.py                 SQLite record of sent / dry-run threads
      .env                  your config (gitignored; copy from threadsmith/.env.example)
  skills/
    thread-style/SKILL.md   hook, one idea per post, closing post
    brand-voice/SKILL.md    personalise this one
  frontend/                 Next.js + CopilotKit on :3010
    app/components/ThreadBoard.tsx   the thread, live from shared state
    app/components/ConfirmAction.tsx approval card showing the full thread
    app/components/ThreadHistory.tsx sent threads
  tests/test_thread_tools.py         offline unit tests (Buffer faked)
  evals/                             golden set for adk eval
```

Python dependencies come from the parent repo's `pyproject.toml` / `uv.lock`
(`--project ..`), so there is nothing extra to install.

## Run it

```bash
cp threadsmith/.env.example threadsmith/backend/thread_smith/.env   # then fill in
./threadsmith/run-backend.sh      # :8010
./threadsmith/run-frontend.sh     # :3010, second terminal
```

Chat and trace inspector without the frontend:

```bash
cd threadsmith && uv run --project .. adk web backend
```

## Test it

| Layer | Command | Needs |
|---|---|---|
| Unit (thread rules, Buffer payload, dry run, approval gate wiring) | `uv run pytest threadsmith/tests` (repo root) | nothing |
| Agent behaviour | `cd threadsmith && uv run --project .. adk eval backend/thread_smith evals/golden.json --config_file_path evals/eval_config.json` | Gemini access |
| End to end, dry run | both run scripts, write a thread, approve it | Gemini access |
| Real send | `DRY_RUN=false`, approve; it is scheduled `BUFFER_REVIEW_DELAY_MINUTES` ahead, delete it in Buffer if you like | Gemini + Buffer with X connected |

Note `adk eval` exits 0 even when cases fail: read the summary line.

## Gotchas

- `BUFFER_API_KEY` goes in `backend/thread_smith/.env`, never in an
  `.env.example`: those are committed.
- Images are not part of v1. Buffer needs a public HTTPS URL for media, which
  means the parent repo's GCS signing setup; add it once text threads work.
- Guardrails (Model Armor, DLP) from the parent's Lab 3 are not wired in here.
