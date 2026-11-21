"""Hold-out set: what Step 3 training data must not contain, so eval scores aren't inflated.

Three guards, because each alone has gaps:

- **plans**: every gold and alternative plan. Compared by meaning (``plan_key``: resolved regions
  and effective period), so a training example with the same analysis is rejected even when it
  is phrased differently or spells the period out. This is the only guard for the statewide
  cases, which name no city.
- **cities**: every city named in an eval plan, matched by name in any state (strict).
- **questions**: normalized eval question texts (exact match; near-duplicate detection is the
  Step 3 generator's job).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evaluation.cases import EvalCase
from evaluation.scoring import plan_key
from tools.validator import PlanValidator


def normalize_question(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def build_holdout(cases: list[EvalCase], cases_file: str) -> dict[str, Any]:
    cities: dict[tuple, dict[str, str | None]] = {}
    plans: list[dict[str, Any]] = []
    for case in cases:
        for plan in case.acceptable_plans():
            if plan not in plans:
                plans.append(plan)
            for city in plan.get("cities", []):
                key = (city["city"].lower(), city.get("state"))
                cities.setdefault(key, {"city": city["city"], "state": city.get("state")})
    return {
        "cases_file": cases_file,
        "note": "Step 3 training data must not contain these plans, cities, or questions. "
        "Check with evaluation.holdout.Holdout.conflicts().",
        "cities": sorted(cities.values(), key=lambda c: (c["state"] or "", c["city"])),
        "plans": plans,
        "questions": sorted({c.question for c in cases}),
    }


class Holdout:
    def __init__(self, data: dict[str, Any], validator: PlanValidator):
        self.validator = validator
        self.city_names = {c["city"].strip().lower() for c in data["cities"]}
        self.plan_keys = {plan_key(p, validator) for p in data["plans"]}
        self.questions = {normalize_question(q) for q in data["questions"]}

    @classmethod
    def load(cls, path: Path | str, validator: PlanValidator) -> Holdout:
        return cls(json.loads(Path(path).read_text()), validator)

    def conflicts(self, question: str, plan: dict[str, Any] | None = None) -> list[str]:
        """Reasons a candidate training example overlaps the eval set (empty list = allowed)."""
        reasons = []
        if normalize_question(question) in self.questions:
            reasons.append("question")
        if plan is not None:
            if plan_key(plan, self.validator) in self.plan_keys:
                reasons.append("plan")
            if any(c["city"].strip().lower() in self.city_names for c in plan.get("cities", [])):
                reasons.append("city")
        return reasons
