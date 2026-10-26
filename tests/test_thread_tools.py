"""Unit tests for the deterministic parts of ThreadSmith.

No model and no network: Buffer is faked at tools._buffer_call, so these run
offline and never post anything.
"""

import asyncio

import pytest

from threadsmith.backend.thread_smith import agent, tools


class _FakeContext:
    """Stands in for ADK's ToolContext: the tools only touch .state."""

    def __init__(self, state=None):
        self.state = dict(state or {})


def _saved(posts):
    ctx = _FakeContext()
    tools.save_thread(posts, ctx)
    return ctx


# --- measure_thread / save_thread --------------------------------------------


def test_measure_thread_accepts_a_valid_thread():
    result = tools.measure_thread(["hook 🧵", "middle", "end"])

    assert result["ok"] is True
    assert result["problems"] == []
    assert [p["index"] for p in result["posts"]] == [1, 2, 3]


def test_measure_thread_flags_exactly_the_post_over_280():
    result = tools.measure_thread(["ok", "x" * 300, "ok"])

    assert result["ok"] is False
    over = [p for p in result["posts"] if not p["within_limit"]]
    assert [(p["index"], p["over_by"]) for p in over] == [(2, 20)]
    assert result["problems"] == ["Post 2 is 20 characters over 280."]


def test_measure_thread_allows_exactly_280():
    assert tools.measure_thread(["x" * 280, "y"])["ok"] is True


def test_measure_thread_rejects_empty_and_too_short_threads():
    assert tools.measure_thread(["only one"])["ok"] is False
    result = tools.measure_thread(["hook", "   "])
    assert result["ok"] is False
    assert "Post 2 is empty." in result["problems"]


def test_measure_thread_rejects_too_many_posts():
    assert tools.measure_thread(["p"] * (tools.MAX_POSTS + 1))["ok"] is False


def test_save_thread_writes_structured_state_for_the_ui():
    ctx = _FakeContext({"thread_status": "scheduled"})

    result = tools.save_thread(["  hook 🧵 ", "second"], ctx)

    assert result["ok"] is True
    assert ctx.state["thread"][0]["text"] == "hook 🧵"  # trimmed
    assert ctx.state["thread_ok"] is True
    assert ctx.state["thread_text"] == "1/2: hook 🧵\n\n2/2: second"
    assert ctx.state["thread_status"] == "draft"  # a new draft resets publish status


# --- build_buffer_payload ------------------------------------------------------


def test_buffer_payload_matches_buffers_thread_contract():
    payload = tools.build_buffer_payload(["a", "b", "c"], "chan", "2026-10-26T10:00:00+00:00")

    assert payload["text"] == "a"  # outer text == first item
    assert payload["metadata"]["twitter"]["thread"] == [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    assert payload["mode"] == "customScheduled"
    assert payload["dueAt"] == "2026-10-26T10:00:00+00:00"
    assert payload["schedulingType"] == "automatic"


def test_buffer_payload_without_delay_goes_to_queue():
    payload = tools.build_buffer_payload(["a", "b"], "chan", None)

    assert payload["mode"] == "addToQueue"
    assert "dueAt" not in payload


# --- publish_thread ------------------------------------------------------------


def _no_buffer(monkeypatch):
    async def boom(tool, args):
        raise AssertionError(f"Buffer must not be called, got {tool}")

    monkeypatch.setattr(tools, "_buffer_call", boom)


def test_publish_dry_run_sends_nothing(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    _no_buffer(monkeypatch)
    ctx = _saved(["hook", "end"])

    result = asyncio.run(tools.publish_thread(ctx))

    assert result["status"] == "dry_run"
    assert result["would_send"]["metadata"]["twitter"]["thread"][1] == {"text": "end"}
    assert ctx.state["thread_status"] == "dry_run"


def test_publish_defaults_to_dry_run_when_unset(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    _no_buffer(monkeypatch)

    assert asyncio.run(tools.publish_thread(_saved(["a", "b"])))["status"] == "dry_run"


def test_publish_refuses_without_a_thread(monkeypatch):
    _no_buffer(monkeypatch)

    result = asyncio.run(tools.publish_thread(_FakeContext()))

    assert result["status"] == "error"


def test_publish_refuses_a_thread_over_the_limit(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    _no_buffer(monkeypatch)
    ctx = _saved(["ok", "x" * 281])

    result = asyncio.run(tools.publish_thread(ctx))

    assert result["status"] == "error"
    assert "Post 2" in result["problems"][0]


def test_publish_live_resolves_the_x_channel_and_sends_the_saved_thread(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("BUFFER_API_KEY", "test-key")
    monkeypatch.setenv("BUFFER_REVIEW_DELAY_MINUTES", "60")
    calls = []

    async def fake_buffer(tool, args):
        calls.append((tool, args))
        if tool == "get_account":
            return {"organizations": [{"id": "org1"}]}
        if tool == "list_channels":
            return [{"service": "linkedin", "id": "li"}, {"service": "twitter", "id": "x1"}]
        if tool == "create_post":
            return {"post": {"id": "p1", "status": "scheduled", "dueAt": args["dueAt"]}}
        raise AssertionError(tool)

    monkeypatch.setattr(tools, "_buffer_call", fake_buffer)
    ctx = _saved(["hook 🧵", "two", "three"])

    result = asyncio.run(tools.publish_thread(ctx))

    sent = calls[-1][1]
    assert calls[-1][0] == "create_post"
    assert sent["channelId"] == "x1"
    assert [t["text"] for t in sent["metadata"]["twitter"]["thread"]] == ["hook 🧵", "two", "three"]
    assert result["status"] == "scheduled"
    assert result["post_id"] == "p1"
    assert ctx.state["thread_status"] == "scheduled"


def test_publish_reports_a_missing_x_channel(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("BUFFER_API_KEY", "test-key")

    async def fake_buffer(tool, args):
        if tool == "get_account":
            return {"organizations": [{"id": "org1"}]}
        return [{"service": "linkedin", "id": "li"}]

    monkeypatch.setattr(tools, "_buffer_call", fake_buffer)

    result = asyncio.run(tools.publish_thread(_saved(["a", "b"])))

    assert result["status"] == "error"
    assert "twitter" in result["error"]


# --- agent wiring ----------------------------------------------------------------


def test_publishing_is_gated_by_confirmation():
    assert agent.publish_tool._require_confirmation is True


def test_orchestrator_has_no_raw_posting_tool():
    names = [getattr(t, "name", None) for t in agent.root_agent.tools]

    assert names == ["research_agent", "thread_writer", "publish_thread"]


@pytest.mark.parametrize("status", ["dry_run", "scheduled"])
def test_track_stage_records_a_real_publish(monkeypatch, status):
    saved = []
    monkeypatch.setattr(agent.db, "save_thread", lambda **kw: saved.append(kw))
    ctx = _saved(["a", "b"])

    agent._track_stage(agent.publish_tool, {}, ctx, {"status": status, "dueAt": None})

    assert ctx.state["pipeline_stage"] == status
    assert saved[0]["posts"] == ["a", "b"]


def test_track_stage_ignores_a_rejected_confirmation(monkeypatch):
    monkeypatch.setattr(agent.db, "save_thread", lambda **kw: pytest.fail("must not save"))
    ctx = _FakeContext({"pipeline_stage": "awaiting_approval"})

    agent._track_stage(agent.publish_tool, {}, ctx, {"error": "This tool call is rejected."})

    assert ctx.state["pipeline_stage"] == "awaiting_approval"
