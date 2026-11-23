# Training runbook: LoRA fine-tune of the Qwen2.5-3B planner (SageMaker Studio)

This runbook trains the Step 3 LoRA model on the planner training data, deploys the merged model,
and scores it on the 200-case eval set. It uses the same account, Region (`us-east-2`), and Studio
setup as [docs/deployment.md](deployment.md).

**Cost:** a training job bills by the second while it runs (`ml.g5.xlarge` is about $1.4/hour).
The smoke job is about 15–25 minutes, and the full run (1 epoch) about 50–60 minutes. The evaluation endpoint
afterwards is about $1.5/hour, as in Step 2.

## 0. Prerequisites

- The Studio setup from [docs/deployment.md](deployment.md) steps 1–2: repo cloned, `uv sync`
  done, Zillow data ingested into `data/`.
- Training-job quota for `ml.g5.xlarge` (Service Quotas → SageMaker → "ml.g5.xlarge for training
  job usage" ≥ 1). A5/A6 trained there. `--instance-type ml.g6e.xlarge` is the fallback.
- No Hugging Face token is needed: Qwen2.5-3B-Instruct isn't gated.

## 1. Build the training data (about 25 s)

```bash
cd ~/llm-class-final && git pull
uv run python scripts/build_training_data.py
```

It should print `3000 examples → data/training/f261a5f4d7`, the version whose report is committed
in `training/reports/f261a5f4d7/`. The build is deterministic. It should also print
`sha256: {'train.jsonl': '13e6c28d43a5eab2', 'dev.jsonl': '21fcff46fc41f459'}`, the checksums of the
reviewed build. A different version or checksum means the code or dataset differs from the reviewed
one; stop and check before training.

## 2. Smoke job (about 15–25 minutes)

`launch_train.py` uses Studio's own `python`, because it needs the `sagemaker` SDK:

```bash
python scripts/launch_train.py --data-dir data/training/f261a5f4d7 --smoke
```

It trains on 32 rows for 1 epoch, then still merges and uploads the full 3B model (about 6 GB).
That checks the container, the library pins, data loading, merging, the chat template, and upload
before the full run. Compressing and uploading the model is most of the time. At the end it
prints the S3 paths for `model.tar.gz` and `output.tar.gz`.

**Optional but recommended (about 15 minutes, about $0.40):** deploy the smoke model and run the
endpoint smoke test. This checks the path from merged model to TGI (weights load, the chat
template is found, constrained decoding works) before spending an hour on the full run. The
smoke model's answers will be poor, since it trained on only 32 rows; only checks 1–4 passing
matter.

```bash
python scripts/deploy_endpoint.py --name final-wm-qwen-lora-smoke \
  --model-data s3://…/output/model.tar.gz --fallback-instance-types ml.g6.2xlarge ml.g6e.xlarge
uv run python scripts/smoke_endpoint.py --endpoint final-wm-qwen-lora-smoke
python scripts/deploy_endpoint.py --delete --name final-wm-qwen-lora-smoke
```

## 3. Full training run (about 50–60 minutes)

```bash
python scripts/launch_train.py --data-dir data/training/f261a5f4d7
```

Defaults (in `training/job/train.py`):

| Setting | Value |
|---|---|
| LoRA | r 16, alpha 32, dropout 0.05 |
| Target modules | `q,k,v,o,gate,up,down_proj` |
| Learning rate | 2e-4, cosine, 3% warmup |
| Epochs | 1 (data `93a8b1a171`: dev loss was flat from epoch 1 to epoch 2) |
| Batch size | 4 × 4 gradient accumulation |
| Precision | bf16, with gradient checkpointing |
| Loss | final assistant turn only |

Variants: `--epochs 3 --name ep3`, `--learning-rate 1e-4 --name lr1e4`.

Read the metrics (training loss, dev loss per epoch, runtime, peak VRAM) with the command the
script prints, for example:

```bash
aws s3 cp s3://…/output/output.tar.gz /tmp/ && tar -xzf /tmp/output.tar.gz -C /tmp \
  && python -m json.tool /tmp/training_metrics.json | head -40
```

Dev loss is reported once per epoch. With the 1-epoch default there is a single value; for a
`--epochs 2` comparison run, dev loss should still fall in epoch 2. If it stays flat or rises
while training loss keeps falling (as with data `93a8b1a171`: 0.0373 → 0.0376, training loss
0.0036), the extra epoch is memorizing, not generalizing.

## 4. Deploy and evaluate the merged model

Use the deploy command `launch_train.py` printed (the merged weights load straight into TGI), then
the same checks as the baseline:

```bash
python scripts/deploy_endpoint.py --name final-wm-qwen-lora \
  --model-data s3://…/output/model.tar.gz --fallback-instance-types ml.g6.2xlarge ml.g6e.xlarge
uv run python scripts/smoke_endpoint.py --endpoint final-wm-qwen-lora              # first request
uv run python scripts/run_eval.py --model sagemaker --endpoint final-wm-qwen-lora \
  --model-id qwen2.5-3b-lora-f261a5f4d7
uv run python scripts/run_eval.py --model sagemaker --endpoint final-wm-qwen-lora \
  --model-id qwen2.5-3b-lora-f261a5f4d7 --unconstrained                              # ablation
python scripts/deploy_endpoint.py --delete --name final-wm-qwen-lora
```

Optional, for the base model's "no constraint" row: deploy the base model again
(`--hf-model-id Qwen/Qwen2.5-3B-Instruct --name final-wm-qwen25-3b-base`) and run the eval with
`--unconstrained --model-id qwen2.5-3b-instruct-planner-v2`.

## 5. Bring the results back

```bash
git add evaluation/reports/ && git commit -m "Add Qwen LoRA eval reports" && git push
```

Also paste or copy the `training_metrics.json` summary (first ~40 lines) so it can be recorded in
`docs/evaluation.md`.
