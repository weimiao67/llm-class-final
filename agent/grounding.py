"""Grounding helpers: numeric-faithfulness check, templated answers, clarification text.

The faithfulness check is deliberately strict: every number in the model's answer must match a
number in the tool summary (at the precision the answer states it), a year in the result, or a
number the user typed. Anything else triggers a regeneration and then a templated fallback.

Known limitation: rounding to fewer decimals is allowed ("about 2%" for 2.1), so a small
integer can coincidentally match a rounded value. Large invented values are always caught.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from tools.schemas import QueryArtifact, ToolError

# 1,234,567.89 | 1234.5 | -2.1 | 535 ; optional currency symbol is ignored by the pattern
_NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")


def _walk(obj: Any, out: list[float], years: set[int]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, date):
        years.add(obj.year)  # months are stored as day 1, so only the year is meaningful
    elif isinstance(obj, str):
        if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", obj):
            years.add(int(obj[:4]))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out, years)
    elif isinstance(obj, list | tuple):
        for v in obj:
            _walk(v, out, years)


def numbers_in_text(text: str) -> list[tuple[float, int]]:
    """Return (value, decimals) for each number in ``text``."""
    found = []
    for m in _NUMBER.finditer(text):
        raw = m.group().replace(",", "")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        found.append((float(raw), decimals))
    return found


def unsupported_numbers(answer: str, evidence: Any, question: str = "") -> list[str]:
    """Numbers in ``answer`` that are not grounded in ``evidence`` or the question."""
    values: list[float] = []
    years: set[int] = set()
    _walk(evidence, values, years)
    question_values = {v for v, _ in numbers_in_text(question)}
    bad = []
    for value, decimals in numbers_in_text(answer):
        if value in question_values or (decimals == 0 and int(value) in years):
            continue
        if any(round(abs(v), decimals) == abs(value) for v in values):
            continue
        bad.append(f"{value:.{decimals}f}")
    return bad


# ---- deterministic text -----------------------------------------------------------------------


def _money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:,.0f}"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1f}%"


def _month(d: Any) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d:%b %Y}"


def _name(c: dict[str, Any]) -> str:
    return f"{c['city']}, {c['state']}"


def template_answer(art: QueryArtifact) -> str:
    """A plain answer built only from the artifact, used when the model's answer is ungrounded."""
    s, metric = art.summary, art.metric.upper()
    if art.operation == "rank":
        top = "; ".join(
            f"{c['rank']}. {c['label']} ({_pct(c['pct_change'])}, {_money(c['end_value'])})"
            if s["rank_by"] != "value"
            else f"{c['rank']}. {c['label']} ({_money(c['end_value'])})"
            for c in s["top"]
        )
        return f"{metric} ranking by {s['rank_by']} ({s['eligible']} cities): {top}."
    if art.operation == "aggregate":
        return (
            f"The {s['aggregate']} {metric} went from {_money(s['first']['value'])} in "
            f"{_month(s['first']['month'])} to {_money(s['last']['value'])} in "
            f"{_month(s['last']['month'])} ({_pct(s['pct_change'])})."
        )
    parts = []
    for c in s.get("cities", []):
        if art.operation in ("change", "yoy_change"):
            start_key = "prior" if art.operation == "yoy_change" else "start"
            parts.append(
                f"{_name(c)}: {_money(c[f'{start_key}_value'])} ({_month(c[f'{start_key}_month'])})"
                f" to {_money(c['end_value'])} ({_month(c['end_month'])}), {_pct(c['pct_change'])}"
            )
        elif art.operation == "extrema":
            parts.append(
                f"{_name(c)}: highest {_money(c['max_value'])} in {_month(c['max_month'])}, "
                f"lowest {_money(c['min_value'])} in {_month(c['min_month'])}"
            )
        elif art.operation == "series":
            parts.append(
                f"{_name(c)}: {c['observations']} months from {_month(c['first_month'])} to "
                f"{_month(c['last_month'])}, latest {_money(c['latest_value'])}"
            )
        elif art.operation == "coverage":
            parts.append(
                f"{_name(c)}: {_month(c['first_month'])} to {_month(c['last_month'])}, "
                f"{c['observations']} months, {c['missing_months']} missing"
            )
    return f"{metric} — " + "; ".join(parts) + "."


def clarification_text(err: ToolError) -> str:
    if err.kind == "ambiguous_city":
        lines = []
        for item in err.details["cities"]:
            options = ", ".join(
                f"{c['city']}, {c['state']} ({c['county']})" for c in item["candidates"]
            )
            lines.append(f'Several places match "{item["query"]["city"]}": {options}.')
        return " ".join(lines) + " Which one do you mean?"
    if err.kind == "city_not_found":
        lines = []
        for item in err.details["cities"]:
            name = item["query"]["city"]
            if item["suggestions"]:
                lines.append(
                    f"I couldn't find {name}. Did you mean {', '.join(item['suggestions'])}?"
                )
            else:
                lines.append(
                    f"I couldn't find {name} in the data. Please check the city and state."
                )
        return " ".join(lines)
    return err.message
