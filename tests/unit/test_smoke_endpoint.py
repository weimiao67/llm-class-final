"""Smoke-test reply classification, replayed on the real replies from the Llama-3.2-3B endpoint."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("smoke", ROOT / "scripts" / "smoke_endpoint.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

# Constrained reply from the live endpoint: right shape, but neither cities nor state_filter.
NO_SCOPE = (
    '{"call": {"tool": "analyze", "plan": {"metric": "zhvi", "operation": "rank", '
    '"rank_by": "change", "order": "desc", "limit": 10}}}'
)
# Unconstrained reply from the live endpoint: cities sent as a string.
CITIES_AS_STRING = (
    '{"call": {"tool": "analyze", "plan": {"metric": "zhvi", "operation": "rank", '
    '"rank_by": "change", "order": "desc", "cities": "[\\"Denver, CO\\", \\"Aurora, CO\\"]"}}}'
)
VALID = (
    '{"call": {"tool": "analyze", "plan": {"metric": "zhvi", "operation": "rank", '
    '"rank_by": "pct_change", "state_filter": "CO"}}}'
)


def test_schema_shaped_replies_pass_the_shape_check_even_if_invalid():
    assert smoke.shaped(NO_SCOPE) == "analyze"
    assert smoke.shaped(CITIES_AS_STRING) == "analyze"


@pytest.mark.parametrize(
    "reply",
    ["hello", "", "[1, 2]", '{"call": "x"}', '{"call": {}}', '{"call": {"tool": "run_sql"}}'],
)
def test_malformed_replies_always_raise_value_error(reply):
    with pytest.raises(ValueError):
        smoke.shaped(reply)


def test_describe_separates_shape_from_validity():
    assert "fails validation" in smoke.describe(NO_SCOPE)
    assert "exactly one" in smoke.describe(NO_SCOPE)
    assert "fails validation" in smoke.describe(CITIES_AS_STRING)
    assert "valid plan" in smoke.describe(VALID)
    assert smoke.describe("hello").startswith("not schema-shaped")
