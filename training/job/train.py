"""LoRA fine-tune the Qwen2.5-3B-Instruct planner, merge the adapter, and save a deployable model.

Entry script of a SageMaker training job on the Hugging Face PyTorch container (launched by
scripts/launch_train.py). Hyperparameters arrive as --key value CLI args. The `train` channel
(SM_CHANNEL_TRAIN) holds the files built by scripts/build_training_data.py: train.jsonl,
dev.jsonl, and manifest.json.

Each record is a full message list (system, any history, the user question, and for retry
examples a rejected call plus the agent's retry feedback) ending with the gold assistant tool call.
It is split into a conversational prompt (everything but the last turn) and a completion (the last
assistant turn), and with completion_only_loss only that final reply is trained. The rejected call
inside a retry example is never learned.

After training, the adapter is merged into the base weights (merge_and_unload) and saved to
SM_MODEL_DIR, which SageMaker uploads as model.tar.gz: deploy it directly with
`scripts/deploy_endpoint.py --model-data <s3 uri>` (TGI loads it from /opt/ml/model). The small
training_metrics.json also goes to SM_OUTPUT_DATA_DIR (output.tar.gz), so the loss curve can be read
without downloading the model.

Keep this file self-contained (no imports from the repo) and on Python 3.12 syntax: it runs as a
top-level script on the container's Python. Heavy imports (torch, transformers, trl, peft) live
inside functions so the pure parts can be unit-tested without them.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

BASE_MODEL = "Qwen/Qwen2.5-3B-Instruct"
LORA_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
TRAIN_FILENAME, DEV_FILENAME, MANIFEST_FILENAME = "train.jsonl", "dev.jsonl", "manifest.json"
METRICS_FILENAME = "training_metrics.json"

# Defaults from A5/A6, adjusted for a 3B model and ~2.6k examples of ~1k tokens.
DEFAULTS = {
    "learning_rate": 2e-4,
    "warmup_ratio": 0.03,
    "epochs": 1.0,  # data 93a8b1a171: dev loss was flat from epoch 1 (0.0373) to 2 (0.0376)
    "batch_size": 4,  # x grad_accum 4 = 16 per step, about 165 steps per epoch
    "grad_accum": 4,
    "lora_r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "max_length": 2048,  # the longest example is about 1,200 tokens: nothing is truncated
    "seed": 42,
}


# ---- pure helpers (unit-tested without GPU libraries) -----------------------------------------


def to_prompt_completion(record: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Split a full message list into TRL's conversational prompt/completion form."""
    messages = record["messages"]
    if not messages or messages[-1]["role"] != "assistant":
        raise ValueError("a training record must end with the assistant's gold turn")
    return {"prompt": messages[:-1], "completion": [messages[-1]]}


def read_records(path: Path, num_samples: int = 0, seed: int = 42) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if 0 < num_samples < len(rows):
        import random

        rows = random.Random(seed).sample(rows, num_samples)
    return [to_prompt_completion(r) for r in rows]


def channel_dir() -> Path:
    """SageMaker mounts the `train` channel at SM_CHANNEL_TRAIN; locally, pass --data-dir."""
    return Path(os.environ.get("SM_CHANNEL_TRAIN", "data/training/latest"))


def summarize_run(
    log_history: list[dict],
    runtime_s: float,
    peak_vram_bytes: int,
    manifest: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    losses = [e["loss"] for e in log_history if "loss" in e]
    evals = [
        {"epoch": e.get("epoch"), "eval_loss": e["eval_loss"]}
        for e in log_history
        if "eval_loss" in e
    ]
    return {
        "base_model": args.model_name,
        "data_version": manifest.get("data_version"),
        "hyperparameters": {k: getattr(args, k) for k in DEFAULTS},
        "train_runtime_seconds": round(runtime_s, 1),
        "peak_vram_gb": round(peak_vram_bytes / 1024**3, 2),
        "first_logged_loss": losses[0] if losses else None,
        "final_logged_loss": losses[-1] if losses else None,
        "dev_loss_by_epoch": evals,
        "log_history": log_history,
    }


def embed_chat_template(model_dir: Path) -> bool:
    """Copy chat_template.jinja into tokenizer_config.json if it isn't there.

    transformers 4.57 saves the chat template only as chat_template.jinja, but TGI's Messages API
    reads it from tokenizer_config.json (the same fix as A7's merge_adapter.py). Without it the
    merged model's endpoint can't render chat requests the way training did. Returns whether the
    config now holds a template.
    """
    config_path = model_dir / "tokenizer_config.json"
    template_path = model_dir / "chat_template.jinja"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if "chat_template" not in config and template_path.exists():
        config["chat_template"] = template_path.read_text(encoding="utf-8")
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return bool(config.get("chat_template"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model-name", default=BASE_MODEL)
    p.add_argument("--learning-rate", type=float, default=DEFAULTS["learning_rate"])
    p.add_argument("--warmup-ratio", type=float, default=DEFAULTS["warmup_ratio"])
    p.add_argument("--epochs", type=float, default=DEFAULTS["epochs"])
    p.add_argument("--batch-size", type=int, default=DEFAULTS["batch_size"])
    p.add_argument("--grad-accum", type=int, default=DEFAULTS["grad_accum"])
    p.add_argument("--lora-r", type=int, default=DEFAULTS["lora_r"])
    p.add_argument("--lora-alpha", type=int, default=DEFAULTS["lora_alpha"])
    p.add_argument("--lora-dropout", type=float, default=DEFAULTS["lora_dropout"])
    p.add_argument("--max-length", type=int, default=DEFAULTS["max_length"])
    p.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    p.add_argument("--logging-steps", type=int, default=10)
    p.add_argument("--num-samples", type=int, default=0, help="0 = all rows (smoke runs: 32)")
    p.add_argument("--no-merge", action="store_true", help="save only the adapter")
    p.add_argument("--data-dir", type=Path, default=channel_dir())
    # SageMaker uploads SM_MODEL_DIR as model.tar.gz and SM_OUTPUT_DATA_DIR as output.tar.gz.
    p.add_argument("--output-dir", default=os.environ.get("SM_MODEL_DIR", "outputs/model"))
    p.add_argument("--metrics-dir", default=os.environ.get("SM_OUTPUT_DATA_DIR", "outputs/metrics"))
    return p.parse_args(argv)


# ---- training ---------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> dict[str, Any]:
    import datasets
    import torch
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    args = parse_args(argv)
    data_dir = Path(args.data_dir)
    manifest_path = data_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    train_rows = read_records(data_dir / TRAIN_FILENAME, args.num_samples, args.seed)
    dev_rows = read_records(data_dir / DEV_FILENAME, args.num_samples // 4, args.seed)
    print(f"data {manifest.get('data_version')}: {len(train_rows)} train, {len(dev_rows)} dev")

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    # Qwen2.5-Instruct ships pad "<|endoftext|>" distinct from eos "<|im_end|>"; keep it that way
    # so the end-of-turn token is never masked as padding.
    assert tokenizer.pad_token and tokenizer.pad_token != tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(args.model_name, dtype=torch.bfloat16)

    trainer = SFTTrainer(
        model=model,
        args=SFTConfig(
            output_dir=str(Path(args.output_dir) / "_checkpoints"),
            learning_rate=args.learning_rate,
            lr_scheduler_type="cosine",
            warmup_ratio=args.warmup_ratio,
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch_size,
            per_device_eval_batch_size=args.batch_size,
            gradient_accumulation_steps=args.grad_accum,
            gradient_checkpointing=True,
            max_length=args.max_length,
            bf16=True,
            completion_only_loss=True,
            logging_steps=args.logging_steps,
            eval_strategy="epoch" if dev_rows else "no",
            save_strategy="no",  # only the final model is kept
            report_to="none",
            seed=args.seed,
        ),
        train_dataset=datasets.Dataset.from_list(train_rows),
        eval_dataset=datasets.Dataset.from_list(dev_rows) if dev_rows else None,
        processing_class=tokenizer,
        peft_config=LoraConfig(
            r=args.lora_r,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            target_modules=LORA_TARGET_MODULES,
            task_type="CAUSAL_LM",
        ),
    )

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    trainer.train()
    runtime = time.perf_counter() - start
    peak = torch.cuda.max_memory_allocated() if torch.cuda.is_available() else 0

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    adapter_dir = Path(args.metrics_dir) / "adapter"  # small; kept with the metrics
    trainer.model.save_pretrained(adapter_dir)
    if args.no_merge:
        trainer.model.save_pretrained(out)
    else:
        merged = trainer.model.merge_and_unload()
        merged.save_pretrained(out, safe_serialization=True)
    tokenizer.save_pretrained(out)
    if not embed_chat_template(out):
        raise RuntimeError("the saved model has no chat template; TGI couldn't serve it")
    _remove_checkpoints(out / "_checkpoints")

    summary = summarize_run(trainer.state.log_history, runtime, peak, manifest, args)
    for directory in (out, Path(args.metrics_dir)):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / METRICS_FILENAME).write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"runtime {runtime / 60:.1f} min | peak VRAM {summary['peak_vram_gb']} GB | "
        f"loss {summary['first_logged_loss']} -> {summary['final_logged_loss']} | "
        f"dev {summary['dev_loss_by_epoch']}"
    )
    return summary


def _remove_checkpoints(path: Path) -> None:
    """Keep model.tar.gz to the merged weights: TGI loads whatever is in /opt/ml/model."""
    import shutil

    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    main()
