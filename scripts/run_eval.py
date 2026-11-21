"""Run the evaluation set against a model backend and write a report.

Usage:
    # Check the eval set itself (gold calls must all succeed):
    uv run python scripts/run_eval.py --model oracle
    # Score the offline stub model:
    uv run python scripts/run_eval.py --model stub
    # Score a deployed SageMaker TGI endpoint:
    uv run python scripts/run_eval.py --model sagemaker --endpoint <name> --model-id <label>

Reports go to evaluation/reports/<run-id>/ (report.md, summary.json, results.jsonl).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from agent.model_clients.stub import StubModelClient, demo_rules
from evaluation.cases import load_cases
from evaluation.oracle import OracleModelClient
from evaluation.runner import run_eval, write_report
from housing.db import HousingDB

DEFAULT_CASES = Path("evaluation/cases/v1.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", choices=["oracle", "stub", "sagemaker"], required=True)
    parser.add_argument("--endpoint", help="SageMaker endpoint name (for --model sagemaker)")
    parser.add_argument("--model-id", help="label for the report, e.g. llama-3.2-3b-base")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--out-dir", type=Path, default=Path("evaluation/reports"))
    parser.add_argument("--family", action="append", help="only run these families")
    parser.add_argument("--limit", type=int, help="only run the first N cases (smoke test)")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if args.family:
        cases = [c for c in cases if c.family in set(args.family)]
    if args.limit:
        cases = cases[: args.limit]
    db = HousingDB(args.data_dir)

    if args.model == "oracle":
        factory, model_id = OracleModelClient, "oracle"
    elif args.model == "stub":
        stub = StubModelClient(rules=demo_rules())
        factory, model_id = (lambda case: stub), "stub"
    else:
        if not args.endpoint:
            parser.error("--endpoint is required for --model sagemaker")
        from agent.model_clients.sagemaker import SageMakerModelClient

        client = SageMakerModelClient(args.endpoint, model_id=args.model_id, region=args.region)
        factory, model_id = (lambda case: client), client.model_id

    def progress(i, n, r):
        mark = "✓" if r.success else "✗"
        print(f"[{i:3d}/{n}] {mark} {r.id:<16} {r.latency_ms:8.0f} ms  {r.question[:60]}")

    results = run_eval(cases, db, factory, progress=progress)
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{model_id}"
    report = write_report(
        args.out_dir / run_id,
        results,
        model_id=model_id,
        db=db,
        cases_file=str(args.cases),
        knowledge_base=False,
    )
    o = report["overall"]
    print(
        f"\nTurn success {o['turn_success']['rate']:.1%} · execution accuracy "
        f"{(o['execution_accuracy']['rate'] or 0):.1%} · report: {args.out_dir / run_id}"
    )
    failed_oracle = args.model == "oracle" and o["turn_success"]["rate"] != 1.0
    return 1 if failed_oracle else 0


if __name__ == "__main__":
    sys.exit(main())
