"""Streamlit UI (Step 4b): the API client, the view helpers, and the app end to end."""

from __future__ import annotations

import json

import httpx
import pytest

from ui import view
from ui.client import MAX_HISTORY_MESSAGES, AnalystClient, APIError

# ---- client ------------------------------------------------------------------------------------


def client_for(handler, api_key=None) -> AnalystClient:
    return AnalystClient("http://api", api_key=api_key, transport=httpx.MockTransport(handler))


def test_ask_sends_key_trimmed_history_and_state():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"kind": "answer"})

    history = [{"role": "user", "content": f"q{i}" + "x" * 5000} for i in range(30)]
    client_for(handler, api_key="k").ask("hi", history=history, state={"metric": "zori"})
    body = seen["body"]
    assert seen["key"] == "k"
    assert len(body["history"]) == MAX_HISTORY_MESSAGES
    assert body["history"][0]["content"].startswith("q10")  # the most recent messages are kept
    assert all(len(m["content"]) <= 4000 for m in body["history"])
    assert body["state"] == {"metric": "zori"} and body["question"] == "hi"


@pytest.mark.parametrize(
    ("status", "payload", "message"),
    [
        (401, {"detail": "missing"}, "API key"),
        (422, {"detail": [{"msg": "String should have at most 1000 characters"}]}, "1000"),
        (500, {"detail": "boom"}, "HTTP 500"),
    ],
)
def test_http_errors_become_user_messages(status, payload, message):
    client = client_for(lambda r: httpx.Response(status, json=payload))
    with pytest.raises(APIError, match=message):
        client.ask("q")


def test_unreachable_api_and_timeouts_are_explained():
    def refuse(request):
        raise httpx.ConnectError("refused")

    def slow(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(APIError, match="Can't reach the agent API at http://api"):
        client_for(refuse).ask("q")
    with pytest.raises(APIError, match="too long"):
        client_for(slow).ask("q")


def test_ready_accepts_503_as_an_answer():
    body = {"status": "not_ready", "model": {"status": "Creating"}, "model_id": "m"}
    assert client_for(lambda r: httpx.Response(503, json=body)).ready() == body


# ---- view --------------------------------------------------------------------------------------


def series_artifact():
    def row(city, month, value):
        return {"region_id": city, "city": city, "state": "CO", "month": month, "value": value}

    return {
        "operation": "series",
        "metric": "zhvi",
        "chart": {"type": "line", "x": "month", "y": "value", "series": "region_id"},
        # Denver is missing April; Mead has two months.
        "rows": [
            row("Denver", "2025-03-01", 1.0),
            row("Denver", "2025-05-01", 3.0),
            row("Mead", "2025-03-01", 5.0),
            row("Mead", "2025-04-01", 6.0),
        ],  # fmt: skip
        "summary": {"cities": []},
    }


def test_line_chart_breaks_at_missing_months_instead_of_bridging():
    fig = view.figure(series_artifact())
    denver, mead = fig.data
    assert denver.name == "Denver, CO" and denver.connectgaps is False
    assert list(denver.y) == [1.0, None, 3.0]  # April is an explicit gap
    assert list(mead.y) == [5.0, 6.0]


def test_rank_chart_plots_the_top_rows_on_the_ranked_measure():
    top = [{"label": "A, CO", "pct_change": 8.9}, {"label": "B, CO", "pct_change": 7.1}]
    artifact = {
        "operation": "rank",
        "metric": "zori",
        "chart": {"type": "bar", "x": "label", "y": "pct_change"},
        "rows": top + [{"label": "C, CO", "pct_change": 1.0}],
        "summary": {"top": top},
    }
    (bar,) = view.figure(artifact).data
    assert list(bar.x) == ["A, CO", "B, CO"] and list(bar.y) == [8.9, 7.1]


def test_no_chart_without_a_hint_or_rows():
    assert view.figure(None) is None
    assert view.figure({**series_artifact(), "chart": None}) is None
    assert view.figure({**series_artifact(), "rows": []}) is None


def test_change_cards_reformat_the_summary_only():
    city = {"city": "Denver", "state": "CO", "start_month": "2020-01-01", "end_month":
            "2025-12-01", "end_value": 1819.56, "change": 235.98, "pct_change": 14.9}  # fmt: skip
    (card,) = view.metric_cards({"operation": "change", "summary": {"cities": [city]}})
    assert card == view.Card("Denver, CO", "$1,820", "+14.9%", "Jan 2020 → Dec 2025 · +$236")


def test_cards_give_way_to_a_table_beyond_four_cities():
    cities = [{"city": f"C{i}", "state": "CO", "end_value": 1.0} for i in range(5)]
    assert view.metric_cards({"operation": "change", "summary": {"cities": cities}}) == []
    assert len(view.metric_cards({"operation": "change", "summary": {"cities": cities[:4]}})) == 4


def test_aggregate_card_shows_delta_only_over_more_than_one_month():
    one = {"aggregate": "median", "scope": "CO", "months": 1, "pct_change": 0.0,
           "first": {"month": "2025-12-01", "value": 466375.97, "regions": 340},
           "last": {"month": "2025-12-01", "value": 466375.97, "regions": 340}}  # fmt: skip
    (card,) = view.metric_cards({"operation": "aggregate", "summary": one})
    assert card == view.Card("Median across CO", "$466,376", None, "Dec 2025 · 340 cities")
    many = {
        **one,
        "months": 12,
        "pct_change": 2.5,
        "first": {**one["first"], "month": "2025-01-01"},
    }
    (card,) = view.metric_cards({"operation": "aggregate", "summary": many})
    assert card.delta == "+2.5%" and card.caption.startswith("Jan 2025 → Dec 2025")


def test_rows_table_is_formatted_but_csv_keeps_raw_values():
    artifact = {"rows": [{"city": "Denver", "month": "2025-03-01", "value": 559063.67,
                          "pct_change": None}]}  # fmt: skip
    df = view.rows_frame(artifact)
    assert df.iloc[0].to_dict() == {"city": "Denver", "month": "Mar 2025", "value": "$559,064",
                                    "pct_change": "—"}  # fmt: skip
    assert view.rows_csv(artifact).decode().splitlines()[1] == "Denver,2025-03-01,559063.67,"
    assert view.rows_frame(None).empty


def test_status_line_levels():
    ready = {"status": "ready", "model_id": "qwen-lora", "dataset_version": "23ccd46a4560"}
    assert view.status_line(ready) == ("ok", "Ready · qwen-lora · data 23ccd46a4560")
    down = {**ready, "status": "not_ready", "model": {"status": "Creating"}}
    assert view.status_line(down)[0] == "warn" and "Creating" in view.status_line(down)[1]
    assert view.status_line(None, "Can't reach") == ("error", "Can't reach")


def test_failed_turns_are_left_out_of_the_history():
    turns = [
        {"question": "q1", "response": {"answer": "a1"}},
        {"question": "q2", "response": None, "error": "down"},
    ]
    assert view.history_for_api(turns) == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]


# ---- app end to end ----------------------------------------------------------------------------


@pytest.fixture
def app_against_stub_api(db, monkeypatch):
    """The Streamlit app, with its HTTP client pointed at the real API app (stub model)."""
    import streamlit as st
    from fastapi.testclient import TestClient
    from streamlit.testing.v1 import AppTest

    from agent.model_clients.stub import StubModelClient, demo_rules
    from agent.orchestrator import Agent
    from api.main import create_app
    from tools.knowledge import BM25KnowledgeBase

    kb = BM25KnowledgeBase.from_dir("rag/corpus")
    agent = Agent(db, StubModelClient(rules=demo_rules()), knowledge=kb)
    with TestClient(create_app(agent=agent)) as api:
        original = AnalystClient.__init__

        def init(self, base_url, api_key=None, transport=None):
            original(self, "http://testserver", api_key, transport=api._transport)

        monkeypatch.setattr(AnalystClient, "__init__", init)
        # Streamlit caches live for the whole process: without clearing them, this test would
        # reuse the client (and status) cached by an earlier test, bound to that test's API app.
        st.cache_resource.clear()
        st.cache_data.clear()
        at = AppTest.from_file("../../ui/app.py", default_timeout=30)
        at.run()
        yield at
    st.cache_resource.clear()
    st.cache_data.clear()


def test_app_answers_a_question_and_carries_state_into_the_follow_up(app_against_stub_api):
    at = app_against_stub_api
    assert not at.exception
    assert at.sidebar.success[0].value.startswith("Ready · stub")
    at.sidebar.chat_input[0].set_value("Rank Colorado cities by ZHVI growth in 2025").run()
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert labels[0] == "AI response" and labels[2] == "Evidence & trace"
    assert labels[1].startswith("Queried data · ") and labels[1].endswith(" rows")
    assert at.session_state.state["state_filter"] == "CO"

    at.sidebar.chat_input[0].set_value("What about rent growth for the same cities and year?").run()
    assert not at.exception
    assert len(at.session_state.turns) == 2
    assert at.session_state.state["metric"] == "zori"


def test_app_shows_clarification_and_api_errors(app_against_stub_api, monkeypatch):
    at = app_against_stub_api
    at.sidebar.chat_input[0].set_value("How did home values change in Oakwood, OH since 2020?")
    at.run()
    assert "Needs clarification" in [c.value for c in at.caption]

    def down(self, *args, **kwargs):
        raise APIError("Can't reach the agent API at http://testserver.")

    monkeypatch.setattr(AnalystClient, "ask", down)
    at.sidebar.chat_input[0].set_value("What is ZORI?").run()
    assert not at.exception
    assert at.error[0].value.startswith("Can't reach")
    assert at.session_state.turns[-1]["response"] is None


def test_warnings_are_shown_once_and_rankings_keep_only_ranking_columns():
    top = [{"rank": 1, "label": "A, CO", "region_id": "1", "county": "X", "size_rank": 5,
            "start_value": 1.0, "end_value": 2.0, "change": 1.0, "pct_change": 100.0}]  # fmt: skip
    artifact = {"warnings": ["w1", "w2"], "summary": {"top": top}, "rows": top}
    response = {"warnings": ["w1", "w2", "w3"], "artifact": artifact}
    assert view.all_warnings(response) == ["w1", "w2", "w3"]
    assert list(view.ranking_frame(artifact).columns) == [
        "rank", "label", "start_value", "end_value", "change", "pct_change"
    ]  # fmt: skip


# ---- PR #8 review follow-ups ---------------------------------------------------------------------


def oakwoods():
    def row(rid, county, value):
        return {"region_id": rid, "city": "Oakwood", "state": "OH", "county": county,
                "month": "2025-01-01", "value": value}  # fmt: skip

    return [row("a", "Montgomery County", 300000.0), row("b", "Cuyahoga County", 150000.0)]


def test_same_named_cities_get_separate_lines_labeled_by_county():
    chart = {"type": "line", "x": "month", "y": "value", "series": "region_id"}
    artifact = {"operation": "series", "metric": "zhvi", "rows": oakwoods(), "summary": {},
                "chart": chart}  # fmt: skip
    traces = {t.name: list(t.y) for t in view.figure(artifact).data}
    assert traces == {
        "Oakwood, OH (Montgomery County)": [300000.0],
        "Oakwood, OH (Cuyahoga County)": [150000.0],
    }


def test_same_named_cities_get_distinct_bars_and_cards():
    top = [{**r, "label": "Oakwood, OH", "pct_change": 1.0} for r in oakwoods()]
    artifact = {"operation": "rank", "metric": "zhvi", "rows": top, "summary": {"top": top},
                "chart": {"type": "bar", "x": "label", "y": "pct_change"}}  # fmt: skip
    (bar,) = view.figure(artifact).data
    assert len(set(bar.x)) == 2
    cards = view.metric_cards({"operation": "change", "summary": {"cities": oakwoods()}})
    assert [c.label for c in cards] == [
        "Oakwood, OH (Montgomery County)",
        "Oakwood, OH (Cuyahoga County)",
    ]
    assert view.region_labels([{"region_id": "1", "city": "Denver", "state": "CO"}]) == {
        "1": "Denver, CO"
    }


def test_non_json_responses_become_api_errors():
    client = client_for(lambda r: httpx.Response(503, text="Service Unavailable"))
    with pytest.raises(APIError, match="unexpected response"):
        client.ready()


def test_negative_changes_are_signed_in_tables():
    df = view.rows_frame({"rows": [{"change": -16537.1}, {"change": 250.0}]})
    assert list(df["change"]) == ["−$16,537", "+$250"]


def test_status_line_explains_endpoint_errors():
    base = {"status": "not_ready", "model_id": "m", "dataset_version": "v"}

    def line(error):
        return view.status_line({**base, "model": {"status": "unreachable", "error": error}})[1]

    assert line("ValidationException").startswith("Model endpoint not deployed")
    assert line("AccessDeniedException").startswith(
        "Model endpoint not allowed for this app's role"
    )
    assert line("EndpointConnectionError").startswith(
        "Model endpoint unreachable (EndpointConnectionError)"
    )
