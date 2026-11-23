"""Generate, filter, split, and write the Step 3 planner training data, plus a report.

Every candidate passes four filters (rejections are counted per reason):
  1. outcome: the gold call runs through the real validator and tools and ends as expected
     (an answer with rows, or a clarification for ambiguous / unknown cities);
  2. hold-out: ``evaluation.holdout.Holdout.conflicts`` (same plan meaning, eval city, or eval
     question);
  3. near-duplicate of an eval question (character 3-gram Jaccard >= NEAR_DUP);
  4. exact duplicate within the generated set.
Examples are written in the exact message format the agent uses at inference time.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent.prompts import PROMPT_VERSION, invalid_call_payload, planner_messages, retry_message
from evaluation.cases import EvalCase
from evaluation.holdout import Holdout, normalize_question
from housing.db import HousingDB
from tools.operations import execute
from tools.schemas import QueryArtifact, ToolCall, ToolError, canonical_json
from tools.validator import PlanValidator, ValidatedPlan
from training.pools import Pools
from training.templates import SCENARIO_SHARES, TEMPLATES, Ctx, Example

NEAR_DUP = 0.6
DEV_SHARE = 0.12
MAX_ATTEMPTS_PER_EXAMPLE = 40
SAMPLES_PER_SCENARIO = 30


def trigrams(text: str) -> set[str]:
    s = normalize_question(text)
    return {s[i : i + 3] for i in range(max(len(s) - 2, 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


@dataclass
class Built:
    record: dict[str, Any]
    example: Example
    max_eval_similarity: float


class Generator:
    def __init__(
        self,
        db: HousingDB,
        holdout: dict[str, Any],
        eval_cases: list[EvalCase],
        min_state_cities: int | None = None,
    ):
        self.db = db
        self.validator = PlanValidator(db)
        self.holdout = Holdout(holdout, self.validator)
        city_names = {c["city"] for c in holdout["cities"]}
        pool_kwargs = {} if min_state_cities is None else {"min_state_cities": min_state_cities}
        self.ctx = Ctx.for_data(Pools(db, city_names, **pool_kwargs), self.validator)
        self.eval_grams = [trigrams(c.question) for c in eval_cases]
        self.seen: set[str] = set()
        self.rejected: Counter[str] = Counter()

    # -- filters -----------------------------------------------------------------------------

    def outcome_ok(self, ex: Example) -> str | None:
        call = ex.target["call"]
        if call["tool"] != "analyze":
            return None
        vplan = self.validator.validate(call["plan"])
        if ex.expect == "clarify":
            ok = isinstance(vplan, ToolError) and vplan.kind in ("ambiguous_city", "city_not_found")
            return None if ok else "outcome_not_clarify"
        if not isinstance(vplan, ValidatedPlan):
            return f"outcome_{vplan.kind}"
        art = execute(vplan, self.db)
        if not isinstance(art, QueryArtifact):
            return "outcome_no_rows"
        return None

    def check(self, ex: Example) -> tuple[str | None, float]:
        try:
            canonical_json(ex.target)
        except ValidationError:
            return "invalid_target", 0.0
        if reason := self.outcome_ok(ex):
            return reason, 0.0
        plan = ex.target["call"].get("plan")
        if conflicts := self.holdout.conflicts(ex.question, plan):
            return f"holdout_{conflicts[0]}", 0.0
        grams = trigrams(ex.question)
        sim = max((jaccard(grams, g) for g in self.eval_grams), default=0.0)
        if sim >= NEAR_DUP:
            return "near_duplicate_of_eval", sim
        key = json.dumps([ex.question.lower(), ex.history, ex.state], sort_keys=True, default=str)
        if key in self.seen:
            return "duplicate", sim
        self.seen.add(key)
        return None, sim

    # -- records -----------------------------------------------------------------------------

    def record(self, ex: Example) -> dict[str, Any]:
        messages = planner_messages(self.db, ex.question, ex.history, ex.state)
        if ex.bad_call is not None:
            try:
                ToolCall.model_validate_json(json.dumps(ex.bad_call))
                raise AssertionError("retry example's bad call is unexpectedly valid")
            except ValidationError as exc:
                feedback = retry_message(invalid_call_payload(exc))
            messages += [{"role": "assistant", "content": json.dumps(ex.bad_call)}, feedback]
        messages.append({"role": "assistant", "content": canonical_json(ex.target)})
        return {
            "scenario": ex.scenario,
            "template": ex.template,
            "split": ex.split,
            "expect": ex.expect,
            "messages": messages,
        }

    # -- generation --------------------------------------------------------------------------

    def generate(self, n: int, seed: int) -> list[Built]:
        rng = random.Random(seed)
        built: list[Built] = []
        for scenario, share in SCENARIO_SHARES.items():
            templates = [t for t in TEMPLATES if t.scenario == scenario]
            target, accepted, attempts = round(n * share), 0, 0
            while accepted < target and attempts < target * MAX_ATTEMPTS_PER_EXAMPLE:
                template = templates[attempts % len(templates)]  # round-robin keeps balance
                attempts += 1
                split = "dev" if rng.random() < DEV_SHARE else "train"
                try:
                    ex = template.build(rng, self.ctx, split)
                except IndexError:  # an empty slot pool (e.g. no multi-state names in a fixture)
                    ex = None
                if ex is None:
                    self.rejected["builder_skip"] += 1
                    continue
                ex.template, ex.scenario, ex.split = template.id, scenario, split
                reason, sim = self.check(ex)
                if reason:
                    self.rejected[reason] += 1
                    continue
                built.append(Built(self.record(ex), ex, sim))
                accepted += 1
        return built


# ---- outputs ---------------------------------------------------------------------------------


def data_version(seed: int, n: int, dataset_version: str) -> str:
    code = b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))
    key = f"{seed}|{n}|{dataset_version}|{PROMPT_VERSION}|".encode() + code
    return hashlib.sha256(key).hexdigest()[:10]


def stats(built: list[Built], rejected: Counter) -> dict[str, Any]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for b in built:
        ex, call = b.example, b.example.target["call"]
        counts["scenario"][ex.scenario] += 1
        counts["template"][ex.template] += 1
        counts["split"][ex.split] += 1
        counts["expect"][ex.expect] += 1
        counts["tool"][call["tool"]] += 1
        if call["tool"] == "analyze":
            plan = call["plan"]
            counts["operation"][plan["operation"]] += 1
            counts["metric"][plan["metric"]] += 1
            counts["scope"]["state_filter" if plan.get("state_filter") else "cities"] += 1
        else:
            counts["respond_kind"][call.get("kind", call["tool"])] += 1
    sims = sorted(b.max_eval_similarity for b in built)
    questions = [b.example.question.lower() for b in built]
    return {
        "examples": len(built),
        "rejected": dict(rejected.most_common()),
        "counts": {k: dict(v.most_common()) for k, v in counts.items()},
        "max_similarity_to_eval": {
            "p50": round(statistics.median(sims), 3) if sims else None,
            "p95": round(sims[int(0.95 * (len(sims) - 1))], 3) if sims else None,
            "max": round(sims[-1], 3) if sims else None,
            "threshold": NEAR_DUP,
        },
        "distinct_question_share": round(len(set(questions)) / len(questions), 3)
        if questions
        else None,
        "mean_prompt_chars": round(
            statistics.fmean(sum(len(m["content"]) for m in b.record["messages"]) for b in built)
        )
        if built
        else None,
    }


def render_report(meta: dict[str, Any], s: dict[str, Any]) -> str:
    def table(title: str, counts: dict[str, int]) -> list[str]:
        total = sum(counts.values()) or 1
        rows = [f"| {k} | {v} | {v / total:.1%} |" for k, v in counts.items()]
        return [f"### {title}", "", "| Value | Count | Share |", "|---|---:|---:|", *rows, ""]

    sim = s["max_similarity_to_eval"]
    lines = [
        f"# Training data report: `{meta['data_version']}`",
        "",
        f"- {s['examples']} examples (seed {meta['seed']}, requested {meta['requested']}); "
        f"dataset `{meta['dataset_version']}`; prompt `{meta['prompt_version']}`",
        f"- Distinct questions: {s['distinct_question_share']:.1%}; mean prompt length "
        f"{s['mean_prompt_chars']} characters (about {s['mean_prompt_chars'] // 4} tokens)",
        f"- Wording overlap with the eval set (max character 3-gram Jaccard per example): "
        f"median {sim['p50']}, 95th percentile {sim['p95']}, max {sim['max']}; "
        f"anything at or above {sim['threshold']} was rejected",
        "",
        "## Rejected candidates",
        "",
        "| Reason | Count |",
        "|---|---:|",
        *[f"| {k} | {v} |" for k, v in s["rejected"].items()],
        "",
        "## Composition",
        "",
    ]
    for key in (
        "scenario",
        "split",
        "tool",
        "operation",
        "scope",
        "metric",
        "respond_kind",
        "template",
    ):
        if key in s["counts"]:
            lines += table(key, s["counts"][key])
    return "\n".join(lines)


def render_samples(built: list[Built]) -> str:
    by_scenario: dict[str, list[Built]] = defaultdict(list)
    for b in built:
        by_scenario[b.example.scenario].append(b)
    lines = ["# Training data samples for review", ""]
    for scenario, items in by_scenario.items():
        lines += [
            f"## {scenario}",
            "",
            "| Split | Template | Question | Target |",
            "|---|---|---|---|",
        ]
        for b in items[:SAMPLES_PER_SCENARIO]:
            ex = b.example
            q = ex.question.replace("|", "\\|")
            if ex.history:
                q = f"*(after: {ex.history[0]['content']})* {q}".replace("|", "\\|")
            if ex.bad_call:
                q += " *(retry after an invalid call)*"
            target = canonical_json(ex.target).replace("|", "\\|")
            lines.append(f"| {ex.split} | {ex.template} | {q} | `{target}` |")
        lines.append("")
    return "\n".join(lines)


def write_outputs(built: list[Built], meta: dict[str, Any], data_dir: Path, report_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    for split in ("train", "dev"):
        with (data_dir / f"{split}.jsonl").open("w") as fh:
            for b in built:
                if b.record["split"] == split:
                    fh.write(json.dumps(b.record, ensure_ascii=False) + "\n")
    s = stats(built, meta["rejected_counter"])
    meta = {k: v for k, v in meta.items() if k != "rejected_counter"}
    (data_dir / "manifest.json").write_text(json.dumps({**meta, **s}, indent=2) + "\n")
    (report_dir / "stats.json").write_text(json.dumps({**meta, **s}, indent=2) + "\n")
    (report_dir / "report.md").write_text(render_report(meta, s) + "\n")
    (report_dir / "samples.md").write_text(render_samples(built) + "\n")
    return s
