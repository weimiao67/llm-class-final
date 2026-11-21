from agent.decoding import ANSWER, PLAN, tgi_parameters
from agent.model_clients.stub import StubModelClient, demo_rules
from tools.schemas import ToolCall, tool_call_json_schema


def test_stub_plans_are_valid_tool_calls():
    stub = StubModelClient(rules=demo_rules())
    for question in [
        "What was Mead, CO's highest ZHVI month in 2025?",
        "Rank Colorado cities by ZHVI growth in 2025",
        "How did home values change in Oakwood, OH since 2020?",
        "What will Denver rent be next year?",
        "What is ZORI and how is it smoothed?",
        "Something unrelated",
    ]:
        out = stub.complete([{"role": "user", "content": question}], PLAN)
        ToolCall.model_validate_json(out.text)


def test_stub_demo_plans_validate_against_data(validator):
    stub = StubModelClient(rules=demo_rules())
    out = stub.complete([{"role": "user", "content": "Rank Colorado cities"}], PLAN)
    call = ToolCall.model_validate_json(out.text).call
    assert call.tool == "analyze"
    assert validator.validate(call.plan).state == "CO"


def test_plan_profile_is_greedy_and_constrained():
    params = tgi_parameters(PLAN, tool_call_json_schema())
    assert params["temperature"] == 0.0
    assert params["response_format"]["type"] == "json_object"


def test_answer_profile_samples_without_constraint():
    params = tgi_parameters(ANSWER, tool_call_json_schema())
    assert (params["temperature"], params["top_p"]) == (0.3, 0.9)
    assert "response_format" not in params


def test_stub_forecast_rule_wins_over_city_rules():
    stub = StubModelClient(rules=demo_rules())
    out = stub.complete([{"role": "user", "content": "Will Oakwood's value rise next year?"}], PLAN)
    call = ToolCall.model_validate_json(out.text).call
    assert call.tool == "respond" and call.kind == "out_of_scope"


def test_stub_call_log_is_bounded():
    from agent.model_clients.stub import STUB_CALL_LOG

    stub = StubModelClient(rules=demo_rules())
    for _ in range(STUB_CALL_LOG + 10):
        stub.complete([{"role": "user", "content": "x"}], PLAN)
    assert len(stub.calls) == STUB_CALL_LOG


def test_respond_schema_has_no_direct_answer_kind():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ToolCall.model_validate({"call": {"tool": "respond", "kind": "answer", "text": "hi"}})
