"""Launch the Step 3 LoRA training job on SageMaker (run from a SageMaker Studio terminal).

Adapted from assignment A6 (same SDK v3 ModelTrainer, Hugging Face training container, and
trl/peft pins). The job runs training/job/train.py; the dataset folder built by
scripts/build_training_data.py (train.jsonl, dev.jsonl, manifest.json) is uploaded as the `train`
channel. When the job ends, SageMaker uploads:
  * model.tar.gz:  the merged model, deployable with deploy_endpoint.py --model-data
  * output.tar.gz: training_metrics.json and the LoRA adapter (small)

Usage, from the repo root:
    python scripts/launch_train.py --data-dir data/training/076967313a --smoke   # ~15 min check
    python scripts/launch_train.py --data-dir data/training/076967313a           # full run
    python scripts/launch_train.py --data-dir ... --epochs 3 --name ep3          # a variant

Training bills by the second while the job runs (ml.g5.xlarge is about $1.4/h).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

INSTANCE_TYPE = "ml.g5.xlarge"  # A10G 24 GB; A5/A6 trained here. Fallback: ml.g6e.xlarge.
VOLUME_GB = 60  # base model download (~6 GB) + merged model (~6 GB) + archive
MAX_RUNTIME_HOURS = 3.0
JOB_PREFIX = "final-wm-qwen-lora"
SOURCE_DIR = "training/job"
REQUIRED_FILES = ("train.jsonl", "dev.jsonl", "manifest.json")
# Hugging Face training container (A6); requirements.txt then pins trl/peft/transformers.
IMAGE_VERSION = {"version": "4.56.2", "base_framework_version": "pytorch2.8.0",
                 "py_version": "py312"}  # fmt: skip
SMOKE = {"num-samples": 32, "epochs": 1, "logging-steps": 1}


def check_data_dir(path: Path) -> dict[str, Any]:
    """The dataset folder must be complete and match its manifest's version."""
    missing = [f for f in REQUIRED_FILES if not (path / f).exists()]
    if missing:
        raise SystemExit(f"{path} is missing {missing}; run scripts/build_training_data.py")
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest.get("data_version") != path.name:
        raise SystemExit(
            f"{path} holds data version {manifest.get('data_version')!r}, not {path.name!r}"
        )
    return manifest


def hyperparameters(args: argparse.Namespace) -> dict[str, Any]:
    """CLI args for train.py. Its own defaults are the run's settings; only overrides go here."""
    hp: dict[str, Any] = dict(SMOKE) if args.smoke else {}
    for key in ("epochs", "learning_rate", "lora_r"):
        value = getattr(args, key)
        if value is not None:
            hp[key.replace("_", "-")] = value
    return hp


def job_name(args: argparse.Namespace) -> str:
    parts = [JOB_PREFIX, "smoke" if args.smoke else None, args.name]
    return "-".join(p for p in parts if p)


def training_image(region: str, instance_type: str) -> str:
    try:  # sagemaker SDK v3 (what A6 used)
        from sagemaker.core import image_uris
    except ImportError:
        from sagemaker import image_uris
    return image_uris.retrieve(
        framework="huggingface",
        region=region,
        instance_type=instance_type,
        image_scope="training",
        **IMAGE_VERSION,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True, help="data/training/<version>")
    parser.add_argument("--smoke", action="store_true", help="32 rows, 1 epoch")
    parser.add_argument("--name", help="suffix for the job name, e.g. ep3")
    parser.add_argument("--epochs", type=float)
    parser.add_argument("--learning-rate", type=float)
    parser.add_argument("--lora-r", type=int)
    parser.add_argument("--instance-type", default=INSTANCE_TYPE)
    parser.add_argument("--max-runtime-hours", type=float, default=MAX_RUNTIME_HOURS)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-2"))
    args = parser.parse_args(argv)

    manifest = check_data_dir(args.data_dir)
    print(
        f"data {manifest['data_version']}: {manifest['counts']['split']} "
        f"(prompt {manifest['prompt_version']})"
    )

    from sagemaker.train import ModelTrainer
    from sagemaker.train.configs import Compute, InputData, SourceCode, StoppingCondition

    environment = {"HF_TOKEN": os.environ["HF_TOKEN"]} if os.environ.get("HF_TOKEN") else {}
    trainer = ModelTrainer(
        base_job_name=job_name(args),
        training_image=training_image(args.region, args.instance_type),
        source_code=SourceCode(
            source_dir=SOURCE_DIR,
            entry_script="train.py",
            requirements="requirements.txt",
            ignore_patterns=["__pycache__"],
        ),
        compute=Compute(instance_type=args.instance_type, volume_size_in_gb=VOLUME_GB),
        stopping_condition=StoppingCondition(
            max_runtime_in_seconds=int(args.max_runtime_hours * 3600)
        ),
        hyperparameters=hyperparameters(args),
        environment=environment,
    )
    trainer.train(
        input_data_config=[InputData(channel_name="train", data_source=str(args.data_dir))],
        wait=True,
        logs=True,
    )
    job = trainer._latest_training_job
    model_uri = job.model_artifacts.s3_model_artifacts
    output_uri = model_uri.rsplit("/", 1)[0] + "/output.tar.gz"
    print(f"\nMerged model: {model_uri}")
    print(f"Metrics:      {output_uri}")
    print("\nRead the metrics:")
    print(
        f"  aws s3 cp {output_uri} /tmp/ && tar -xzf /tmp/output.tar.gz -C /tmp "
        "&& cat /tmp/training_metrics.json | head -40"
    )
    print("Deploy it:")
    print(
        f"  python scripts/deploy_endpoint.py --name {job_name(args)} --model-data {model_uri} "
        "--fallback-instance-types ml.g6.2xlarge ml.g6e.xlarge"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
