"""Convert wide Zillow city CSVs into one validated, versioned long-format Parquet dataset.

Layout produced under ``data_dir``::

    parquet/<dataset_version>/observations.parquet
    parquet/<dataset_version>/manifest.json
    active_version.txt          # written last, only after validation passes
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from housing.db import sql_string_literal

METRICS = ("zhvi", "zori")
ID_COLUMNS = (
    "RegionID",
    "SizeRank",
    "RegionName",
    "RegionType",
    "StateName",
    "State",
    "Metro",
    "CountyName",
)
MONTH_COLUMN_REGEX = r"^\d{4}-\d{2}-\d{2}$"


class IngestError(ValueError):
    """Raised when a source file fails validation. The active version is left unchanged."""


@dataclass(frozen=True)
class SourceFile:
    metric: str
    path: Path
    series_variant: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_long(con: duckdb.DuckDBPyConnection, source: SourceFile) -> None:
    """Load one wide CSV into the ``staged`` table as long rows (missing months are dropped)."""
    header = con.execute(
        "SELECT * FROM read_csv(?, header = true, sample_size = -1) LIMIT 0", [str(source.path)]
    ).description
    columns = [col[0] for col in header]
    missing = [c for c in ID_COLUMNS if c not in columns]
    if missing:
        raise IngestError(f"{source.path.name}: missing required columns {missing}")

    con.execute(
        f"""
        INSERT INTO staged
        SELECT
            ? AS metric,
            CAST("RegionID" AS VARCHAR) AS region_id,
            "RegionName" AS city,
            "State" AS state,
            "StateName" AS state_name,
            "CountyName" AS county,
            "Metro" AS metro,
            CAST("SizeRank" AS INTEGER) AS size_rank,
            CAST(date_trunc('month', CAST(month AS DATE)) AS DATE) AS month,
            CAST(value AS DOUBLE) AS value
        FROM (
            UNPIVOT (SELECT * FROM read_csv(?, header = true, sample_size = -1))
            ON COLUMNS('{MONTH_COLUMN_REGEX}')
            INTO NAME month VALUE value
        )
        """,
        [source.metric, str(source.path)],
    )


def _validate(con: duckdb.DuckDBPyConnection, sources: list[SourceFile]) -> dict:
    """Run integrity checks on the staged table and return a per-metric profile."""
    dupes = con.execute(
        """SELECT count(*) FROM (
               SELECT metric, region_id, month FROM staged
               GROUP BY ALL HAVING count(*) > 1)"""
    ).fetchone()[0]
    if dupes:
        raise IngestError(f"{dupes} duplicate (metric, region_id, month) keys")

    bad_values = con.execute(
        "SELECT count(*) FROM staged WHERE value IS NULL OR NOT isfinite(value) OR value <= 0"
    ).fetchone()[0]
    if bad_values:
        raise IngestError(f"{bad_values} non-positive or non-finite values")

    bad_keys = con.execute(
        "SELECT count(*) FROM staged WHERE region_id IS NULL OR city IS NULL OR state IS NULL"
    ).fetchone()[0]
    if bad_keys:
        raise IngestError(f"{bad_keys} rows missing region_id/city/state")

    profile = {}
    for source in sources:
        row = con.execute(
            """SELECT count(*), count(DISTINCT region_id), min(month), max(month)
               FROM staged WHERE metric = ?""",
            [source.metric],
        ).fetchone()
        if not row[0]:
            raise IngestError(f"{source.path.name}: no observations")
        profile[source.metric] = {
            "observations": row[0],
            "regions": row[1],
            "first_month": row[2].isoformat(),
            "last_month": row[3].isoformat(),
        }
    return profile


def ingest(sources: list[SourceFile], data_dir: Path) -> dict:
    """Ingest ``sources`` into a new dataset version and activate it. Returns the manifest."""
    metrics = [s.metric for s in sources]
    if sorted(metrics) != sorted(set(metrics)) or not set(metrics) <= set(METRICS):
        raise IngestError(f"expected each of {METRICS} at most once, got {metrics}")

    checksums = {s.metric: sha256_file(s.path) for s in sources}
    version = hashlib.sha256(
        "|".join(f"{m}:{checksums[m]}" for m in sorted(checksums)).encode()
    ).hexdigest()[:12]

    con = duckdb.connect()
    con.execute(
        """CREATE TABLE staged (
               metric VARCHAR, region_id VARCHAR, city VARCHAR, state VARCHAR,
               state_name VARCHAR, county VARCHAR, metro VARCHAR, size_rank INTEGER,
               month DATE, value DOUBLE)"""
    )
    for source in sources:
        _load_long(con, source)
    profile = _validate(con, sources)

    out_dir = data_dir / "parquet" / version
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "observations.parquet"
    con.execute(
        f"COPY (SELECT * FROM staged ORDER BY metric, region_id, month) "
        f"TO {sql_string_literal(parquet_path.as_posix())} (FORMAT parquet, COMPRESSION zstd)"
    )
    con.close()

    manifest = {
        "dataset_version": version,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": [
            {
                "metric": s.metric,
                "filename": s.path.name,
                "series_variant": s.series_variant,
                "sha256": checksums[s.metric],
            }
            for s in sources
        ],
        "profile": profile,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Activate last: a failure above leaves the previously active version in place.
    (data_dir / "active_version.txt").write_text(version + "\n")
    return manifest
