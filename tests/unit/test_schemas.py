import pytest
from pydantic import ValidationError

from tools.schemas import AnalysisPlan, ToolCall, tool_call_json_schema


def plan(**overrides):
    base = {"metric": "zhvi", "cities": [{"city": "Denver", "state": "CO"}], "operation": "change"}
    return {**base, **overrides}


def test_minimal_plan_is_valid():
    p = AnalysisPlan.model_validate(plan())
    assert p.order == "desc" and p.limit == 10


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"state_filter": "CO"}, "exactly one"),
        ({"cities": []}, "exactly one"),
        ({"operation": "aggregate"}, "'aggregate' is required"),
        ({"aggregate": "avg"}, "'aggregate' is required"),
        ({"operation": "rank"}, "'rank_by' is required"),
        ({"cities": [], "state_filter": "CO", "operation": "series"}, "needs explicit 'cities'"),
        ({"start_month": "2025-06", "end_month": "2025-01"}, "must not be after"),
        ({"start_month": "2025-13"}, "pattern"),
        ({"metric": "rent"}, "Input should be"),
        ({"limit": 51}, "less than or equal"),
        ({"sql": "DROP TABLE observations"}, "Extra inputs"),
        ({"cities": [{"city": "Denver", "state": "Colorado"}]}, "pattern"),
    ],
)
def test_structural_rules(overrides, message):
    with pytest.raises(ValidationError, match=message):
        AnalysisPlan.model_validate(plan(**overrides))


def test_too_many_cities_rejected():
    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(plan(cities=[{"city": f"C{i}"} for i in range(21)]))


def test_tool_call_envelope_discriminates_by_tool():
    call = ToolCall.model_validate({"call": {"tool": "analyze", "plan": plan()}}).call
    assert call.plan.operation == "change"
    call = ToolCall.model_validate(
        {"call": {"tool": "respond", "kind": "clarify", "text": "Which Oakwood?"}}
    ).call
    assert call.kind == "clarify"
    with pytest.raises(ValidationError):
        ToolCall.model_validate({"call": {"tool": "run_sql", "sql": "SELECT 1"}})


def test_json_schema_is_exportable():
    schema = tool_call_json_schema()
    assert "AnalysisPlan" in schema["$defs"]
