# Housing Market AI Analyst

A small language model plans analyses of Zillow city-level home values (ZHVI) and rents (ZORI);
trusted code validates each plan, compiles it to parameterized DuckDB SQL, and computes the
results deterministically. The model never writes SQL and never supplies the numbers.

> Status: Step 4 (product). The LoRA-tuned Qwen2.5-3B planner reaches 89.3% execution accuracy on
> the 200-case eval set (base model: 51.1%), see [docs/evaluation.md](docs/evaluation.md). Done so
> far: the methodology knowledge base (4a) and the Streamlit UI (4b); next, app deployment (4c).

## Quick start (no AWS needed)

```bash
uv sync --python 3.12

# 1. Put the Zillow city CSVs in datasets/ (git-ignored), then build the versioned dataset:
uv run python scripts/ingest_zillow.py \
    --zhvi datasets/City_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv \
    --zori datasets/City_zori_uc_sfrcondomfr_sm_sa_month.csv \
    --data-dir data

# 2. Run the tests (they use a synthetic fixture, not the real files)
uv run pytest
uv run ruff check .
```

## Run the API

```bash
# Offline, with the deterministic stub model (no AWS):
MODEL_BACKEND=stub uv run uvicorn api.main:app --port 8000
# Against a deployed SageMaker TGI endpoint:
MODEL_BACKEND=sagemaker SAGEMAKER_ENDPOINT_NAME=<name> AWS_REGION=us-east-2 \
    uv run uvicorn api.main:app --port 8000

curl -s localhost:8000/health   # liveness: always 200 while the app is up
curl -s localhost:8000/ready    # readiness: 503 when the model endpoint isn't InService
curl -s localhost:8000/v1/ask -H 'content-type: application/json' \
    -d '{"question": "Rank Colorado cities by ZHVI growth in 2025", "include_rows": false}'
```

Interactive API docs: <http://localhost:8000/docs>. Set `API_KEY` to require an `X-API-Key` header.

## Run the UI

The Streamlit UI is a client of the API: start the API first (above), then

```bash
uv run streamlit run ui/app.py        # opens http://localhost:8501
```

Set `ANALYST_API_URL` (default `http://localhost:8000`) and, if the API has one, `ANALYST_API_KEY`.
Ask in the sidebar or pick an example. Each answer has three tabs: **AI response** (warnings,
answer, headline numbers, chart), **Queried data** (every row, with CSV download), and **Evidence &
trace** (dataset version, resolved cities, the SQL and its parameters, the model's plan, knowledge
sources, and the tool events with timings). With `MODEL_BACKEND=stub`, the example questions are
answered by fixed rules, so the whole UI works without AWS.

## Layout

| Path | Role |
|---|---|
| `housing/ingest.py` | Wide Zillow CSV → validated long Parquet + manifest; activates only after validation |
| `housing/db.py` | Read-only DuckDB view over the active dataset version; coverage and region index |
| `tools/schemas.py` | `AnalysisPlan` and tool-call envelope (JSON Schema for prompts + constrained decoding) |
| `tools/resolve.py` | City resolution: exact match, ambiguity reporting, fuzzy suggestions |
| `tools/validator.py` | Data-aware validation → `ValidatedPlan` or a typed `ToolError` |
| `tools/compiler.py` | `ValidatedPlan` → parameterized SQL |
| `tools/operations.py` | Operation registry: series, change, yoy_change, extrema, rank, aggregate, coverage |
| `agent/decoding.py` | Decoding profiles per agent step (greedy+constrained plans, nucleus answers) |
| `agent/model_clients/` | Model-client interface, deterministic stub, SageMaker TGI client |
| `agent/prompts.py` | Planner and answer-writer prompts (catalog injected) |
| `agent/orchestrator.py` | Bounded agent loop: plan → validate → execute → answer, with retries |
| `agent/grounding.py` | Numeric-faithfulness check, template answers, clarification text |
| `rag/corpus/` | Methodology knowledge base (ZHVI, ZORI, coverage, scope) with source citations |
| `tools/knowledge.py` | BM25 retrieval over the corpus for `search_knowledge` |
| `api/main.py` | FastAPI: `POST /v1/ask`, `GET /v1/catalog`, `GET /health`, `GET /ready` |
| `ui/` | Streamlit UI (`app.py`), its API client (`client.py`), and display helpers (`view.py`) |
| `evaluation/` | Frozen eval set (200 cases), oracle, scorer, runner — see [evaluation/README.md](evaluation/README.md) |
| `scripts/run_eval.py` | Score a model backend (`oracle`, `stub`, `sagemaker`) on the eval set |
| `scripts/deploy_endpoint.py` | Deploy / check / delete the SageMaker TGI endpoint — see [docs/deployment.md](docs/deployment.md) |
| `scripts/smoke_endpoint.py` | Check a live endpoint against the decoding settings the agent relies on |
| `docs/evaluation.md` | Evaluation results so far (baseline v0, the next runs) |
| `training/` | Step 3 planner training data: phrase grammar, filters, train/dev split — see [training/README.md](training/README.md) |
| `scripts/build_training_data.py` | Build the training data and its report |
| `training/job/train.py` | SageMaker training job: LoRA on Qwen2.5-3B, completion-only loss, in-job merge |
| `scripts/launch_train.py` | Launch the training job from Studio — see [docs/training.md](docs/training.md) |

## Example

```python
from housing.db import HousingDB
from tools.validator import PlanValidator
from tools.operations import execute

db = HousingDB("data")
plan = {
    "metric": "zhvi",
    "state_filter": "CO",
    "start_month": "2025-01",
    "end_month": "2025-12",
    "operation": "rank",
    "rank_by": "pct_change",
    "limit": 5,
}
result = execute(PlanValidator(db).validate(plan), db)
print(result.summary["top"], result.warnings)
```

Data: [Zillow Research](https://www.zillow.com/research/data/), used for non-commercial coursework.
