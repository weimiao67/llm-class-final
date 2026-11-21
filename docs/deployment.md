# Deployment runbook: baseline endpoint and evaluation (SageMaker Studio)

This runbook deploys the Step 2 baseline model (`meta-llama/Llama-3.2-3B-Instruct`) to a SageMaker
real-time endpoint, checks it, scores it on the 200-case eval set, and deletes it. It uses the same
account, Region (`us-east-2`), and Studio setup as assignments A4–A8.

**Cost:** the endpoint runs on `ml.g5.2xlarge` (about $1.5/hour, check current pricing) from the
moment it is created until it is deleted. One full session (deploy, smoke test, full eval, delete)
takes about 45–60 minutes. **Always finish with step 7.**

## 0. Prerequisites

- SageMaker Studio in `us-east-2` with the execution role used in A7. It can create models,
  endpoint configs, and endpoints.
- A Hugging Face token with access to `meta-llama/Llama-3.2-3B-Instruct`. The model is gated:
  accept its license on the model page if you haven't already, because access to the 1B model
  does not always cover the 3B model.
- Endpoint quota for `ml.g5.2xlarge` (Service Quotas → SageMaker → "ml.g5.2xlarge for endpoint
  usage" ≥ 1). It worked in A7.

## 1. Get the code (Studio terminal)

```bash
git clone https://github.com/weimiao67/llm-class-final.git
cd llm-class-final
git checkout step2-baseline-endpoint      # until this branch is merged; then stay on main
pip install --user uv                     # or: curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --python 3.12                     # uv downloads Python 3.12 if Studio's is different
```

## 2. Load the data

Put the two Zillow city CSVs in `datasets/`. Uploading the same files you used locally keeps the
dataset version identical (`23ccd46a4560`): drag them into `llm-class-final/datasets/` in the
Studio file browser (about 100 MB). Alternatively, download the current files from Zillow
Research. These URLs follow Zillow's public file layout; if they fail, use the upload instead:

```bash
mkdir -p datasets
curl -L -o datasets/City_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv \
  https://files.zillowstatic.com/research/public_csvs/zhvi/City_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv
curl -L -o datasets/City_zori_uc_sfrcondomfr_sm_sa_month.csv \
  https://files.zillowstatic.com/research/public_csvs/zori/City_zori_uc_sfrcondomfr_sm_sa_month.csv
```

Then ingest it and confirm the oracle still scores 100% on this copy of the data:

```bash
uv run python scripts/ingest_zillow.py \
  --zhvi datasets/City_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv \
  --zori datasets/City_zori_uc_sfrcondomfr_sm_sa_month.csv --data-dir data
uv run python scripts/run_eval.py --model oracle --out-dir /tmp/eval   # must print 100.0%
```

Newer Zillow files can make a few gold cases behave differently, for example when a city gains
rent data. In that case the oracle run fails and lists those cases; fix the cases before scoring
a model.

## 3. Deploy the endpoint (~10 minutes; billing starts)

`deploy_endpoint.py` uses Studio's own `python` (it needs the `sagemaker` SDK for the image
lookup and the execution role, and it imports nothing from this repo):

```bash
export HF_TOKEN=hf_...            # don't commit or paste it into files
python scripts/deploy_endpoint.py # → "final-wm-llama32-3b-base is InService."
python scripts/deploy_endpoint.py --status
```

The token is passed to the container as an environment variable, so anyone in the account who can
run `DescribeModel` can see it. Use a read-only token, and revoke it after the project.

## 4. Smoke-test the request settings

```bash
uv run python scripts/smoke_endpoint.py --endpoint final-wm-llama32-3b-base
```

It checks that TGI accepts the JSON-schema constraint (`response_format`), that greedy decoding
is deterministic, and that sampled answers work. **If check 1 fails, stop here** (go to step 7)
and share the output: it usually means TGI rejected part of the schema, and the fix belongs in the
code, not the endpoint.

## 5. Run the evaluation

Start with a quick run, then the full set (about 15–25 minutes):

```bash
uv run python scripts/run_eval.py --model sagemaker --endpoint final-wm-llama32-3b-base \
  --model-id llama-3.2-3b-instruct-base --limit 20
uv run python scripts/run_eval.py --model sagemaker --endpoint final-wm-llama32-3b-base \
  --model-id llama-3.2-3b-instruct-base
```

The report is written to `evaluation/reports/<timestamp>-llama-3.2-3b-instruct-base/`
(`report.md`, `summary.json`, `results.jsonl`).

## 6. Bring the report back

Either download the report folder from the Studio file browser into
`evaluation/reports/` locally, or commit it from Studio:

```bash
git add evaluation/reports/ && git commit -m "Add Llama-3.2-3B baseline eval report" && git push
```

Pushing from Studio needs GitHub authentication there (for example a fine-grained token with
access to this repository only).

## 7. Delete the endpoint (stops billing)

```bash
python scripts/deploy_endpoint.py --delete
python scripts/deploy_endpoint.py --status   # → "Could not find endpoint ..."
```

Also check the SageMaker console (Inference → Endpoints) to confirm nothing is left running.
