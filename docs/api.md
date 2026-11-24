# Agent API

FastAPI service in `api/main.py`. Interactive OpenAPI docs are served at `/docs` and the schema at
`/openapi.json` on every deployment (locally `http://localhost:8000/docs`).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/v1/ask` | API key | Answer one question (one agent turn) |
| `GET` | `/v1/catalog` | API key | Dataset version, coverage per metric, operations, sources, knowledge base |
| `GET` | `/health` | none | Liveness: 200 while the process is up and the dataset is loaded |
| `GET` | `/ready` | none | Readiness: 200 when the model endpoint is `InService`, otherwise 503 |

**Authentication.** When the server has `API_KEY` set (always on EC2), `/v1/*` requires the header
`X-API-Key: <key>`; a missing or wrong key gets **401**. `/health` and `/ready` are open so
health checks and the UI's status line work without the key.

## `POST /v1/ask`

### Request

```json
{
  "question": "Rank Colorado cities by ZHVI growth in 2025",
  "history": [],
  "state": {},
  "include_rows": false
}
```

| Field | Type | Limits | Meaning |
|---|---|---|---|
| `question` | string | 1–1,000 characters | The user's question |
| `history` | list of `{role, content}` | ≤ 20 messages, each ≤ 4,000 characters; `role` is `user` or `assistant` | Earlier turns, oldest first. The planner sees the last 6. |
| `state` | object | `metric`, `cities`, `state_filter`, `start_month`, `end_month`, `operation`; no other keys | The previous turn's `updated_state`, for follow-ups ("only since 2022") |
| `include_rows` | boolean | default `true` | `false` returns the artifact without its rows (the summary is still there) |

To hold a conversation, send each turn's question and answer back in `history`, and the
response's `updated_state` back as `state`. The Streamlit UI does exactly this.

### Response

The fields of every response:

| Field | Meaning |
|---|---|
| `kind` | `answer`, `clarify`, `unsupported`, `out_of_scope`, `no_data`, or `error` |
| `answer` | The text to show the user |
| `answer_source` | `model` (sampled answer that passed the number check), `model_regenerated` (greedy retry passed), `template` (written by code from the result), or `system` (fixed text: clarifications, refusals, errors) |
| `artifact` | For data answers: the result (below); otherwise `null` |
| `plan` | The last `AnalysisPlan` the model proposed this turn, or `null` |
| `sources` | For methodology answers: the retrieved passages (`doc_id`, `title`, `section`, `source_url`, `text`, `score`) |
| `trace` | The tool events of the turn: `step`, `tool`, `status` (`ok`, `retry`, `stop`, `error`), `duration_ms`, `detail` |
| `updated_state` | Conversation state to send with the next question |
| `warnings` | Warnings for the user (missing data, excluded cities, truncation) |
| `model_id`, `prompt_version`, `dataset_version` | What produced this answer |
| `latency_ms` | `model`, `tools`, and `total` milliseconds |

The `artifact` of a data answer:

| Field | Meaning |
|---|---|
| `operation`, `metric` | What was computed (`series`, `change`, `yoy_change`, `extrema`, `rank`, `aggregate`, `coverage`; `zhvi` or `zori`) |
| `rows` | Every result row (at most 5,000 in the response) |
| `rows_total`, `rows_truncated` | Total rows, and whether `rows` was cut (by the cap or `include_rows: false`) |
| `summary` | The compact result the answer was written from (per-city values, or the top of a ranking) |
| `regions` | The resolved cities: `region_id`, `city`, `state`, `county` |
| `period` | The months actually used |
| `sql` | The SQL `template` that ran and its bound `params` |
| `chart` | A chart hint (`type`, `x`, `y`, `series`) or `null` |
| `warnings`, `dataset_version` | As above |

### Example: a state ranking

```bash
curl -s http://localhost:8000/v1/ask -H "X-API-Key: $KEY" -H 'content-type: application/json' \
  -d '{"question": "Rank Colorado cities by ZHVI growth in 2025", "include_rows": false}'
```

Response (shortened; produced with the offline stub model, so `answer` is the code-written
template. With the LoRA endpoint, `answer` is the model's prose and `answer_source` is `model`):

```json
{
  "kind": "answer",
  "answer": "ZHVI ranking by pct_change (333 cities): 1. Telluride, CO (+8.9%, $2,144,201); 2. Stratton, CO (+8.7%, $207,064); …",
  "answer_source": "template",
  "artifact": {
    "operation": "rank",
    "metric": "zhvi",
    "rows": [],
    "rows_total": 333,
    "rows_truncated": true,
    "summary": {
      "rank_by": "pct_change", "order": "desc", "eligible": 333, "excluded": 7,
      "window": {"start_month": "2025-01-01", "end_month": "2025-12-01"},
      "top": [
        {"rank": 1, "label": "Telluride, CO", "region_id": "50002", "county": "San Miguel County",
         "start_value": 1968086.27, "end_value": 2144201.19, "change": 176114.93, "pct_change": 8.95}
      ]
    },
    "regions": [],
    "period": {"start_month": "2025-01-01", "end_month": "2025-12-01"},
    "sql": {"template": "WITH s AS ( SELECT … FROM observations WHERE metric = ? AND state = ? AND month BETWEEN ? AND ? ) …",
            "params": ["zhvi", "CO", "2025-01-01", "2025-12-01"]},
    "chart": {"type": "bar", "x": "label", "y": "pct_change"},
    "warnings": [
      "7 city(ies) excluded for lacking data over the full window Jan 2025–Dec 2025: Aguilar, CO, …",
      "Showing top 10 of 333; all rows are in the table."
    ],
    "dataset_version": "23ccd46a4560"
  },
  "plan": {"metric": "zhvi", "cities": [], "state_filter": "CO", "start_month": "2025-01",
           "end_month": "2025-12", "operation": "rank", "aggregate": null, "rank_by": "pct_change",
           "order": "desc", "limit": 10},
  "sources": [],
  "trace": [
    {"step": 1, "tool": "analyze", "status": "ok", "duration_ms": 24.8, "detail": "rank, 333 rows"},
    {"step": 2, "tool": "answer_writer", "status": "ok", "duration_ms": 0.0, "detail": "template fallback"}
  ],
  "updated_state": {"metric": "zhvi", "cities": [], "state_filter": "CO", "start_month": "2025-01",
                    "end_month": "2025-12", "operation": "rank"},
  "warnings": ["7 city(ies) excluded …", "Showing top 10 of 333; all rows are in the table."],
  "model_id": "stub",
  "prompt_version": "planner-v2",
  "dataset_version": "23ccd46a4560",
  "latency_ms": {"model": 0.0, "tools": 24.8, "total": 25.6}
}
```

The stub's trace also shows two `answer_writer` retries (the stub writes no prose); they are
left out above.

### Example: a clarification

```json
{
  "kind": "clarify",
  "answer": "Several places match \"Oakwood\": Oakwood, OH (Cuyahoga County), Oakwood, OH (Montgomery County), Oakwood, OH (Paulding County). Which one do you mean?",
  "answer_source": "system",
  "artifact": null,
  "trace": [{"step": 1, "tool": "analyze", "status": "stop", "duration_ms": 0.1, "detail": "ambiguous_city"}]
}
```

The plan schema accepts a county (`cities[].county`), and the validator uses it to pick one of the
matches. **The model wasn't trained or evaluated on resolving a clarification**, though: no
training example or eval case replies to one ("the one in Montgomery County") or names a county
in the question. Whether a follow-up resolves the ambiguity is untested; see
[model.md](model.md), "Known limitations".

### Response kinds and what causes them

| `kind` | Caused by |
|---|---|
| `answer` | Data answer (`analyze` ran) or methodology answer (`search_knowledge` found passages) |
| `clarify` | The model asked, or the validator found an ambiguous or unknown city (`ambiguous_city`, `city_not_found` with suggestions) |
| `unsupported` | The model declined: a field, operation, or kind of request the data can't serve (mortgage rates, SQL, clustering) |
| `out_of_scope` | The model declined a forecast, advice, or modeling request, usually offering the historical alternative |
| `no_data` | The validator stopped the plan for a reason a retry can't fix: no data for it (`no_data`, e.g. no ZORI for that city) or `capability_not_implemented`. Also when no methodology passage matched. The `answer` is the validator's message. |
| `error` | The turn couldn't finish: the plan was still invalid after 2 retries, the 60 s budget ran out, or the model or knowledge base was unavailable |

The tool errors behind these (`invalid_plan`, `ambiguous_city`, `city_not_found`, `no_data`,
`capability_not_implemented`) are defined in `tools/schemas.py`; only `invalid_plan` is sent back
to the model for a retry.

## HTTP status codes

| Code | When |
|---|---|
| 200 | Every completed turn, including clarifications, refusals, and `kind: error` |
| 401 | `/v1/*` without the right `X-API-Key` (`{"detail": "missing or invalid X-API-Key"}`) |
| 422 | Request doesn't match the schema, e.g. an empty question (`{"detail": [{"type": "string_too_short", "loc": ["body", "question"], …}]}`) |
| 503 | `/ready` only: the model endpoint isn't `InService` |

## `GET /v1/catalog`

```json
{
  "dataset_version": "23ccd46a4560",
  "tool_protocol_version": 1,
  "metrics": {
    "zhvi": {"first_month": "2000-03-01", "last_month": "2026-10-01", "regions": 24197, "observations": 4968547},
    "zori": {"first_month": "2015-01-01", "last_month": "2026-10-01", "regions": 4405, "observations": 226489}
  },
  "operations": ["aggregate", "change", "coverage", "extrema", "rank", "series", "yoy_change"],
  "sources": [{"metric": "zhvi", "filename": "City_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv", "series_variant": "…", "sha256": "…"}, "…"],
  "knowledge": {"version": "…", "documents": [["zhvi", "Zillow Home Value Index (ZHVI)", "https://www.zillow.com/research/…"], "…"]}
}
```

## `GET /ready`

```json
{"dataset_version": "23ccd46a4560", "model_id": "final-wm-qwen-lora",
 "model": {"endpoint": "final-wm-qwen-lora", "status": "InService"}, "status": "ready"}
```

When the endpoint can't be described, `model` is `{"status": "unreachable", "error": "<AWS error
code>"}`: `ValidationException` means the endpoint doesn't exist, `AccessDeniedException` that the
app's role may not call it.
