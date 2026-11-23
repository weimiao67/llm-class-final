"""Re-score a saved run against a corrected case file, without calling any model.

Only cases whose definition changed between the two files are re-scored. Their response kind,
proposed plan, and (for data answers) executed rows are recomputed from what the run saved in
results.jsonl. Every other case keeps its original score, so a correction can't silently change
unrelated results. Runs saved before results kept the proposed plan score ``plan_match`` as
False for changed cases, the same as a missing plan at run time.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from evaluation.cases import EvalCase
from evaluation.scoring import CaseResult, plan_key, rows_key, summarize
from housing.db import HousingDB
from tools.operations import execute
from tools.schemas import QueryArtifact
from tools.validator import PlanValidator, ValidatedPlan


def changed_ids(base: list[EvalCase], corrected: list[EvalCase]) -> set[str]:
    old = {c.id: c.model_dump() for c in base}
    new = {c.id: c.model_dump() for c in corrected}
    if old.keys() != new.keys():
        raise ValueError("the corrected file must contain exactly the same case ids")
    return {i for i in new if new[i] != old[i]}


def load_results(path: Path) -> list[CaseResult]:
    names = {f.name for f in fields(CaseResult)}
    return [
        CaseResult(**{k: v for k, v in json.loads(line).items() if k in names})
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def rescore_case(r: CaseResult, case: EvalCase, db: HousingDB, validator: PlanValidator):
    failures = []
    r.expected_response, r.expected_tool = case.expected_response, case.expected_tool
    r.tool_correct = r.first_tool == case.expected_tool
    if not r.tool_correct:
        failures.append(f"first tool {r.first_tool!r}, expected {case.expected_tool!r}")
    r.kind_correct = r.kind == case.expected_response
    if not r.kind_correct:
        failures.append(f"response kind {r.kind!r}, expected {case.expected_response!r}")
    r.plan_match = None
    if case.expected_tool == "analyze":
        gold = {plan_key(p, validator) for p in case.acceptable_plans()}
        r.plan_match = r.plan is not None and plan_key(r.plan, validator) in gold
        if not r.plan_match:
            failures.append("plan differs from gold")
    r.exec_match = None
    if case.expected_tool == "analyze" and case.expected_response == "answer":
        r.exec_match = _rows_match(r, case, db, validator)
        if not r.exec_match:
            failures.append("executed result differs from gold")
    r.success = r.kind_correct and (r.exec_match is not False)
    r.failures = failures


def _rows_match(r: CaseResult, case: EvalCase, db, validator) -> bool:
    def rows(plan: dict[str, Any]):
        vplan = validator.validate(plan)
        art = execute(vplan, db) if isinstance(vplan, ValidatedPlan) else None
        return rows_key(art.rows) if isinstance(art, QueryArtifact) else None

    if r.kind != "answer" or r.plan is None:
        return False
    got = rows(r.plan)
    return got is not None and got in {rows(p) for p in case.acceptable_plans()}


def rescore_run(
    run_dir: Path, base: list[EvalCase], corrected: list[EvalCase], db: HousingDB
) -> tuple[list[CaseResult], dict[str, Any]]:
    ids = changed_ids(base, corrected)
    by_id = {c.id: c for c in corrected}
    validator = PlanValidator(db)
    results = load_results(run_dir / "results.jsonl")
    for r in results:
        if r.id in ids:
            rescore_case(r, by_id[r.id], db, validator)
    return results, summarize(results)
