"""Deterministic operation registry.

Each operation post-processes rows from the compiled query into a QueryArtifact: the full rows
(shown in the UI's data tab and downloadable), a compact ``summary`` (the only thing the model
sees), chart hints, the SQL actually run, and warnings.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from housing.db import HousingDB
from tools.compiler import compile_plan
from tools.schemas import QueryArtifact, ToolError
from tools.validator import METRIC_LABEL, ValidatedPlan

Rows = list[dict[str, Any]]
Summary = dict[str, Any]
OperationFn = Callable[[ValidatedPlan, Rows, list[str]], tuple[Rows, Summary]]

MAX_NAMED_EXCLUSIONS = 10


def _r(x: float | None, digits: int = 2) -> float | None:
    return None if x is None else round(x, digits)


def _pct(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start == 0:
        return None
    return (end - start) / start * 100


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _label(row: dict[str, Any]) -> str:
    return f"{row['city']}, {row['state']}"


def _ident(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "region_id": row["region_id"],
        "city": row["city"],
        "state": row["state"],
        "county": row["county"],
        "size_rank": row["size_rank"],
    }


def _cap(vplan: ValidatedPlan, items: list, warnings: list[str]) -> list:
    """For state-wide scopes, show the model only the ``limit`` largest cities (by Zillow size
    rank, smaller = larger city) rather than an arbitrary alphabetical slice; rows stay complete."""
    limit = vplan.plan.limit
    if vplan.state and len(items) > limit:
        warnings.append(
            f"Summary shows the {limit} largest of {len(items)} cities (by Zillow size rank); "
            "all rows are in the data table. Use rank to order by a measure."
        )
        return sorted(items, key=lambda i: (i["size_rank"], i["region_id"]))[:limit]
    return items


def _exclusion_warning(excluded: Rows, reason: str) -> str:
    names = ", ".join(_label(r) for r in excluded[:MAX_NAMED_EXCLUSIONS])
    more = len(excluded) - MAX_NAMED_EXCLUSIONS
    return f"{len(excluded)} city(ies) excluded {reason}: {names}" + (
        f" and {more} more." if more > 0 else "."
    )


def _split_full_window(rows: Rows, *, need_start: bool = True) -> tuple[Rows, Rows, date, date]:
    """Split rows into those covering the common data window and those that don't."""
    window_start = min(r["start_month"] for r in rows)
    window_end = max(r["end_month"] for r in rows)
    full, partial = [], []
    for r in rows:
        ok = r["end_month"] == window_end and (not need_start or r["start_month"] == window_start)
        (full if ok else partial).append(r)
    return full, partial, window_start, window_end


def _endpoint_warnings(vplan: ValidatedPlan, rows: Rows, warnings: list[str]) -> None:
    for row in rows:
        if row["start_month"] > vplan.start:
            warnings.append(f"Data for {_label(row)} starts in {row['start_month']:%b %Y}.")
        if row["end_month"] < vplan.end:
            warnings.append(f"Data for {_label(row)} ends in {row['end_month']:%b %Y}.")


RANK_KEY = {"value": "end_value", "change": "change", "pct_change": "pct_change"}


def _unique_labels(rows: Rows) -> dict[str, str]:
    """'City, ST' per region, adding the county when two regions would share a label."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[_label(r)] = counts.get(_label(r), 0) + 1
    return {
        r["region_id"]: _label(r) + (f" ({r['county']})" if counts[_label(r)] > 1 else "")
        for r in rows
    }


def _with_change(row: dict[str, Any]) -> dict[str, Any]:
    two_points = row["observations"] >= 2
    change = row["end_value"] - row["start_value"] if two_points else None
    pct = _pct(row["start_value"], row["end_value"]) if two_points else None
    return {**row, "change": change, "pct_change": pct}


# ---- operations ------------------------------------------------------------------------------


def op_series(vplan: ValidatedPlan, rows: Rows, warnings: list[str]) -> tuple[Rows, Summary]:
    per_region: dict[str, dict[str, Any]] = {}
    for row in rows:
        s = per_region.setdefault(
            row["region_id"],
            {
                **_ident(row),
                "first_month": row["month"],
                "observations": 0,
                "min_value": row["value"],
                "max_value": row["value"],
            },
        )
        s["observations"] += 1
        s["last_month"], s["latest_value"] = row["month"], row["value"]
        s["min_value"] = min(s["min_value"], row["value"])
        s["max_value"] = max(s["max_value"], row["value"])
    cities = []
    for s in per_region.values():
        gaps = _months_between(s["first_month"], s["last_month"]) + 1 - s["observations"]
        if gaps:
            warnings.append(f"{s['city']}, {s['state']} has {gaps} missing month(s) in range.")
        cities.append(
            {
                **s,
                "missing_months": gaps,
                "latest_value": _r(s["latest_value"]),
                "min_value": _r(s["min_value"]),
                "max_value": _r(s["max_value"]),
            }
        )
    return rows, {"cities": cities}


def op_change(vplan: ValidatedPlan, rows: Rows, warnings: list[str]) -> tuple[Rows, Summary]:
    out = [_with_change(r) for r in rows]
    if vplan.state:
        # Statewide: only cities measured over the same window are comparable in the summary.
        full, partial, ws, we = _split_full_window(out)
        comparable = [r for r in full if r["change"] is not None]
        excluded = partial + [r for r in full if r["change"] is None]
        if excluded:
            warnings.append(
                _exclusion_warning(
                    excluded, f"for lacking data over the full window {ws:%b %Y}–{we:%b %Y}"
                )
            )
    else:
        _endpoint_warnings(vplan, out, warnings)
        for r in out:
            if r["change"] is None:
                warnings.append(f"{_label(r)} has only one observation in range; no change.")
        comparable = out
    summary = [
        {
            **_ident(r),
            "start_month": r["start_month"],
            "start_value": _r(r["start_value"]),
            "end_month": r["end_month"],
            "end_value": _r(r["end_value"]),
            "change": _r(r["change"]),
            "pct_change": _r(r["pct_change"]),
        }
        for r in comparable
    ]
    return out, {"cities": _cap(vplan, summary, warnings)}


def op_yoy_change(vplan: ValidatedPlan, rows: Rows, warnings: list[str]) -> tuple[Rows, Summary]:
    out = []
    for r in rows:
        change = None if r["prior_value"] is None else r["end_value"] - r["prior_value"]
        out.append({**r, "change": change, "pct_change": _pct(r["prior_value"], r["end_value"])})

    if vplan.state:
        # Statewide: only cities current as of the latest month and with a prior-year value.
        latest = max(r["end_month"] for r in out)
        shown, excluded = [], []
        for r in out:
            current = r["end_month"] == latest and r["change"] is not None
            (shown if current else excluded).append(r)
        if excluded:
            warnings.append(
                _exclusion_warning(
                    excluded, f"for lacking both {latest:%b %Y} and the prior-year observation"
                )
            )
    else:
        shown = out
        for r in out:
            if r["end_month"] < vplan.end:
                warnings.append(
                    f"Latest data for {_label(r)} is {r['end_month']:%b %Y}; its year-over-year "
                    "change is as of that month, not the requested end."
                )
            if r["prior_value"] is None:
                warnings.append(
                    f"{_label(r)} has no observation 12 months before {r['end_month']:%b %Y}."
                )
    summary = [
        {
            **_ident(r),
            "end_month": r["end_month"],
            "end_value": _r(r["end_value"]),
            "prior_month": r["prior_month"],
            "prior_value": _r(r["prior_value"]),
            "change": _r(r["change"]),
            "pct_change": _r(r["pct_change"]),
        }
        for r in shown
    ]
    return out, {"cities": _cap(vplan, summary, warnings)}


def op_extrema(vplan: ValidatedPlan, rows: Rows, warnings: list[str]) -> tuple[Rows, Summary]:
    summary = [
        {
            **_ident(r),
            "max_month": r["max_month"],
            "max_value": _r(r["max_value"]),
            "min_month": r["min_month"],
            "min_value": _r(r["min_value"]),
            "observations": r["observations"],
        }
        for r in rows
    ]
    return rows, {"cities": _cap(vplan, summary, warnings), "tie_rule": "earliest month wins"}


def op_rank(vplan: ValidatedPlan, rows: Rows, warnings: list[str]) -> tuple[Rows, Summary]:
    plan = vplan.plan
    key = RANK_KEY[plan.rank_by]
    full, partial, window_start, window_end = _split_full_window(
        [_with_change(r) for r in rows], need_start=plan.rank_by != "value"
    )
    eligible = [r for r in full if r[key] is not None]
    excluded = partial + [r for r in full if r[key] is None]

    sign = -1 if plan.order == "desc" else 1
    eligible.sort(key=lambda r: (sign * r[key], r["state"], r["city"], r["region_id"]))
    labels = _unique_labels(eligible)
    ranked = [
        {"rank": i, "label": labels[r["region_id"]], **r} for i, r in enumerate(eligible, start=1)
    ]

    if excluded:
        warnings.append(
            _exclusion_warning(
                excluded,
                f"for lacking data over the full window {window_start:%b %Y}–{window_end:%b %Y}",
            )
        )
    if len(ranked) > plan.limit:
        warnings.append(f"Showing top {plan.limit} of {len(ranked)}; all rows are in the table.")
    top = [
        {
            "rank": r["rank"],
            "label": r["label"],
            **_ident(r),
            "start_value": _r(r["start_value"]),
            "end_value": _r(r["end_value"]),
            "change": _r(r["change"]),
            "pct_change": _r(r["pct_change"]),
        }
        for r in ranked[: plan.limit]
    ]
    summary = {
        "rank_by": plan.rank_by,
        "order": plan.order,
        "window": {"start_month": window_start, "end_month": window_end},
        "eligible": len(ranked),
        "excluded": len(excluded),
        "top": top,
    }
    return ranked, summary


def op_aggregate(vplan: ValidatedPlan, rows: Rows, warnings: list[str]) -> tuple[Rows, Summary]:
    first, last = rows[0], rows[-1]
    summary = {
        "aggregate": vplan.plan.aggregate,
        "scope": vplan.state or [f"{r.city}, {r.state}" for r in vplan.regions],
        "first": {
            "month": first["month"],
            "value": _r(first["value"]),
            "regions": first["regions"],
        },
        "last": {"month": last["month"], "value": _r(last["value"]), "regions": last["regions"]},
        "change": _r(last["value"] - first["value"]),
        "pct_change": _r(_pct(first["value"], last["value"])),
        "months": len(rows),
    }
    if vplan.regions:
        reporting = max(r["regions"] for r in rows)
        if reporting < len(vplan.regions):
            warnings.append(
                f"Only {reporting} of the {len(vplan.regions)} requested cities have data in "
                "this period; the aggregate covers only those."
            )
    if first["regions"] != last["regions"]:
        warnings.append(
            f"The number of reporting cities changes from {first['regions']} to "
            f"{last['regions']} over the period, which affects the aggregate."
        )
    return rows, summary


def op_coverage(vplan: ValidatedPlan, rows: Rows, warnings: list[str]) -> tuple[Rows, Summary]:
    out = []
    for r in rows:
        expected = _months_between(r["first_month"], r["last_month"]) + 1
        out.append({**r, "missing_months": expected - r["observations"]})
    summary = [
        {
            **_ident(r),
            "first_month": r["first_month"],
            "last_month": r["last_month"],
            "observations": r["observations"],
            "missing_months": r["missing_months"],
        }
        for r in out
    ]
    return out, {"cities": _cap(vplan, summary, warnings)}


OPERATIONS: dict[str, OperationFn] = {
    "series": op_series,
    "change": op_change,
    "yoy_change": op_yoy_change,
    "extrema": op_extrema,
    "rank": op_rank,
    "aggregate": op_aggregate,
    "coverage": op_coverage,
}

CHART_HINTS = {
    "series": {"type": "line", "x": "month", "y": "value", "series": "region_id"},
    "aggregate": {"type": "line", "x": "month", "y": "value", "series": None},
    "rank": {"type": "bar", "x": "label", "y": None},  # y set from rank_by in execute()
}


def execute(vplan: ValidatedPlan, db: HousingDB) -> QueryArtifact | ToolError:
    plan = vplan.plan
    compiled = compile_plan(vplan)
    rows = db.query(compiled.sql, compiled.params)
    period = {"start_month": vplan.start, "end_month": vplan.end}
    if not rows:
        return ToolError(
            kind="no_data",
            message=(
                f"No {METRIC_LABEL[plan.metric]} observations for the requested places between "
                f"{vplan.start:%b %Y} and {vplan.end:%b %Y}."
            ),
            details={
                "metric": plan.metric,
                "period": {k: v.isoformat() for k, v in period.items()},
            },
        )

    warnings = list(vplan.warnings)
    if vplan.regions and plan.operation != "aggregate":
        present = {r["region_id"] for r in rows}
        for region in vplan.regions:
            if region.region_id not in present:
                warnings.append(
                    f"No data for {region.city}, {region.state} between "
                    f"{vplan.start:%b %Y} and {vplan.end:%b %Y}."
                )

    out_rows, summary = OPERATIONS[plan.operation](vplan, rows, warnings)
    chart = CHART_HINTS.get(plan.operation)
    if chart and plan.operation == "rank":
        chart = {**chart, "y": RANK_KEY[plan.rank_by]}
    return QueryArtifact(
        operation=plan.operation,
        metric=plan.metric,
        rows=out_rows,
        summary=summary,
        regions=vplan.regions,
        period=period,
        sql=compiled.describe(),
        chart=chart,
        warnings=warnings,
        dataset_version=db.dataset_version,
    )
