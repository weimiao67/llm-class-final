"""Data-aware validation: turn a model-proposed plan into a ValidatedPlan or a typed ToolError."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from housing.db import HousingDB
from tools.resolve import CityResolver
from tools.schemas import AnalysisPlan, ResolvedRegion, ToolError

METRIC_LABEL = {"zhvi": "ZHVI (home values)", "zori": "ZORI (rents)"}


@dataclass
class ValidatedPlan:
    plan: AnalysisPlan
    regions: list[ResolvedRegion]  # empty when the plan targets a whole state
    state: str | None
    start: date
    end: date
    warnings: list[str] = field(default_factory=list)


def _month(text: str) -> date:
    year, month = text.split("-")
    return date(int(year), int(month), 1)


def _fmt(d: date) -> str:
    return d.strftime("%b %Y")


def field_errors(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {"field": ".".join(str(p) for p in err["loc"]) or "plan", "error": err["msg"]}
        for err in exc.errors()
    ]


class PlanValidator:
    def __init__(self, db: HousingDB):
        self.db = db
        self.resolver = CityResolver(db.regions)
        self._states: dict[str, set[str]] = {}
        for region in db.regions.values():
            for metric in region.metrics:
                self._states.setdefault(metric, set()).add(region.state)

    def validate(self, raw: AnalysisPlan | dict[str, Any]) -> ValidatedPlan | ToolError:
        if isinstance(raw, AnalysisPlan):
            plan = raw
        else:
            try:
                plan = AnalysisPlan.model_validate(raw)
            except ValidationError as exc:
                return ToolError(
                    kind="invalid_plan",
                    message="The plan does not match the AnalysisPlan schema.",
                    details={"errors": field_errors(exc)},
                )

        warnings: list[str] = []
        label = METRIC_LABEL[plan.metric]
        coverage = self.db.coverage.get(plan.metric)
        if coverage is None:
            return ToolError(
                kind="no_data",
                message=f"The active dataset contains no {label} data.",
                details={"metric": plan.metric},
            )

        regions: list[ResolvedRegion] = []
        if plan.state_filter:
            if plan.state_filter not in self._states.get(plan.metric, set()):
                return ToolError(
                    kind="no_data",
                    message=f"No {label} data is published for cities in {plan.state_filter}.",
                    details={"state": plan.state_filter, "metric": plan.metric},
                )
        else:
            result = self._resolve_cities(plan)
            if isinstance(result, ToolError):
                return result
            regions, metric_warnings = self._filter_by_metric(plan.metric, result)
            if not regions:
                names = ", ".join(f"{r.city}, {r.state}" for r in result)
                return ToolError(
                    kind="no_data",
                    message=f"No {label} data is published for {names}.",
                    details={"metric": plan.metric, "cities": [r.model_dump() for r in result]},
                )
            warnings += metric_warnings

        start = _month(plan.start_month) if plan.start_month else coverage.first_month
        end = _month(plan.end_month) if plan.end_month else coverage.last_month
        if end < coverage.first_month or start > coverage.last_month:
            return ToolError(
                kind="no_data",
                message=(
                    f"{label} data covers {_fmt(coverage.first_month)} to "
                    f"{_fmt(coverage.last_month)}; the requested period is outside it."
                ),
                details={
                    "metric": plan.metric,
                    "coverage": {
                        "first_month": coverage.first_month.isoformat(),
                        "last_month": coverage.last_month.isoformat(),
                    },
                },
            )
        if start < coverage.first_month:
            warnings.append(f"{label} data starts in {_fmt(coverage.first_month)}.")
            start = coverage.first_month
        if end > coverage.last_month:
            warnings.append(f"{label} data ends in {_fmt(coverage.last_month)}.")
            end = coverage.last_month

        return ValidatedPlan(
            plan=plan,
            regions=regions,
            state=plan.state_filter,
            start=start,
            end=end,
            warnings=warnings,
        )

    def _resolve_cities(self, plan: AnalysisPlan) -> list[ResolvedRegion] | ToolError:
        not_found, ambiguous = [], []
        resolved: dict[str, ResolvedRegion] = {}
        for ref in plan.cities:
            res = self.resolver.resolve(ref)
            if not res.matches:
                not_found.append({"query": ref.model_dump(), "suggestions": res.suggestions})
            elif res.ambiguous:
                ambiguous.append(
                    {
                        "query": ref.model_dump(),
                        "candidates": [m.model_dump() for m in res.matches],
                    }
                )
            else:
                resolved.setdefault(res.matches[0].region_id, res.matches[0])
        if not_found:
            names = ", ".join(
                f"{n['query']['city']}{', ' + n['query']['state'] if n['query']['state'] else ''}"
                for n in not_found
            )
            return ToolError(
                kind="city_not_found",
                message=f"Could not find: {names}.",
                details={"cities": not_found},
            )
        if ambiguous:
            names = ", ".join(a["query"]["city"] for a in ambiguous)
            return ToolError(
                kind="ambiguous_city",
                message=f"More than one place matches: {names}. Ask the user which one.",
                details={"cities": ambiguous},
            )
        return list(resolved.values())

    def _filter_by_metric(
        self, metric: str, regions: list[ResolvedRegion]
    ) -> tuple[list[ResolvedRegion], list[str]]:
        kept = [r for r in regions if metric in self.db.regions[r.region_id].metrics]
        dropped = [r for r in regions if r not in kept]
        warnings = []
        if dropped and kept:
            names = ", ".join(f"{r.city}, {r.state}" for r in dropped)
            warnings.append(f"No {METRIC_LABEL[metric]} data is published for {names}; excluded.")
        return kept, warnings
