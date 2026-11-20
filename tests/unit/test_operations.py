"""Expected numbers follow from the fixture's linear series (see tests/conftest.py)."""

from datetime import date

import pytest

from tools.compiler import compile_plan
from tools.operations import execute
from tools.schemas import QueryArtifact, ToolError


def run(validator, db, **plan) -> QueryArtifact:
    vplan = validator.validate(plan)
    assert not isinstance(vplan, ToolError), vplan
    out = execute(vplan, db)
    assert isinstance(out, QueryArtifact), out
    return out


CO_2025 = {"metric": "zhvi", "state_filter": "CO", "start_month": "2025-01", "end_month": "2025-12"}


def test_change(validator, db):
    art = run(
        validator,
        db,
        metric="zhvi",
        cities=[{"city": "Denver", "state": "CO"}],
        start_month="2025-01",
        end_month="2025-12",
        operation="change",
    )
    city = art.summary["cities"][0]
    assert (city["start_value"], city["end_value"], city["change"]) == (524000, 535000, 11000)
    assert city["pct_change"] == pytest.approx(11000 / 524000 * 100, abs=0.01)
    assert art.warnings == []


def test_change_warns_when_city_data_starts_late(validator, db):
    art = run(validator, db, metric="zhvi", cities=[{"city": "Fort Collins"}], operation="change")
    assert art.summary["cities"][0]["start_month"] == date(2024, 1, 1)
    assert any("starts in Jan 2024" in w for w in art.warnings)


def test_extrema_skips_missing_month(validator, db):
    art = run(
        validator,
        db,
        metric="zhvi",
        cities=[{"city": "Mead", "state": "CO"}],
        start_month="2025-01",
        end_month="2025-12",
        operation="extrema",
    )
    c = art.summary["cities"][0]
    assert (c["max_month"], c["max_value"]) == (date(2025, 12, 1), 470000)
    assert (c["min_month"], c["min_value"]) == (date(2025, 1, 1), 448000)
    assert c["observations"] == 11


def test_extrema_tie_uses_earliest_month(db):
    rows = db.query(
        """WITH s AS (SELECT * FROM (VALUES ('1', 'X', 'CO', NULL, DATE '2025-01-01', 5.0),
                                            ('1', 'X', 'CO', NULL, DATE '2025-02-01', 5.0))
                      t(region_id, city, state, county, month, value))
           SELECT min(month) FILTER (WHERE value = (SELECT max(value) FROM s)) AS m FROM s""",
        [],
    )
    assert rows[0]["m"] == date(2025, 1, 1)


def test_yoy_uses_latest_month_in_range(validator, db):
    art = run(
        validator,
        db,
        metric="zhvi",
        cities=[{"city": "Mead", "state": "CO"}],
        end_month="2025-07",
        operation="yoy_change",
    )
    c = art.summary["cities"][0]
    # 2025-07 is missing for Mead, so the latest observation is 2025-06 (i=29)
    assert c["end_month"] == date(2025, 6, 1) and c["prior_month"] == date(2024, 6, 1)
    assert c["change"] == 24000


def test_yoy_without_prior_year_warns(validator, db):
    art = run(
        validator,
        db,
        metric="zhvi",
        cities=[{"city": "Fort Collins"}],
        end_month="2024-06",
        operation="yoy_change",
    )
    assert art.summary["cities"][0]["change"] is None
    assert any("no observation 12 months before" in w for w in art.warnings)


def test_rank_by_pct_change_in_state(validator, db):
    art = run(validator, db, **CO_2025, operation="rank", rank_by="pct_change")
    assert [c["city"] for c in art.summary["top"]] == ["Mead", "Denver", "Boulder", "Fort Collins"]
    assert art.summary["eligible"] == 4 and art.summary["excluded"] == 0
    assert art.chart["y"] == "pct_change"


def test_rank_ascending_with_limit(validator, db):
    art = run(validator, db, **CO_2025, operation="rank", rank_by="value", order="asc", limit=2)
    assert [c["city"] for c in art.summary["top"]] == ["Mead", "Denver"]
    assert len(art.rows) == 4  # all ranked rows stay available
    assert any("Showing top 2 of 4" in w for w in art.warnings)


def test_rank_excludes_cities_without_full_window(validator, db):
    art = run(validator, db, metric="zhvi", state_filter="CO", operation="rank", rank_by="change")
    assert art.summary["excluded"] == 1
    assert any("Fort Collins" in w for w in art.warnings)


def test_aggregate_avg_and_reporting_count_warning(validator, db):
    art = run(
        validator, db, metric="zhvi", state_filter="CO", operation="aggregate", aggregate="avg"
    )
    assert art.summary["first"]["value"] == pytest.approx((500000 + 800000 + 400000) / 3, abs=0.01)
    assert (art.summary["first"]["regions"], art.summary["last"]["regions"]) == (3, 4)
    assert any("number of reporting cities" in w for w in art.warnings)


def test_aggregate_median_and_count(validator, db):
    med = run(validator, db, **CO_2025, operation="aggregate", aggregate="median")
    assert med.summary["months"] == 12
    cnt = run(validator, db, **CO_2025, operation="aggregate", aggregate="count")
    assert cnt.summary["first"]["value"] == 4


def test_coverage_counts_missing_months(validator, db):
    art = run(validator, db, metric="zori", cities=[{"city": "Boulder"}], operation="coverage")
    c = art.summary["cities"][0]
    assert (c["observations"], c["missing_months"]) == (34, 2)


def test_series_returns_rows_and_gap_warning(validator, db):
    art = run(
        validator,
        db,
        metric="zhvi",
        cities=[{"city": "Mead"}, {"city": "Denver"}],
        start_month="2025-01",
        end_month="2025-12",
        operation="series",
    )
    assert len(art.rows) == 11 + 12
    assert any("Mead, CO has 1 missing month" in w for w in art.warnings)
    assert art.chart["type"] == "line"


def test_city_with_no_rows_in_period_is_warned(validator, db):
    art = run(
        validator,
        db,
        metric="zhvi",
        cities=[{"city": "Fort Collins"}, {"city": "Denver"}],
        start_month="2023-01",
        end_month="2023-06",
        operation="change",
    )
    assert [c["city"] for c in art.summary["cities"]] == ["Denver"]
    assert any("No data for Fort Collins" in w for w in art.warnings)


def test_no_rows_at_all_is_no_data(validator, db):
    vplan = validator.validate(
        {
            "metric": "zhvi",
            "cities": [{"city": "Fort Collins"}],
            "end_month": "2023-06",
            "operation": "change",
        }
    )
    err = execute(vplan, db)
    assert isinstance(err, ToolError) and err.kind == "no_data"


def test_compiled_sql_binds_every_plan_value(validator):
    vplan = validator.validate(
        {
            "metric": "zhvi",
            "cities": [{"city": "Denver"}],
            "start_month": "2025-01",
            "operation": "change",
        }
    )
    compiled = compile_plan(vplan)
    assert "Denver" not in compiled.sql and "zhvi" not in compiled.sql
    assert compiled.sql.count("?") == len(compiled.params)
    assert compiled.describe()["params"] == ["zhvi", "1", "2025-01-01", "2025-12-01"]


def test_artifact_serializes_to_json(validator, db):
    art = run(validator, db, **CO_2025, operation="rank", rank_by="value")
    dumped = art.model_dump(mode="json")
    assert dumped["period"]["start_month"] == "2025-01-01"
    assert dumped["dataset_version"] == db.dataset_version


# ---- regressions from code review ------------------------------------------------------------


def test_yoy_warns_when_city_data_is_stale(validator, db):
    art = run(validator, db, metric="zhvi", cities=[{"city": "Stale Town"}], operation="yoy_change")
    assert art.summary["cities"][0]["end_month"] == date(2024, 12, 1)
    assert any("Latest data for Stale Town, KS is Dec 2024" in w for w in art.warnings)


def test_yoy_statewide_excludes_stale_cities(validator, db):
    art = run(validator, db, metric="zhvi", state_filter="KS", operation="yoy_change")
    assert [c["city"] for c in art.summary["cities"]] == ["Wichita"]
    assert any("1 city(ies) excluded" in w and "Stale Town" in w for w in art.warnings)


def test_aggregate_warns_when_requested_city_missing(validator, db):
    # Boulder's ZORI is missing Jun-Jul 2023, so only Denver reports in this window.
    art = run(
        validator,
        db,
        metric="zori",
        cities=[{"city": "Denver"}, {"city": "Boulder"}],
        start_month="2023-06",
        end_month="2023-07",
        operation="aggregate",
        aggregate="avg",
    )
    assert art.summary["first"]["regions"] == 1
    assert any("Only 1 of the 2 requested cities" in w for w in art.warnings)


def test_statewide_change_excludes_partial_windows(validator, db):
    art = run(validator, db, metric="zhvi", state_filter="CO", operation="change")
    assert "Fort Collins" not in [c["city"] for c in art.summary["cities"]]
    assert len(art.rows) == 4  # full rows still include it
    assert any("excluded" in w and "Fort Collins" in w for w in art.warnings)


def test_statewide_summary_cap_prefers_largest_cities(validator, db):
    # Fixture size ranks: Denver 0, Boulder 1, Mead 2 -> alphabetical would pick Boulder.
    art = run(validator, db, **CO_2025, operation="change", limit=1)
    assert [c["city"] for c in art.summary["cities"]] == ["Denver"]
    assert any("largest of 4 cities" in w for w in art.warnings)


def test_rank_labels_disambiguate_same_name_cities(validator, db):
    art = run(
        validator,
        db,
        metric="zhvi",
        cities=[
            {"city": "Oakwood", "county": "Montgomery"},
            {"city": "Oakwood", "county": "Cuyahoga"},
            {"city": "Springfield", "state": "IL"},
            {"city": "Springfield", "state": "MO"},
        ],
        operation="rank",
        rank_by="value",
    )
    labels = [r["label"] for r in art.rows]
    assert len(set(labels)) == 4
    assert "Oakwood, OH (Montgomery County)" in labels and "Springfield, IL" in labels
    assert art.chart == {"type": "bar", "x": "label", "y": "end_value"}
