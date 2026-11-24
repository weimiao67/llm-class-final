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
import re
import sys
from datetime import datetime
from pathlib import Path

from agent.model_clients.stub import StubModelClient, demo_rules
from evaluation.cases import load_cases
from evaluation.oracle import OracleModelClient
from evaluation.runner import run_eval, write_report
from housing.db import HousingDB
from tools.knowledge import BM25KnowledgeBase

DEFAULT_CASES = Path("evaluation/cases/v1.jsonl")


def safe_name(text: str) -> str:
    """Folder-safe run label: Hugging Face ids like "meta-llama/Llama-3.2-3B" contain slashes."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "model"


def pct(metric: dict) -> str:
    """A metric's rate for the console; "n/a" when no case was scored on it (e.g. execution
    accuracy on a methodology-only run), never a misleading 0.0%."""
    return "n/a" if metric["rate"] is None else f"{metric['rate']:.1%}"


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
    parser.add_argument(
        "--knowledge",
        type=Path,
        nargs="?",
        const=Path("rag/corpus"),
        help="answer methodology questions from this corpus (default rag/corpus); without it "
        "they're scored on choosing search_knowledge only",
    )
    parser.add_argument(
        "--unconstrained",
        action="store_true",
        help="plan without the JSON-schema grammar (ablation); validation is unchanged",
    )
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

    constrained = not args.unconstrained
    knowledge = BM25KnowledgeBase.from_dir(args.knowledge) if args.knowledge else None
    results = run_eval(
        cases, db, factory, knowledge=knowledge, progress=progress, constrained=constrained
    )
    label = model_id if constrained else f"{model_id}-unconstrained"
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{safe_name(label)}"
    report = write_report(
        args.out_dir / run_id,
        results,
        model_id=model_id,
        db=db,
        cases_file=str(args.cases),
        knowledge_base=knowledge is not None,
        constrained=constrained,
    )
    o = report["overall"]
    print(
        f"\nTurn success {pct(o['turn_success'])} · execution accuracy "
        f"{pct(o['execution_accuracy'])} · report: {args.out_dir / run_id}"
    )
    failed_oracle = args.model == "oracle" and o["turn_success"]["rate"] != 1.0
    return 1 if failed_oracle else 0


if __name__ == "__main__":
    sys.exit(main())
