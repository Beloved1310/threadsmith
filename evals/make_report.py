"""Render an `adk eval` result file as a readable Markdown report.

Reads the .evalset_result.json that `adk eval` writes to
backend/thread_smith/.adk/eval_history/, looks up each rubric's plain-English
text in golden.json and eval_config.json, and writes one section per test:
its prompt, the tools it called, every metric with its threshold, score and
PASS/FAIL, and each rubric's score with the judge's reasoning.

    uv run python evals/make_report.py <result.json> <report.md> [title]
"""

import json
import pathlib
import sys

EVALS = pathlib.Path(__file__).resolve().parent
STATUS = {1: "PASS", 2: "FAIL", 3: "NOT EVALUATED"}


def rubric_texts() -> dict[str, str]:
    texts = {}
    config = json.loads((EVALS / "eval_config.json").read_text())
    for criterion in config["criteria"].values():
        for r in criterion.get("rubrics", []):
            texts[r["rubric_id"]] = r["rubric_content"]["text_property"]
    golden = json.loads((EVALS / "golden.json").read_text())
    for case in golden["eval_cases"]:
        for inv in case["conversation"]:
            for r in inv.get("rubrics", []):
                texts[r["rubric_id"]] = r["rubric_content"]["text_property"]
    return texts


def text_of(content: dict | None) -> str:
    parts = (content or {}).get("parts") or []
    return "\n".join(p["text"] for p in parts if p.get("text") and not p.get("thought"))


def fmt(score) -> str:
    return "n/a" if score is None else f"{score:.2f}"


def main(result_path: str, out_path: str, title: str = "ThreadSmith golden eval") -> None:
    result = json.loads(pathlib.Path(result_path).read_text())
    texts = rubric_texts()
    cases = result["eval_case_results"]
    failed = sum(c["final_eval_status"] != 1 for c in cases)

    lines = [
        f"# {title}",
        "",
        f"- Result file: `{pathlib.Path(result_path).name}`",
        f"- Eval set: `{result['eval_set_id']}`",
        f"- Tests passed: {len(cases) - failed}",
        f"- Tests failed: {failed}",
        "",
        "| Test | Status |",
        "|---|---|",
    ]
    lines += [f"| `{c['eval_id']}` | **{STATUS.get(c['final_eval_status'], '?')}** |" for c in cases]

    for case in cases:
        lines += ["", f"## `{case['eval_id']}`: {STATUS.get(case['final_eval_status'], '?')}", ""]
        for inv in case["eval_metric_result_per_invocation"]:
            actual = inv["actual_invocation"]
            tools = [t["name"] for t in (actual.get("intermediate_data") or {}).get("tool_uses") or []]
            lines += [
                f"**Prompt:** {text_of(actual['user_content'])}",
                "",
                f"**Tools called:** {', '.join(tools) or '(none)'}",
                "",
                "**Agent response:**",
                "",
                *[f"> {line}" for line in text_of(actual.get("final_response")).splitlines()],
                "",
                "| Metric | Threshold | Score | Status |",
                "|---|---|---|---|",
            ]
            metrics = [m for m in inv["eval_metric_results"] if m.get("threshold") is not None]
            lines += [
                f"| `{m['metric_name']}` | {m['threshold']} | {fmt(m.get('score'))} | "
                f"**{STATUS.get(m['eval_status'], '?')}** |"
                for m in metrics
            ]
            lines += ["", "| Rubric (plain English) | Score | Judge's reasoning |", "|---|---|---|"]
            for m in metrics:
                for rs in (m.get("details") or {}).get("rubric_scores") or []:
                    rubric = texts.get(rs["rubric_id"], "")
                    why = (rs.get("rationale") or "").replace("\n", " ").replace("|", "\\|")
                    lines.append(f"| **{rs['rubric_id']}**: {rubric} | {fmt(rs.get('score'))} | {why} |")

    pathlib.Path(out_path).write_text("\n".join(lines) + "\n")
    print(f"wrote {out_path}: Tests passed: {len(cases) - failed}, Tests failed: {failed}")


if __name__ == "__main__":
    main(*sys.argv[1:])
