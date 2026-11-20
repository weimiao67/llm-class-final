"""Ingest the downloaded Zillow city CSVs into a versioned Parquet dataset.

Usage:
    uv run python scripts/ingest_zillow.py \
        --zhvi datasets/City_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv \
        --zori datasets/City_zori_uc_sfrcondomfr_sm_sa_month.csv \
        --data-dir data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from housing.ingest import IngestError, SourceFile, ingest

ZHVI_VARIANT = "All homes (SFR + condo), mid tier 0.33-0.67, smoothed, seasonally adjusted"
ZORI_VARIANT = "All homes + multifamily, smoothed, seasonally adjusted"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zhvi", type=Path, required=True)
    parser.add_argument("--zori", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    sources = [
        SourceFile("zhvi", args.zhvi, ZHVI_VARIANT),
        SourceFile("zori", args.zori, ZORI_VARIANT),
    ]
    try:
        manifest = ingest(sources, args.data_dir)
    except IngestError as exc:
        print(f"Ingest failed; active dataset unchanged: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
