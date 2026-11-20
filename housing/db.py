"""Read-only access to the active dataset version through DuckDB.

Only trusted code (the plan compiler) passes SQL here; the model never does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb


@dataclass(frozen=True)
class Region:
    region_id: str
    city: str
    state: str
    county: str | None
    metrics: frozenset[str]


@dataclass(frozen=True)
class Coverage:
    metric: str
    first_month: date
    last_month: date
    regions: int
    observations: int


def sql_string_literal(text: str) -> str:
    """Quote a trusted local path for DuckDB statements that cannot bind it as a parameter."""
    return "'" + text.replace("'", "''") + "'"


class HousingDB:
    def __init__(self, data_dir: Path | str):
        data_dir = Path(data_dir)
        active = data_dir / "active_version.txt"
        if not active.exists():
            raise FileNotFoundError(
                f"No active dataset in {data_dir}; run scripts/ingest_zillow.py first"
            )
        self.dataset_version = active.read_text().strip()
        version_dir = data_dir / "parquet" / self.dataset_version
        self.manifest: dict = json.loads((version_dir / "manifest.json").read_text())
        parquet = (version_dir / "observations.parquet").as_posix()

        self._con = duckdb.connect()
        self._con.execute(
            f"CREATE VIEW observations AS SELECT * FROM read_parquet({sql_string_literal(parquet)})"
        )
        self.coverage: dict[str, Coverage] = {
            m: Coverage(m, first, last, n_regions, n_obs)
            for m, first, last, n_regions, n_obs in self._con.execute(
                """SELECT metric, min(month), max(month), count(DISTINCT region_id), count(*)
                   FROM observations GROUP BY metric"""
            ).fetchall()
        }
        self.regions: dict[str, Region] = {
            rid: Region(rid, city, state, county, frozenset(metrics))
            for rid, city, state, county, metrics in self._con.execute(
                """SELECT region_id, any_value(city), any_value(state), any_value(county),
                          list(DISTINCT metric)
                   FROM observations GROUP BY region_id"""
            ).fetchall()
        }

    def query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        cursor = self._con.cursor()
        result = cursor.execute(sql, params)
        names = [d[0] for d in result.description]
        return [dict(zip(names, row, strict=True)) for row in result.fetchall()]

    def source_files(self) -> list[dict]:
        return self.manifest["sources"]
