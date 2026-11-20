"""Compile a ValidatedPlan into parameterized SQL.

Every value from the plan is a bound ``?`` parameter. The only text spliced into SQL comes from the
fixed fragments below, selected by enum values that the schema already restricted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from tools.validator import ValidatedPlan

AGGREGATE_SQL = {
    "avg": "avg(value)",
    "median": "median(value)",
    "min": "min(value)",
    "max": "max(value)",
    "count": "count(*)",
}

GROUP_COLS = "region_id, city, state, county, size_rank"
YOY_LOWER_BOUND = date(1900, 1, 1)

_PER_REGION_ENDPOINTS = f"""
SELECT {GROUP_COLS},
       arg_min(value, month) AS start_value, min(month) AS start_month,
       arg_max(value, month) AS end_value,   max(month) AS end_month,
       count(*) AS observations
FROM s GROUP BY {GROUP_COLS}
ORDER BY state, city, region_id"""

_TEMPLATES = {
    "series": f"SELECT {GROUP_COLS}, month, value FROM s ORDER BY state, city, region_id, month",
    "change": _PER_REGION_ENDPOINTS,
    "rank": _PER_REGION_ENDPOINTS,
    "extrema": f"""
, w AS (
    SELECT *, max(value) OVER (PARTITION BY region_id) AS mx,
              min(value) OVER (PARTITION BY region_id) AS mn
    FROM s)
SELECT {GROUP_COLS},
       any_value(mx) AS max_value, min(month) FILTER (WHERE value = mx) AS max_month,
       any_value(mn) AS min_value, min(month) FILTER (WHERE value = mn) AS min_month,
       count(*) AS observations
FROM w GROUP BY {GROUP_COLS}
ORDER BY state, city, region_id""",
    "yoy_change": """
, latest AS (SELECT region_id, max(month) AS m FROM s GROUP BY region_id)
SELECT s.region_id, s.city, s.state, s.county, s.size_rank,
       l.m AS end_month, s.value AS end_value,
       p.month AS prior_month, p.value AS prior_value
FROM latest l
JOIN s ON s.region_id = l.region_id AND s.month = l.m
LEFT JOIN s p ON p.region_id = l.region_id
             AND p.month = CAST(l.m - INTERVAL 12 MONTH AS DATE)
ORDER BY s.state, s.city, s.region_id""",
    "coverage": f"""
SELECT {GROUP_COLS},
       min(month) AS first_month, max(month) AS last_month, count(*) AS observations
FROM s GROUP BY {GROUP_COLS}
ORDER BY state, city, region_id""",
}


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    params: list[Any]

    def describe(self) -> dict[str, Any]:
        return {
            "template": self.sql.strip(),
            "params": [p.isoformat() if isinstance(p, date) else p for p in self.params],
        }


def compile_plan(vplan: ValidatedPlan) -> CompiledQuery:
    plan = vplan.plan
    params: list[Any] = [plan.metric]

    if vplan.state:
        scope = "state = ?"
        params.append(vplan.state)
    else:
        scope = f"region_id IN ({', '.join('?' for _ in vplan.regions)})"
        params += [r.region_id for r in vplan.regions]

    # YoY compares each city's latest observed month (<= end) with 12 months before it. That
    # month can precede ``end`` because of gaps, so no lower bound is applied.
    lower = YOY_LOWER_BOUND if plan.operation == "yoy_change" else vplan.start
    params += [lower, vplan.end]

    base = f"""WITH s AS (
    SELECT {GROUP_COLS}, month, value FROM observations
    WHERE metric = ? AND {scope} AND month BETWEEN ? AND ?
)"""

    if plan.operation == "aggregate":
        body = f"""
SELECT month, {AGGREGATE_SQL[plan.aggregate]} AS value, count(*) AS regions
FROM s GROUP BY month ORDER BY month"""
    else:
        body = _TEMPLATES[plan.operation]
    return CompiledQuery(sql=base + body, params=params)
