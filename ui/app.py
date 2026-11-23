"""Housing Market AI Analyst: Streamlit UI (design doc §15).

A client of the agent API, like curl: every answer comes from POST /v1/ask.

    uv run uvicorn api.main:app                  # terminal 1 (MODEL_BACKEND=stub by default)
    uv run streamlit run ui/app.py               # terminal 2

Environment: ANALYST_API_URL (default http://localhost:8000), ANALYST_API_KEY (if the API has one).
"""

from __future__ import annotations

import json
import os
from typing import Any

import streamlit as st

from ui.client import AnalystClient, APIError
from ui.view import (
    GAP_CAPTION,
    METRIC_NAMES,
    TRACE_CAPTION,
    all_warnings,
    figure,
    history_for_api,
    metric_cards,
    month_label,
    ranking_frame,
    resolved_cities,
    rows_csv,
    rows_frame,
    status_line,
    trace_frame,
)

EXAMPLES = [
    "What was Mead, CO's highest ZHVI month in 2025?",
    "Rank Colorado cities by ZHVI growth in 2025",
    "What about rent?",
    "How did home values change in Oakwood, OH since 2020?",
    "What will Denver rent be next year?",
    "What is ZORI and how is it smoothed?",
]
KIND_LABELS = {"clarify": "Needs clarification", "unsupported": "Not supported",
               "out_of_scope": "Out of scope", "no_data": "No data", "error": "Error"}  # fmt: skip


@st.cache_resource
def get_client() -> AnalystClient:
    url = os.environ.get("ANALYST_API_URL", "http://localhost:8000")
    return AnalystClient(url, api_key=os.environ.get("ANALYST_API_KEY") or None)


@st.cache_data(ttl=30, show_spinner=False)
def get_status() -> tuple[str, str]:
    try:
        return status_line(get_client().ready())
    except APIError as exc:
        return status_line(None, str(exc))


def init_session() -> None:
    st.session_state.setdefault("turns", [])  # [{question, response | None, error | None}]
    st.session_state.setdefault("state", {})  # ConversationState from the last answered turn
    st.session_state.setdefault("selected", None)


def ask(question: str) -> None:
    turns = st.session_state.turns
    try:
        with st.spinner("Planning and running the analysis…"):
            response = get_client().ask(
                question, history=history_for_api(turns), state=st.session_state.state
            )
    except APIError as exc:
        turns.append({"question": question, "response": None, "error": str(exc)})
    else:
        turns.append({"question": question, "response": response, "error": None})
        st.session_state.state = response.get("updated_state") or st.session_state.state
    st.session_state.selected = len(turns) - 1


def sidebar() -> None:
    with st.sidebar:
        st.title("Housing Market AI Analyst")
        level, text = get_status()
        {"ok": st.success, "warn": st.warning, "error": st.error}[level](text)

        question = st.chat_input("Ask about housing data or Zillow metrics…")
        st.caption("Examples")
        for example in EXAMPLES:
            if st.button(example, width="stretch"):
                question = example
        if question:
            ask(question)

        turns = st.session_state.turns
        if turns:
            st.divider()
            st.caption("Conversation")
            for i, t in reversed(list(enumerate(turns))):
                marker = "▶ " if i == st.session_state.selected else ""
                if st.button(f"{marker}{t['question']}", key=f"turn-{i}",
                             width="stretch"):  # fmt: skip
                    st.session_state.selected = i
                    st.rerun()
            if st.button("New conversation", type="secondary"):
                st.session_state.turns, st.session_state.state = [], {}
                st.session_state.selected = None
                st.rerun()


def main_area() -> None:
    turns, selected = st.session_state.turns, st.session_state.selected
    if selected is None or not turns:
        st.header("Ask a question")
        st.write(
            "Ask about U.S. city home values (ZHVI) or rents (ZORI): changes over time, highs and "
            "lows, rankings within a state, or how Zillow's indexes are built. The model plans "
            "the analysis; the numbers come from a deterministic query over Zillow's data."
        )
        st.caption("Type in the sidebar or pick an example.")
        return
    turn = turns[selected]
    st.subheader(turn["question"])
    if turn["error"]:
        st.error(turn["error"])
        return
    response = turn["response"]
    artifact = response.get("artifact")
    rows_label = f"Queried data · {artifact['rows_total']:,} rows" if artifact else "Queried data"
    tab_answer, tab_data, tab_trace = st.tabs(["AI response", rows_label, "Evidence & trace"])
    with tab_answer:
        answer_tab(response, artifact)
    with tab_data:
        data_tab(artifact)
    with tab_trace:
        trace_tab(response, artifact)


def answer_tab(response: dict[str, Any], artifact: dict[str, Any] | None) -> None:
    for warning in all_warnings(response):
        st.warning(warning)
    kind = response["kind"]
    with st.container(border=True):
        if kind != "answer":
            st.caption(KIND_LABELS.get(kind, kind))
        st.markdown(response["answer"])
        for s in response.get("sources") or []:
            st.caption(f"Source: [{s['title']} — {s['section']}]({s['source_url']})")
    cards = metric_cards(artifact)
    if cards:
        for col, card in zip(st.columns(len(cards)), cards, strict=True):
            col.metric(card.label, card.value, card.delta, help=None)
            col.caption(card.caption)
    elif artifact and artifact["operation"] == "rank":
        st.dataframe(ranking_frame(artifact), hide_index=True, width="stretch")
    fig = figure(artifact)
    if fig is not None:
        st.plotly_chart(fig, width="stretch")
        if artifact["chart"]["type"] == "line":
            st.caption(GAP_CAPTION)


def data_tab(artifact: dict[str, Any] | None) -> None:
    if not artifact or not artifact.get("rows"):
        st.info("This answer didn't query any data.")
        return
    if artifact.get("rows_truncated"):
        st.warning(
            f"Showing the first {len(artifact['rows']):,} of {artifact['rows_total']:,} rows."
        )
    st.dataframe(rows_frame(artifact), hide_index=True, width="stretch")
    st.download_button("Download CSV", rows_csv(artifact), file_name="queried_data.csv",
                       mime="text/csv")  # fmt: skip


def trace_tab(response: dict[str, Any], artifact: dict[str, Any] | None) -> None:
    st.markdown("**Dataset**")
    st.write(
        f"Version `{response['dataset_version']}` · model `{response['model_id']}` · "
        f"prompt `{response.get('prompt_version', '?')}`"
    )
    if artifact:
        period = artifact.get("period") or {}
        st.write(
            f"{METRIC_NAMES.get(artifact['metric'], artifact['metric'])} · "
            f"`{artifact['operation']}` · {month_label(period.get('start_month'))} to "
            f"{month_label(period.get('end_month'))}"
        )
        regions = resolved_cities(artifact)
        if not regions.empty:
            st.markdown("**Resolved cities**")
            st.dataframe(regions, hide_index=True, width="stretch")
        st.markdown("**SQL template and parameters**")
        st.code(artifact["sql"]["template"], language="sql")
        st.code(json.dumps(artifact["sql"]["params"]), language="json")
    if response.get("plan"):
        st.markdown("**Analysis plan proposed by the model**")
        st.json(response["plan"], expanded=False)
    if response.get("sources"):
        st.markdown("**Knowledge sources**")
        for s in response["sources"]:
            with st.expander(f"{s['title']} — {s['section']} (score {s['score']})"):
                st.write(s["text"])
                st.caption(s["source_url"])
    st.markdown("**Tool trace**")
    st.dataframe(trace_frame(response.get("trace") or []), hide_index=True,
                 width="stretch")  # fmt: skip
    latency = response.get("latency_ms") or {}
    if latency:
        st.caption(" · ".join(f"{k} {v:,.0f} ms" for k, v in latency.items()))
    st.caption(TRACE_CAPTION)


def main() -> None:
    st.set_page_config(page_title="Housing Market AI Analyst", page_icon="🏠", layout="wide")
    init_session()
    sidebar()
    main_area()


main()
