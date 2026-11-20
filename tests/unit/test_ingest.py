from datetime import date

import pytest

from housing.ingest import IngestError, SourceFile, ingest
from tests.conftest import ZHVI, write_wide


def test_ingest_profiles_long_rows_and_drops_missing_months(db):
    profile = db.manifest["profile"]
    # 10 regions x 36 months, minus Mead's gap (1), Fort Collins' first year (12),
    # and Stale Town's last year (12)
    assert profile["zhvi"]["observations"] == 10 * 36 - 1 - 12 - 12
    assert profile["zori"]["observations"] == 2 * 36 - 2
    assert db.coverage["zhvi"].first_month == date(2023, 1, 1)
    assert db.coverage["zhvi"].last_month == date(2025, 12, 1)


def test_months_are_normalized_to_first_of_month(db):
    rows = db.query(
        "SELECT DISTINCT month FROM observations WHERE metric = ? ORDER BY month LIMIT 2",
        ["zhvi"],
    )
    assert [r["month"] for r in rows] == [date(2023, 1, 1), date(2023, 2, 1)]


def test_manifest_records_sources_and_checksums(db):
    sources = {s["metric"]: s for s in db.source_files()}
    assert set(sources) == {"zhvi", "zori"}
    assert len(sources["zhvi"]["sha256"]) == 64


def test_failed_ingest_keeps_previous_active_version(tmp_path):
    good = tmp_path / "good.csv"
    write_wide(good, ZHVI[:2])
    data = tmp_path / "data"
    first = ingest([SourceFile("zhvi", good, "v")], data)

    bad = tmp_path / "bad.csv"
    write_wide(bad, [ZHVI[0], ZHVI[0]])  # duplicate RegionID -> duplicate keys
    with pytest.raises(IngestError, match="duplicate"):
        ingest([SourceFile("zhvi", bad, "v")], data)

    assert (data / "active_version.txt").read_text().strip() == first["dataset_version"]


def test_missing_required_column_is_rejected(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("RegionID,RegionName\n1,Denver\n")
    with pytest.raises(IngestError, match="missing required columns"):
        ingest([SourceFile("zhvi", path, "v")], tmp_path / "data")


def test_same_inputs_give_same_version(tmp_path):
    src = tmp_path / "z.csv"
    write_wide(src, ZHVI[:3])
    a = ingest([SourceFile("zhvi", src, "v")], tmp_path / "a")
    b = ingest([SourceFile("zhvi", src, "v")], tmp_path / "b")
    assert a["dataset_version"] == b["dataset_version"]


def test_paths_with_apostrophes_work(tmp_path):
    from housing.db import HousingDB

    root = tmp_path / "o'neil"
    root.mkdir()
    write_wide(root / "z.csv", ZHVI[:2])
    ingest([SourceFile("zhvi", root / "z.csv", "v")], root / "data")
    assert HousingDB(root / "data").coverage["zhvi"].observations == 72
