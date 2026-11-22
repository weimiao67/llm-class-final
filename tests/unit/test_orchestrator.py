"""Agent-loop behavior with a scripted model, on the fixture dataset (see tests/conftest.py)."""

import time

import pytest

from agent.model_clients.stub import ScriptedModelClient
from agent.orchestrator import MAX_PLAN_RETRIES, Agent
from tools.knowledge import Passage


def analyze(**plan):
    return {"call": {"tool": "analyze", "plan": plan}}


def respond(kind, text):
    return {"call": {"tool": "respond", "kind": kind, "text": text}}


DENVER_2025 = analyze(
    metric="zhvi",
    cities=[{"city": "Denver", "state": "CO"}],
    start_month="2025-01",
    end_month="2025-12",
    operation="change",
)
GOOD_ANSWER = "Denver's ZHVI rose from $524,000 to $535,000 in 2025 (2.1%)."


def make(db, outputs, knowledge=None):
    model = ScriptedModelClient(outputs)
    return Agent(db, model, knowledge=knowledge), model


def test_happy_path_plans_executes_and_answers(db):
    agent, model = make(db, [DENVER_2025, GOOD_ANSWER])
    r = agent.run_turn("How did Denver home values change in 2025?")
    assert (r.kind, r.answer, r.answer_source) == ("answer", GOOD_ANSWER, "model")
    assert r.artifact.summary["cities"][0]["change"] == 11000
    assert [e.tool for e in r.trace] == ["analyze", "answer_writer"]
    # planning is greedy+constrained, answering is sampled and unconstrained
    assert [(c["profile"], c["schema"]) for c in model.calls] == [
        ("plan", True),
        ("answer", False),
    ]
    assert r.updated_state["cities"] == [
        {"city": "Denver", "state": "CO", "county": "Denver County"}
    ]
    assert r.updated_state["start_month"] == "2025-01"


def test_invalid_json_is_retried_with_error_feedback(db):
    agent, model = make(db, ["not json", DENVER_2025, GOOD_ANSWER])
    r = agent.run_turn("Denver 2025?")
    assert r.kind == "answer"
    assert model.calls[1]["profile"] == "plan_retry"
    assert model.calls[1]["messages"][-1]["content"].startswith("TOOL RESULT:")


def test_invalid_plan_is_retried_then_succeeds(db):
    bad = analyze(metric="zhvi", cities=[{"city": "Denver"}], operation="rank")  # no rank_by
    agent, model = make(db, [bad, DENVER_2025, GOOD_ANSWER])
    r = agent.run_turn("Denver 2025?")
    assert r.kind == "answer"
    assert "rank_by" in model.calls[1]["messages"][-1]["content"]
    assert [e.status for e in r.trace][:2] == ["retry", "ok"]


def test_retries_are_bounded(db):
    agent, model = make(db, ["{}"] * (MAX_PLAN_RETRIES + 1))
    r = agent.run_turn("??")
    assert r.kind == "error" and r.answer_source == "system"
    assert len(model.calls) == MAX_PLAN_RETRIES + 1


def test_ambiguous_city_asks_user_without_further_model_calls(db):
    plan = analyze(metric="zhvi", cities=[{"city": "Oakwood", "state": "OH"}], operation="change")
    agent, model = make(db, [plan])
    r = agent.run_turn("How did Oakwood, OH change?", state={"metric": "zori"})
    assert r.kind == "clarify" and "Cuyahoga County" in r.answer
    assert len(model.calls) == 1
    assert r.updated_state == {"metric": "zori"}  # prior context is kept


def test_city_not_found_suggests(db):
    plan = analyze(metric="zhvi", cities=[{"city": "Denvr", "state": "CO"}], operation="series")
    agent, _ = make(db, [plan])
    r = agent.run_turn("Denvr values")
    assert r.kind == "clarify" and "Denver, CO" in r.answer


def test_no_data_is_a_truthful_stop(db):
    plan = analyze(metric="zori", cities=[{"city": "Mead", "state": "CO"}], operation="series")
    agent, _ = make(db, [plan])
    r = agent.run_turn("Mead rent")
    assert r.kind == "no_data" and "ZORI" in r.answer and r.artifact is None


def test_out_of_scope_reply_passes_through(db):
    agent, _ = make(db, [respond("out_of_scope", "I can't forecast; I can show history.")])
    r = agent.run_turn("What will Denver rent be next year?")
    assert (r.kind, r.answer_source) == ("out_of_scope", "model")


def test_direct_reply_with_invented_numbers_is_replaced(db):
    agent, _ = make(db, [respond("unsupported", "Denver rent is $2,345, but I can't say more.")])
    r = agent.run_turn("Denver rent?")
    assert r.answer_source == "system" and "$2,345" not in r.answer


def test_direct_answer_from_memory_is_rejected_and_retried(db):
    memory = respond("answer", "Denver home values rose sharply this year and outpaced Boulder.")
    agent, model = make(db, [memory, DENVER_2025, GOOD_ANSWER])
    r = agent.run_turn("How did Denver compare to Boulder?")
    assert (r.kind, r.answer_source) == ("answer", "model") and r.artifact is not None
    assert model.calls[1]["profile"] == "plan_retry"
    assert "kind" in model.calls[1]["messages"][-1]["content"]  # schema error names the field


def test_repeated_answers_from_memory_never_reach_the_user(db):
    memory = respond("answer", "Denver home values rose sharply this year.")
    agent, _ = make(db, [memory] * (MAX_PLAN_RETRIES + 1))
    r = agent.run_turn("How did Denver do?")
    assert r.kind == "error" and "rose sharply" not in r.answer


def test_ungrounded_answer_is_regenerated_greedily(db):
    agent, model = make(db, [DENVER_2025, "It rose to $999,999.", GOOD_ANSWER])
    r = agent.run_turn("Denver 2025?")
    assert (r.answer, r.answer_source) == (GOOD_ANSWER, "model_regenerated")
    assert model.calls[2]["profile"] == "answer_greedy"


def test_persistently_ungrounded_answer_falls_back_to_template(db):
    agent, _ = make(db, [DENVER_2025, "It is $777,777.", "Still $888,888."])
    r = agent.run_turn("Denver 2025?")
    assert r.answer_source == "template"
    assert "$524,000" in r.answer and "$535,000" in r.answer


def test_model_failure_returns_safe_error(db):
    class Boom:
        model_id = "boom"

        def complete(self, *a, **k):
            raise TimeoutError("endpoint timed out")

    r = Agent(db, Boom()).run_turn("Denver?")
    assert r.kind == "error" and "timed out" not in r.answer


def test_knowledge_unavailable_stops(db):
    call = {"call": {"tool": "search_knowledge", "query": "what is zori", "top_k": 2}}
    agent, _ = make(db, [call])
    r = agent.run_turn("What is ZORI?")
    assert r.kind == "error" and "knowledge base" in r.answer


def test_knowledge_answer_cites_sources(db):
    class KB:
        def search(self, query, top_k):
            return [
                Passage(
                    doc_id="zori",
                    title="ZORI methodology",
                    section="Overview",
                    source_url="https://example.org/zori",
                    text="ZORI measures typical observed market rate rent.",
                    score=1.0,
                )
            ]

    call = {"call": {"tool": "search_knowledge", "query": "what is zori", "top_k": 2}}
    agent, _ = make(db, [call, "ZORI measures typical observed market rent."], knowledge=KB())
    r = agent.run_turn("What is ZORI?")
    assert r.kind == "answer" and r.sources[0].doc_id == "zori"


def test_history_and_state_reach_the_planner_prompt(db):
    agent, model = make(db, [DENVER_2025, GOOD_ANSWER])
    history = [{"role": "user", "content": f"q{i}"} for i in range(10)]
    agent.run_turn("what about 2025?", history=history, state={"metric": "zori"})
    messages = model.calls[0]["messages"]
    assert '"metric": "zori"' in messages[0]["content"]
    assert [m["content"] for m in messages[1:-1]] == [f"q{i}" for i in range(4, 10)]


@pytest.mark.parametrize("outputs", [[DENVER_2025, "", ""]])
def test_empty_answers_fall_back_to_template(db, outputs):
    agent, _ = make(db, outputs)
    assert agent.run_turn("Denver?").answer_source == "template"


def test_trace_records_why_the_template_was_used(db):
    agent, _ = make(db, [DENVER_2025, "", "It is $777,777."])
    r = agent.run_turn("Denver?")
    writer = [(e.status, e.detail) for e in r.trace if e.tool == "answer_writer"]
    assert writer == [
        ("retry", "answer: empty answer"),
        ("retry", "answer_greedy: ungrounded numbers: 777777"),
        ("ok", "template fallback"),
    ]


def test_turn_timeout_stops_before_the_next_model_call(db):
    class Slow(ScriptedModelClient):
        def complete(self, messages, profile, json_schema=None):
            out = super().complete(messages, profile, json_schema)
            time.sleep(0.05)
            return out

    model = Slow([DENVER_2025, GOOD_ANSWER])
    r = Agent(db, model, turn_timeout_s=0.01).run_turn("Denver 2025?")
    assert r.kind == "error" and "too long" in r.answer
    assert len(model.calls) == 1  # the answer-writer call was never made
    assert r.trace[-1].detail == "turn timeout"


def test_retry_feedback_tells_the_model_to_fix_not_reply(db):
    bad = analyze(metric="zhvi", cities=[{"city": "Denver"}], operation="rank")  # no rank_by
    agent, model = make(db, [bad, DENVER_2025, GOOD_ANSWER])
    agent.run_turn("Denver 2025?")
    feedback = model.calls[1]["messages"][-1]["content"]
    assert feedback.startswith("TOOL RESULT:") and "rank_by" in feedback
    assert "Do not respond to the user about this error" in feedback


def test_planner_prompt_v2_states_scope_and_tool_rules(db):
    from agent.prompts import PROMPT_VERSION, planner_messages

    system = planner_messages(db, "q", [], None)[0]["content"]
    assert PROMPT_VERSION == "planner-v2"
    assert "EXACTLY ONE" in system and "state_filter" in system
    assert "Never use it to get values" in system
    agent, _ = make(db, [DENVER_2025, GOOD_ANSWER])
    assert agent.run_turn("Denver 2025?").prompt_version == "planner-v2"
