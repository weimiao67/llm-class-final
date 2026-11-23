"""Re-score saved eval runs on a corrected case file, offline (no endpoint needed).

Usage:
    uv run python scripts/rescore_eval.py --cases evaluation/cases/v1.1.jsonl \
        evaluation/reports/*/

For each run it writes summary-<cases>.json and results-<cases>.jsonl next to the original files,
and prints the original and corrected scores side by side.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from evaluation.cases import load_cases
from evaluation.rescore import changed_ids, rescore_run
from housing.db import HousingDB


def rate(summary: dict, key: str) -> str:
    value = summary["overall"][key]["rate"]
    return "—" if value is None else f"{value * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path, help="evaluation/reports/<run-id>/ folders")
    parser.add_argument("--cases", type=Path, required=True, help="corrected case file")
    parser.add_argument("--base", type=Path, default=Path("evaluation/cases/v1.jsonl"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    base, corrected = load_cases(args.base), load_cases(args.cases)
    print(f"{args.cases.name}: re-scoring {sorted(changed_ids(base, corrected))}\n")
    db = HousingDB(args.data_dir)
    label = args.cases.stem
    print(f"{'run':58s} {'turn success':>22s} {'execution accuracy':>22s}")
    for run in args.runs:
        if not (run / "results.jsonl").exists() or not (run / "summary.json").exists():
            continue
        original = json.loads((run / "summary.json").read_text())
        if original.get("meta", {}).get("model_id") in ("oracle", "stub"):
            continue
        results, summary = rescore_run(run, base, corrected, db)
        (run / f"summary-{label}.json").write_text(
            json.dumps(
                {"meta": {**original.get("meta", {}), "cases_file": str(args.cases)}, **summary},
                indent=2,
            )
            + "\n"
        )
        with (run / f"results-{label}.jsonl").open("w") as fh:
            for r in results:
                fh.write(json.dumps(asdict(r)) + "\n")
        turn = f"{rate(original, 'turn_success')} → {rate(summary, 'turn_success')}"
        exe = f"{rate(original, 'execution_accuracy')} → {rate(summary, 'execution_accuracy')}"
        print(f"{run.name:58s} {turn:>22s} {exe:>22s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
