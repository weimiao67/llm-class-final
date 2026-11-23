"""Build the Step 3 planner training data (train/dev JSONL) and its report.

Usage:
    uv run python scripts/build_training_data.py            # 3,000 examples, seed 13

Data goes to data/training/<version>/ (git-ignored; uploaded to S3 for training in Step 3b).
The report and review samples go to training/reports/<version>/ (committed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.prompts import PROMPT_VERSION
from evaluation.cases import load_cases
from housing.db import HousingDB
from training.build import Generator, data_version, write_outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--cases", type=Path, default=Path("evaluation/cases/v1.jsonl"))
    parser.add_argument("--holdout", type=Path, default=Path("evaluation/cases/v1_holdout.json"))
    parser.add_argument("--out", type=Path, default=Path("data/training"))
    parser.add_argument("--reports", type=Path, default=Path("training/reports"))
    args = parser.parse_args()

    db = HousingDB(args.data_dir)
    gen = Generator(db, json.loads(args.holdout.read_text()), load_cases(args.cases))
    built = gen.generate(args.n, args.seed)
    version = data_version(args.seed, args.n, db.dataset_version)
    meta = {
        "data_version": version,
        "seed": args.seed,
        "requested": args.n,
        "dataset_version": db.dataset_version,
        "prompt_version": PROMPT_VERSION,
        "holdout_file": str(args.holdout),
        "rejected_counter": gen.rejected,
    }
    s = write_outputs(built, meta, args.out / version, args.reports / version)
    print(f"{s['examples']} examples → {args.out / version}")
    print("splits:", s["counts"]["split"], "| scenarios:", s["counts"]["scenario"])
    print("rejected:", s["rejected"])
    print("sha256:", {k: v[:16] for k, v in s["sha256"].items()})
    out = args.reports / version
    print(f"report: {out}/report.md, samples: {out}/samples.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
