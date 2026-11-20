from datetime import date

from tools.schemas import ToolError
from tools.validator import ValidatedPlan


def plan(**overrides):
    base = {"metric": "zhvi", "cities": [{"city": "Denver", "state": "CO"}], "operation": "change"}
    return {**base, **overrides}


def test_resolves_city_and_defaults_period_to_coverage(validator):
    v = validator.validate(plan())
    assert isinstance(v, ValidatedPlan)
    assert [r.region_id for r in v.regions] == ["1"]
    assert (v.start, v.end) == (date(2023, 1, 1), date(2025, 12, 1))


def test_city_lookup_is_case_insensitive_and_without_state(validator):
    v = validator.validate(plan(cities=[{"city": "  mead "}]))
    assert isinstance(v, ValidatedPlan) and v.regions[0].city == "Mead"


def test_schema_errors_are_retryable_with_field_details(validator):
    err = validator.validate(plan(operation="forecast"))
    assert isinstance(err, ToolError) and err.kind == "invalid_plan" and err.retryable
    assert err.details["errors"][0]["field"] == "operation"


def test_ambiguous_within_state_lists_counties(validator):
    err = validator.validate(plan(cities=[{"city": "Oakwood", "state": "OH"}]))
    assert err.kind == "ambiguous_city" and not err.retryable
    counties = {c["county"] for c in err.details["cities"][0]["candidates"]}
    assert counties == {"Montgomery County", "Cuyahoga County"}


def test_ambiguous_across_states(validator):
    err = validator.validate(plan(cities=[{"city": "Springfield"}]))
    assert err.kind == "ambiguous_city"
    assert {c["state"] for c in err.details["cities"][0]["candidates"]} == {"IL", "MO"}


def test_county_disambiguates(validator):
    v = validator.validate(plan(cities=[{"city": "Oakwood", "state": "OH", "county": "cuyahoga"}]))
    assert isinstance(v, ValidatedPlan) and v.regions[0].region_id == "6"


def test_not_found_offers_suggestions(validator):
    err = validator.validate(plan(cities=[{"city": "Denvr", "state": "CO"}]))
    assert err.kind == "city_not_found"
    assert "Denver, CO" in err.details["cities"][0]["suggestions"]


def test_metric_not_published_for_city(validator):
    err = validator.validate(plan(metric="zori", cities=[{"city": "Mead", "state": "CO"}]))
    assert err.kind == "no_data" and "ZORI" in err.message


def test_partial_metric_availability_warns_and_keeps_rest(validator):
    v = validator.validate(
        plan(
            metric="zori",
            cities=[{"city": "Denver", "state": "CO"}, {"city": "Mead", "state": "CO"}],
        )
    )
    assert [r.city for r in v.regions] == ["Denver"]
    assert any("Mead" in w for w in v.warnings)


def test_duplicate_cities_collapse(validator):
    v = validator.validate(plan(cities=[{"city": "Denver"}, {"city": "denver", "state": "CO"}]))
    assert len(v.regions) == 1


def test_period_outside_coverage(validator):
    err = validator.validate(plan(start_month="2030-01"))
    assert err.kind == "no_data" and err.details["coverage"]["last_month"] == "2025-12-01"


def test_period_partially_outside_is_clamped_with_warning(validator):
    v = validator.validate(plan(start_month="2020-01", end_month="2024-06"))
    assert v.start == date(2023, 1, 1) and v.end == date(2024, 6, 1)
    assert any("starts in Jan 2023" in w for w in v.warnings)


def test_unknown_state_filter(validator):
    err = validator.validate(
        {"metric": "zori", "state_filter": "OH", "operation": "rank", "rank_by": "value"}
    )
    assert err.kind == "no_data"


# ---- regressions from code review ------------------------------------------------------------


def test_metric_absent_from_dataset_is_no_data(tmp_path):
    from housing.db import HousingDB
    from housing.ingest import SourceFile, ingest
    from tests.conftest import ZHVI, write_wide
    from tools.validator import PlanValidator

    src = tmp_path / "zhvi.csv"
    write_wide(src, ZHVI[:2])
    ingest([SourceFile("zhvi", src, "v")], tmp_path / "data")
    err = PlanValidator(HousingDB(tmp_path / "data")).validate(plan(metric="zori"))
    assert isinstance(err, ToolError) and err.kind == "no_data"


def test_year_zero_is_a_schema_error_not_a_crash(validator):
    err = validator.validate(plan(start_month="0000-01"))
    assert isinstance(err, ToolError) and err.kind == "invalid_plan"
