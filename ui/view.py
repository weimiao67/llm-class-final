"""Turn an /v1/ask response into what the UI shows: cards, tables, a chart, the trace.

Pure functions over the JSON the API returns, so they're unit-tested without Streamlit. Nothing
here computes a new number: cards and charts only reformat the artifact's own rows and summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
import plotly.graph_objects as go

MAX_CARDS = 4  # more cities than this read better as a table
METRIC_NAMES = {"zhvi": "Home value (ZHVI)", "zori": "Rent (ZORI)"}
GAP_CAPTION = "Missing months are gaps; values are not interpolated or forecast."
TRACE_CAPTION = "These are the real tool events, not model reasoning."
# Row columns that hold months or values, for formatting the data table.
MONTH_COLUMNS = {"month", "start_month", "end_month", "prior_month", "first_month",
                 "last_month", "max_month", "min_month"}  # fmt: skip
VALUE_COLUMNS = {"value", "start_value", "end_value", "prior_value", "max_value", "min_value",
                 "change", "latest_value"}  # fmt: skip
PCT_COLUMNS = {"pct_change"}


@dataclass(frozen=True)
class Card:
    label: str
    value: str
    delta: str | None = None
    caption: str = ""


def month_label(value: str | None) -> str:
    """'2025-03-01' -> 'Mar 2025'."""
    if not value:
        return "—"
    return f"{date.fromisoformat(str(value)[:10]):%b %Y}"


def money(value: float | None) -> str:
    return "—" if value is None else f"${value:,.0f}"


def signed_money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{'+' if value >= 0 else '−'}${abs(value):,.0f}"


def pct(value: float | None) -> str | None:
    return None if value is None else f"{value:+.1f}%"


def city_label(entry: dict[str, Any]) -> str:
    return entry.get("label") or f"{entry['city']}, {entry['state']}"


def metric_cards(artifact: dict[str, Any] | None) -> list[Card]:
    """Headline numbers for up to four cities (or one statewide aggregate); [] otherwise."""
    if not artifact:
        return []
    op, summary = artifact["operation"], artifact.get("summary") or {}
    if op == "aggregate":
        last, first = summary.get("last") or {}, summary.get("first") or {}
        if not last:
            return []
        label = f"{summary.get('aggregate', '').capitalize()} across {summary.get('scope', '')}"
        caption = f"{month_label(last.get('month'))} · {last.get('regions', 0):,} cities"
        if first and first.get("month") != last.get("month"):
            caption = f"{month_label(first.get('month'))} → {caption}"
        delta = pct(summary.get("pct_change")) if summary.get("months", 0) > 1 else None
        return [Card(label.strip(), money(last.get("value")), delta, caption)]
    cities = summary.get("cities")
    if not cities or len(cities) > MAX_CARDS:
        return []
    return [_city_card(op, c) for c in cities]


def _city_card(op: str, c: dict[str, Any]) -> Card:
    label = city_label(c)
    if op in ("change", "yoy_change"):
        start = c.get("prior_month") if op == "yoy_change" else c.get("start_month")
        caption = f"{month_label(start)} → {month_label(c.get('end_month'))}"
        if c.get("change") is not None:
            caption += f" · {signed_money(c['change'])}"
        return Card(label, money(c.get("end_value")), pct(c.get("pct_change")), caption)
    if op == "extrema":
        caption = (
            f"High in {month_label(c.get('max_month'))} · low {money(c.get('min_value'))} "
            f"in {month_label(c.get('min_month'))}"
        )
        return Card(label, money(c.get("max_value")), None, caption)
    if op == "series":
        caption = (
            f"Latest, {month_label(c.get('last_month'))} · range {money(c.get('min_value'))}"
            f"–{money(c.get('max_value'))}"
        )
        return Card(label, money(c.get("latest_value")), None, caption)
    if op == "coverage":
        caption = (
            f"{month_label(c.get('first_month'))} → {month_label(c.get('last_month'))} · "
            f"{c.get('missing_months', 0)} missing"
        )
        return Card(label, f"{c.get('observations', 0):,} months", None, caption)
    return Card(label, "—")


RANK_COLUMNS = ["rank", "label", "start_value", "end_value", "change", "pct_change", "value"]


def all_warnings(response: dict[str, Any]) -> list[str]:
    """The turn's warnings once each (the response repeats the artifact's own warnings)."""
    artifact = response.get("artifact") or {}
    return list(
        dict.fromkeys([*(response.get("warnings") or []), *(artifact.get("warnings") or [])])
    )


def ranking_frame(artifact: dict[str, Any]) -> pd.DataFrame:
    """The ranked top rows with only the columns a ranking needs (all rows are in the data tab)."""
    top = (artifact.get("summary") or {}).get("top") or []
    df = rows_frame({"rows": top})
    return df[[c for c in RANK_COLUMNS if c in df.columns]]


def rows_frame(artifact: dict[str, Any] | None) -> pd.DataFrame:
    """The queried rows for display: months as 'Mar 2025', dollars and percents formatted."""
    rows = (artifact or {}).get("rows") or []
    df = pd.DataFrame(rows)
    for col in df.columns:
        if col in MONTH_COLUMNS:
            df[col] = df[col].map(month_label)
        elif col in VALUE_COLUMNS:
            df[col] = df[col].map(money)
        elif col in PCT_COLUMNS:
            df[col] = df[col].map(lambda v: pct(v) or "—")
    return df


def rows_csv(artifact: dict[str, Any] | None) -> bytes:
    """The raw rows as CSV (unformatted values, ISO months), for download."""
    rows = (artifact or {}).get("rows") or []
    return pd.DataFrame(rows).to_csv(index=False).encode()


def figure(artifact: dict[str, Any] | None) -> go.Figure | None:
    """Plotly figure from the artifact's chart hint, or None when there's nothing to plot."""
    if not artifact or not artifact.get("chart") or not artifact.get("rows"):
        return None
    hint, rows = artifact["chart"], artifact["rows"]
    metric = METRIC_NAMES.get(artifact["metric"], artifact["metric"])
    fig = go.Figure()
    if hint["type"] == "line":
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            key = city_label(r) if hint.get("series") else metric
            groups.setdefault(key, []).append(r)
        for name, group in groups.items():
            x, y = _with_gaps(group, hint["x"], hint["y"])
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=name, connectgaps=False))
        fig.update_layout(yaxis_title=metric, yaxis_tickprefix="$", yaxis_tickformat=",.0f")
    elif hint["type"] == "bar":
        top = (artifact.get("summary") or {}).get("top") or rows
        y_col = hint["y"]
        fig.add_trace(go.Bar(x=[city_label(r) for r in top], y=[r[y_col] for r in top]))
        if y_col == "pct_change":
            fig.update_layout(yaxis_title=f"{metric}, % change", yaxis_ticksuffix="%")
        else:
            title = f"{metric}, change" if y_col == "change" else metric
            fig.update_layout(yaxis_title=title, yaxis_tickprefix="$", yaxis_tickformat=",.0f")
    else:
        return None
    fig.update_layout(margin={"l": 10, "r": 10, "t": 30, "b": 10}, hovermode="x unified",
                      legend={"orientation": "h"})  # fmt: skip
    return fig


def _with_gaps(rows: list[dict[str, Any]], x_col: str, y_col: str):
    """Monthly x/y with None for every missing month, so the line breaks instead of bridging
    the gap (connectgaps=False only breaks at explicit None values)."""
    points = {date.fromisoformat(str(r[x_col])[:10]): r[y_col] for r in rows}
    if not points:
        return [], []
    months = pd.date_range(min(points), max(points), freq="MS").date
    return list(months), [points.get(m) for m in months]


def resolved_cities(artifact: dict[str, Any] | None) -> pd.DataFrame:
    regions = (artifact or {}).get("regions") or []
    return pd.DataFrame(regions, columns=["city", "state", "county", "region_id"])


def trace_frame(trace: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(trace, columns=["step", "tool", "status", "duration_ms", "detail"])
    return df.rename(columns={"duration_ms": "ms"})


def status_line(ready: dict[str, Any] | None, error: str | None = None) -> tuple[str, str]:
    """(level, text) for the sidebar status: level is 'ok', 'warn' or 'error'."""
    if error:
        return "error", error
    ready = ready or {}
    model = ready.get("model_id", "unknown model")
    data = ready.get("dataset_version", "?")
    if ready.get("status") == "ready":
        return "ok", f"Ready · {model} · data {data}"
    endpoint = (ready.get("model") or {}).get("status", "not ready")
    return "warn", f"Model endpoint {endpoint} · {model} · data {data}"


def history_for_api(turns: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The conversation as API messages; failed turns (no response) are left out."""
    messages = []
    for t in turns:
        if t.get("response"):
            messages.append({"role": "user", "content": t["question"]})
            messages.append({"role": "assistant", "content": t["response"]["answer"]})
    return messages
