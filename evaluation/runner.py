"""Run an evaluation set through the real agent with any model client and write a report."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.decoding import DecodingProfile
from agent.model_clients.base import ModelClient, ModelOutput
from agent.orchestrator import Agent
from agent.prompts import PROMPT_VERSION
from evaluation.cases import EvalCase
from evaluation.scoring import CaseResult, Scorer, result_dict, summarize
from housing.db import HousingDB
from tools.knowledge import KnowledgeBase

ModelFactory = Callable[[EvalCase], ModelClient]


class RecordingClient:
    """Wraps a model client and records every call so the scorer can see raw planner output."""

    def __init__(self, inner: ModelClient):
        self.inner = inner
        self.model_id = inner.model_id
        self.calls: list[tuple[str, str, str]] = []  # (profile name, step, text)

    def complete(
        self,
        messages: list[dict[str, str]],
        profile: DecodingProfile,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelOutput:
        out = self.inner.complete(messages, profile, json_schema)
        self.calls.append((profile.name, profile.step, out.text))
        return out

    @property
    def planner_outputs(self) -> list[str]:
        return [text for _, step, text in self.calls if step == "plan"]


def run_eval(
    cases: list[EvalCase],
    db: HousingDB,
    model_factory: ModelFactory,
    knowledge: KnowledgeBase | None = None,
    progress: Callable[[int, int, CaseResult], None] | None = None,
    constrained: bool = True,
) -> list[CaseResult]:
    scorer = Scorer(db, knowledge_available=knowledge is not None)
    results = []
    for i, case in enumerate(cases, start=1):
        model = RecordingClient(model_factory(case))
        agent = Agent(
            db, model, knowledge=knowledge, validator=scorer.validator, constrained=constrained
        )
        resp = agent.run_turn(
            case.question,
            history=case.history,
            state=case.state.model_dump(exclude_defaults=True),
        )
        result = scorer.score(case, resp, model.planner_outputs, len(model.calls))
        results.append(result)
        if progress:
            progress(i, len(cases), result)
    return results


def _git_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _fmt(rate: dict[str, Any]) -> str:
    if rate["rate"] is None:
        return "—"
    return f"{rate['rate'] * 100:.1f}% ({rate['hits']}/{rate['n']})"


def render_markdown(meta: dict[str, Any], summary: dict[str, Any], results: list[CaseResult]):
    o = summary["overall"]
    lines = [
        f"# Evaluation report: {meta['model_id']}",
        "",
        f"- Run: `{meta['run_id']}` · cases: `{meta['cases_file']}` ({o['cases']} cases)",
        f"- Dataset `{meta['dataset_version']}` · prompt `{meta['prompt_version']}`"
        f" · code `{meta['git_sha']}` · knowledge base: {meta['knowledge_base']}"
        f" · planning: {meta.get('decoding', 'constrained')}",
        "",
        "## Overall",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Envelope valid (first output) | {_fmt(o['envelope_valid'])} |",
        f"| Tool selection (first call) | {_fmt(o['tool_correct'])} |",
        f"| Response kind | {_fmt(o['kind_correct'])} |",
        f"| Plan match | {_fmt(o['plan_match'])} |",
        f"| **Execution accuracy** | **{_fmt(o['execution_accuracy'])}** |",
        f"| Faithful model answer | {_fmt(o['faithful_model_answer'])} |",
        f"| Turn success | {_fmt(o['turn_success'])} |",
        f"| Clarification cases reached via analyze | {_fmt(o['clarify_via_analyze'])} |",
        f"| Latency p50 / p95 (ms) | {o['latency_ms_p50']} / {o['latency_ms_p95']} |",
        f"| Mean model calls per turn | {o['mean_model_calls']} |",
        "",
        "## By family",
        "",
        "| Family | Cases | Tool | Kind | Execution | Success |",
        "|---|---:|---|---|---|---|",
    ]
    for fam, f in summary["families"].items():
        lines.append(
            f"| {fam} | {f['cases']} | {_fmt(f['tool_correct'])} | {_fmt(f['kind_correct'])} | "
            f"{_fmt(f['execution_accuracy'])} | {_fmt(f['turn_success'])} |"
        )
    failed = [r for r in results if not r.success]
    lines += ["", f"## Failures ({len(failed)})", ""]
    for r in failed:
        lines.append(f"- **{r.id}** — {r.question}  ")
        lines.append(f"  {'; '.join(r.failures) or 'see results.jsonl'}  ")
        if r.planner_outputs:
            first = r.planner_outputs[0].replace("`", "'")[:240]
            lines.append(f"  first output: `{first}`")
    return "\n".join(lines) + "\n"


def write_report(
    out_dir: Path,
    results: list[CaseResult],
    *,
    model_id: str,
    db: HousingDB,
    cases_file: str,
    knowledge_base: bool,
    constrained: bool = True,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "run_id": out_dir.name,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model_id": model_id,
        "dataset_version": db.dataset_version,
        "prompt_version": PROMPT_VERSION,
        "git_sha": _git_sha(),
        "cases_file": cases_file,
        "knowledge_base": "available" if knowledge_base else "unavailable",
        "decoding": "constrained" if constrained else "unconstrained",
    }
    summary = summarize(results)
    (out_dir / "summary.json").write_text(json.dumps({"meta": meta, **summary}, indent=2) + "\n")
    with (out_dir / "results.jsonl").open("w") as fh:
        for r in results:
            fh.write(json.dumps(result_dict(r)) + "\n")
    (out_dir / "report.md").write_text(render_markdown(meta, summary, results))
    return {"meta": meta, **summary}
