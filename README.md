# Housing Market AI Analyst

A small language model plans analyses of Zillow city-level home values (ZHVI) and rents (ZORI);
trusted code validates each plan, compiles it to parameterized DuckDB SQL, and computes the
results deterministically. The model never writes SQL and never supplies the numbers.

> Status: week 2 in progress — agent loop, SageMaker client, and API work end to end with the
> stub model. Next: evaluation set, endpoint deployment, baseline results. UI and RAG are week 4.

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

curl -s localhost:8000/health
curl -s localhost:8000/v1/ask -H 'content-type: application/json' \
    -d '{"question": "Rank Colorado cities by ZHVI growth in 2025", "include_rows": false}'
```

Interactive API docs: <http://localhost:8000/docs>. Set `API_KEY` to require an `X-API-Key` header.

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
| `api/main.py` | FastAPI: `POST /v1/ask`, `GET /v1/catalog`, `GET /health` |

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
