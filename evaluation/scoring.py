"""Per-case scoring and aggregate metrics (design doc §12.3)."""

from __future__ import annotations

import contextlib
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from agent.orchestrator import AgentResponse
from evaluation.cases import EvalCase
from housing.db import HousingDB
from tools.operations import execute
from tools.schemas import QueryArtifact, ToolCall
from tools.validator import PlanValidator, ValidatedPlan


@dataclass
class CaseResult:
    id: str
    family: str
    question: str
    expected_tool: str
    expected_response: str
    first_output_valid: bool
    first_tool: str | None
    tool_correct: bool
    kind: str
    kind_correct: bool
    plan_match: bool | None  # None when no analyze plan is expected
    exec_match: bool | None  # None unless the case expects a data answer
    answer_source: str
    faithful: bool | None  # None unless the system answered from data
    success: bool
    latency_ms: float
    model_calls: int
    answer: str
    failures: list[str] = field(default_factory=list)
    # Raw evidence for diagnosis: what the model actually emitted and what the agent did.
    planner_outputs: list[str] = field(default_factory=list)
    plan: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)


MAX_OUTPUT_CHARS = 2000  # per planner output kept in results.jsonl


# ---- normalization ----------------------------------------------------------------------------


def _norm_value(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, date):
        return v.isoformat()
    return v


def rows_key(rows: list[dict[str, Any]]) -> tuple:
    """Order-insensitive, rounding-tolerant fingerprint of a result table."""
    normalized = (tuple(sorted((k, _norm_value(v)) for k, v in r.items())) for r in rows)
    return tuple(sorted(normalized, key=repr))  # repr: rows may mix None and numbers


def plan_key(plan: dict[str, Any], validator: PlanValidator) -> tuple:
    """Semantic identity of a plan: resolved regions and effective period when it validates,
    otherwise the raw normalized fields (e.g. for ambiguous cities)."""
    result = validator.validate(plan)
    op = plan.get("operation")
    ranked = op == "rank"
    if isinstance(result, ValidatedPlan):
        p = result.plan
        return (
            "validated",
            p.metric,
            p.operation,
            frozenset(r.region_id for r in result.regions),
            result.state,
            None if op == "yoy_change" else result.start,
            result.end,
            p.aggregate,
            p.rank_by,
            p.order if ranked else None,
            p.limit if ranked else None,
        )
    cities = frozenset(
        ((c.get("city") or "").strip().lower(), c.get("state"), (c.get("county") or "").lower())
        for c in plan.get("cities", [])
    )
    return (
        "raw",
        plan.get("metric"),
        op,
        cities,
        plan.get("state_filter"),
        None if op == "yoy_change" else plan.get("start_month"),
        plan.get("end_month"),
        plan.get("aggregate"),
        plan.get("rank_by"),
        plan.get("order", "desc") if ranked else None,
        plan.get("limit", 10) if ranked else None,
    )


# ---- scoring ----------------------------------------------------------------------------------


class Scorer:
    def __init__(self, db: HousingDB, knowledge_available: bool):
        self.db = db
        self.validator = PlanValidator(db)
        self.knowledge_available = knowledge_available

    def gold_rows(self, case: EvalCase) -> list[tuple]:
        keys = []
        for plan in case.acceptable_plans():
            vplan = self.validator.validate(plan)
            if isinstance(vplan, ValidatedPlan):
                art = execute(vplan, self.db)
                if isinstance(art, QueryArtifact):
                    keys.append(rows_key(art.rows))
        return keys

    def score(
        self, case: EvalCase, resp: AgentResponse, planner_outputs: list[str], model_calls: int
    ) -> CaseResult:
        failures: list[str] = []

        first_call = None
        if planner_outputs:
            with contextlib.suppress(ValidationError):
                first_call = ToolCall.model_validate_json(planner_outputs[0]).call
        first_tool = first_call.tool if first_call else None
        tool_correct = first_tool == case.expected_tool
        if not tool_correct:
            failures.append(f"first tool {first_tool!r}, expected {case.expected_tool!r}")

        kb_case = case.expected_tool == "search_knowledge" and not self.knowledge_available
        if kb_case:
            # Without a knowledge base the turn must stop; score on choosing to search.
            kind_correct = tool_correct
        else:
            kind_correct = resp.kind == case.expected_response
            if not kind_correct:
                failures.append(f"response kind {resp.kind!r}, expected {case.expected_response!r}")

        plan_match = None
        if case.expected_tool == "analyze":
            gold = {plan_key(p, self.validator) for p in case.acceptable_plans()}
            plan_match = resp.plan is not None and plan_key(resp.plan, self.validator) in gold
            if not plan_match:
                failures.append("plan differs from gold")

        exec_match = None
        if case.expected_tool == "analyze" and case.expected_response == "answer":
            exec_match = resp.artifact is not None and rows_key(resp.artifact.rows) in set(
                self.gold_rows(case)
            )
            if not exec_match:
                failures.append("executed result differs from gold")

        faithful = None
        if resp.kind == "answer" and (resp.artifact is not None or resp.sources):
            faithful = resp.answer_source in ("model", "model_regenerated")

        # A data answer must also return the right rows; every other case is about the kind.
        success = kind_correct and (exec_match is not False)

        return CaseResult(
            id=case.id,
            family=case.family,
            question=case.question,
            expected_tool=case.expected_tool,
            expected_response=case.expected_response,
            first_output_valid=first_call is not None,
            first_tool=first_tool,
            tool_correct=tool_correct,
            kind=resp.kind,
            kind_correct=kind_correct,
            plan_match=plan_match,
            exec_match=exec_match,
            answer_source=resp.answer_source,
            faithful=faithful,
            success=success,
            latency_ms=resp.latency_ms.get("total", 0.0),
            model_calls=model_calls,
            answer=resp.answer,
            failures=failures,
            planner_outputs=[o[:MAX_OUTPUT_CHARS] for o in planner_outputs],
            plan=resp.plan,
            trace=[e.model_dump() for e in resp.trace],
        )


# ---- aggregation ------------------------------------------------------------------------------


def _rate(values: list[bool | None]) -> dict[str, Any]:
    scored = [v for v in values if v is not None]
    hits = sum(scored)
    return {
        "rate": round(hits / len(scored), 4) if scored else None,
        "n": len(scored),
        "hits": hits,
    }


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 1)
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1], 1)


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    latencies = [r.latency_ms for r in results]
    overall = {
        "cases": len(results),
        "envelope_valid": _rate([r.first_output_valid for r in results]),
        "tool_correct": _rate([r.tool_correct for r in results]),
        "kind_correct": _rate([r.kind_correct for r in results]),
        "plan_match": _rate([r.plan_match for r in results]),
        "execution_accuracy": _rate([r.exec_match for r in results]),
        "faithful_model_answer": _rate([r.faithful for r in results]),
        "turn_success": _rate([r.success for r in results]),
        # A direct respond(clarify) also counts as success on clarification cases; this shows
        # how often the model got there by calling analyze, as the gold call does.
        "clarify_via_analyze": _rate(
            [r.tool_correct for r in results if r.expected_response == "clarify"]
        ),
        "latency_ms_p50": _pct(latencies, 50),
        "latency_ms_p95": _pct(latencies, 95),
        "mean_model_calls": round(statistics.fmean(r.model_calls for r in results), 2)
        if results
        else None,
    }
    families: dict[str, dict[str, Any]] = {}
    for fam in sorted({r.family for r in results}):
        rs = [r for r in results if r.family == fam]
        families[fam] = {
            "cases": len(rs),
            "tool_correct": _rate([r.tool_correct for r in rs]),
            "kind_correct": _rate([r.kind_correct for r in rs]),
            "execution_accuracy": _rate([r.exec_match for r in rs]),
            "turn_success": _rate([r.success for r in rs]),
        }
    return {"overall": overall, "families": families}


def result_dict(r: CaseResult) -> dict[str, Any]:
    return asdict(r)
