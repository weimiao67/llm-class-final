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


# ---- decoding schema (sent to TGI for grammar-constrained decoding) --------------------------


def _walk_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_keys(v)


def test_decoding_schema_has_no_grammar_blowup_keywords():
    from tools.schemas import decoding_schema

    keys = set(_walk_keys(decoding_schema()))
    assert not keys & {
        "$ref",
        "$defs",
        "maxLength",
        "minLength",
        "pattern",
        "maxItems",
        "discriminator",
        "default",
    }


def _analyze_plan_variants():
    from tools.schemas import decoding_schema

    options = decoding_schema()["properties"]["call"]["oneOf"]
    analyze = next(o for o in options if o["properties"]["tool"]["const"] == "analyze")
    return options, analyze["properties"]["plan"]["oneOf"]


def test_decoding_schema_keeps_structure_enums_and_required_fields():
    import json

    from tools.schemas import decoding_schema

    options, variants = _analyze_plan_variants()
    assert {o["properties"]["tool"]["const"] for o in options} == {
        "analyze",
        "search_knowledge",
        "respond",
    }
    for plan_variant in variants:
        assert {"metric", "operation"} <= set(plan_variant["required"])
        assert plan_variant["properties"]["operation"]["enum"] == [
            "series",
            "change",
            "yoy_change",
            "extrema",
            "rank",
            "aggregate",
            "coverage",
        ]
        assert plan_variant["additionalProperties"] is False
    respond = next(o for o in options if o["properties"]["tool"]["const"] == "respond")
    assert respond["properties"]["kind"]["enum"] == ["clarify", "unsupported", "out_of_scope"]
    assert len(json.dumps(decoding_schema())) < len(json.dumps(tool_call_json_schema()))


def test_decoding_schema_enforces_exactly_one_scope():
    # The baseline's most common failure: plans with both or neither of cities/state_filter.
    _, (city_scoped, state_scoped) = _analyze_plan_variants()
    assert "cities" in city_scoped["required"] and "state_filter" not in city_scoped["properties"]
    assert city_scoped["properties"]["cities"]["minItems"] == 1
    assert "state_filter" in state_scoped["required"] and "cities" not in state_scoped["properties"]
    assert state_scoped["properties"]["state_filter"]["type"] == "string"


def test_bounds_dropped_from_decoding_are_still_enforced_by_validation():
    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(plan(start_month="2025-1"))  # pattern
    with pytest.raises(ValidationError):
        ToolCall.model_validate(
            {"call": {"tool": "respond", "kind": "clarify", "text": "x" * 2001}}  # maxLength
        )


def test_decoding_schema_restricts_states_to_codes():
    from tools.schemas import US_STATE_CODES

    _, (city_scoped, state_scoped) = _analyze_plan_variants()
    assert state_scoped["properties"]["state_filter"]["enum"] == list(US_STATE_CODES)
    city_state = city_scoped["properties"]["cities"]["items"]["properties"]["state"]
    assert {"type": "string", "enum": list(US_STATE_CODES)} in city_state["anyOf"]
    assert {"type": "null"} in city_state["anyOf"]  # the state stays optional
    assert len(US_STATE_CODES) == 51 and all(
        AnalysisPlan.model_validate(plan(cities=[{"city": "X", "state": c}]))
        for c in US_STATE_CODES
    )


def test_canonical_json_drops_defaults_and_keeps_schema_order():
    from tools.schemas import canonical_json

    text = canonical_json(
        {
            "call": {
                "tool": "analyze",
                "plan": {
                    "operation": "change",
                    "metric": "zhvi",
                    "order": "desc",
                    "limit": 10,
                    "cities": [{"county": None, "state": "CO", "city": "Pueblo"}],
                },
            }
        }
    )
    assert text == (
        '{"call": {"tool": "analyze", "plan": {"metric": "zhvi", '
        '"cities": [{"city": "Pueblo", "state": "CO"}], "operation": "change"}}}'
    )
    with pytest.raises(ValidationError):
        canonical_json({"call": {"tool": "analyze", "plan": {"metric": "zhvi"}}})
