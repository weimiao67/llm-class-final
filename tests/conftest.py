"""Shared fixture: a tiny Zillow-shaped dataset ingested through the real pipeline.

Months: 2023-01 .. 2025-12 (36 month-end columns).
Values are linear in the month index so expected results are easy to compute by hand:
    value = base + step * i   (i = 0 for 2023-01)
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from housing.db import HousingDB
from housing.ingest import SourceFile, ingest
from tools.validator import PlanValidator

HEADER = [
    "RegionID",
    "SizeRank",
    "RegionName",
    "RegionType",
    "StateName",
    "State",
    "Metro",
    "CountyName",
]


def month_ends() -> list[str]:
    out = []
    for i in range(36):
        y, m = 2023 + i // 12, i % 12 + 1
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        out.append(date.fromordinal(nxt.toordinal() - 1).isoformat())
    return out


# region_id, name, state, county, base, step, missing month indexes, first index with data
ZHVI = [
    ("1", "Denver", "CO", "Denver County", 500_000, 1_000, set(), 0),
    ("2", "Boulder", "CO", "Boulder County", 800_000, 500, set(), 0),
    ("3", "Mead", "CO", "Weld County", 400_000, 2_000, {30}, 0),
    ("4", "Fort Collins", "CO", "Larimer County", 550_000, -200, set(), 12),  # starts 2024-01
    ("5", "Oakwood", "OH", "Montgomery County", 300_000, 300, set(), 0),
    ("6", "Oakwood", "OH", "Cuyahoga County", 150_000, 100, set(), 0),
    ("7", "Springfield", "IL", "Sangamon County", 160_000, 100, set(), 0),
    ("8", "Springfield", "MO", "Greene County", 200_000, 150, set(), 0),
    ("9", "Wichita", "KS", "Sedgwick County", 250_000, 400, set(), 0),
    ("10", "Stale Town", "KS", "Ford County", 90_000, 50, set(range(24, 36)), 0),  # ends 2024-12
]
ZORI = [
    ("1", "Denver", "CO", "Denver County", 2_000, 5, set(), 0),
    ("2", "Boulder", "CO", "Boulder County", 2_500, 10, {5, 6}, 0),
]


def value(base: int, step: int, i: int) -> float:
    return float(base + step * i)


def write_wide(path: Path, rows) -> None:
    months = month_ends()
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER + months)
        for rank, (rid, name, state, county, base, step, missing, first) in enumerate(rows):
            vals = [
                "" if (i in missing or i < first) else value(base, step, i)
                for i in range(len(months))
            ]
            writer.writerow([rid, rank, name, "city", state, state, f"{name} Metro", county] + vals)


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("zillow")
    write_wide(root / "zhvi.csv", ZHVI)
    write_wide(root / "zori.csv", ZORI)
    ingest(
        [
            SourceFile("zhvi", root / "zhvi.csv", "test zhvi"),
            SourceFile("zori", root / "zori.csv", "test zori"),
        ],
        root / "data",
    )
    return root / "data"


@pytest.fixture(scope="session")
def db(data_dir) -> HousingDB:
    return HousingDB(data_dir)


@pytest.fixture(scope="session")
def validator(db) -> PlanValidator:
    return PlanValidator(db)
