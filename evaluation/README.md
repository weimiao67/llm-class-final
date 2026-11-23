# Evaluation set and runner

The frozen evaluation set measures how well a model *plans*. Numbers always come from trusted code,
so the question is whether the model picks the right tool and the right analysis. The design is in
§12 of the design doc.

## Files

| Path | Contents |
|---|---|
| `cases/v1.jsonl` | 200 hand-written cases, one JSON object per line |
| `cases/v1.1.jsonl` | v1 with four gold plans corrected to match the city/state policy (see `notes` in each) |
| `rescore.py` | Re-scores a saved run on a corrected case file, offline; only changed cases are re-scored |
| `cases/v1_holdout.json` | What Step 3 training data must not contain: eval plans (by meaning), cities, and questions |
| `holdout.py` | Builds the hold-out file; `Holdout.conflicts(question, plan)` is the check Step 3 runs |
| `cases.py` | Case schema (`EvalCase`) and loader |
| `oracle.py` | Model client that always emits the gold call, used to check the set and the scorer |
| `scoring.py` | Per-case scoring and aggregate metrics |
| `runner.py` | Runs cases through the real `Agent` and writes reports |
| `reports/<run-id>/` | `report.md`, `summary.json`, `results.jsonl` for each run |

## Case format

```json
{"id": "multi_city-002", "family": "multi_city",
 "question": "Rank Colorado cities by ZHVI growth in 2025.",
 "gold_call": {"tool": "analyze", "plan": {"metric": "zhvi", "operation": "rank",
   "state_filter": "CO", "start_month": "2025-01", "end_month": "2025-12", "rank_by": "pct_change"}},
 "alt_calls": [],
 "expected_response": "answer"}
```

- `gold_call` is the correct **first** tool call. `alt_calls` lists other calls that are equally
  correct, using the same tool (for example `change` vs `series` for "compare A and B").
- `expected_response` is how the turn should end: `answer`, `clarify` (ambiguous or unknown
  city), `no_data`, `unsupported`, or `out_of_scope`.
- Follow-up cases also carry `history` and `state`, the previous-turn context the client sends.
- A gold plan has a state only when the user wrote it. A state after a list ("Phoenix, Mesa,
  and Tempe, AZ") counts for every city in the list. Names that match one place in the data
  ("Seattle") resolve without a state. Names that match several places ("Atlanta" exists in 10
  states) must lead to a clarification, even for famous cities. The model must never add a state
  from its own knowledge.

| Family | Cases | What it tests |
|---|---:|---|
| single_city | 35 | series, change, and year-over-year for one city |
| extrema | 20 | highest and lowest month |
| multi_city | 30 | explicit city lists and statewide rankings |
| aggregate | 20 | avg, median, min, max, and count across cities |
| coverage | 10 | which months have data (including a city with no ZORI) |
| methodology | 15 | metric definitions, which should go to `search_knowledge` |
| follow_up | 20 | "what about rent?", "only the top 3", and similar follow-ups |
| ambiguous | 15 | ambiguous names, typos, and fictional cities, all of which should clarify |
| boundary | 25 | forecasts, missing fields, unimplemented operations, and SQL/code requests |
| injection | 10 | instructions embedded in the question |

## Metrics

| Metric | Meaning |
|---|---|
| Envelope valid | The first planner output parses as a tool call |
| Tool selection | The first call uses the gold tool |
| Response kind | The turn ends with `expected_response` |
| Plan match | The proposed plan has the same meaning as gold or an alt (resolved regions and effective period) |
| **Execution accuracy** | The executed result rows equal the rows from gold or an alt (primary metric) |
| Faithful model answer | The model's own prose passed the number check (a template fallback counts as a failure) |
| Turn success | Correct response kind and, for data answers, correct rows |
| Clarification via analyze | On clarification cases, the share where the model called `analyze` (the gold call) rather than asking on its own |

Scoring rule for clarification cases: any turn that ends in `clarify` counts as a success, including
a direct `respond(clarify)`, because the user still gets a question back. Only a clarification
from `analyze` lists the real candidates ("Atlanta exists in 10 states: GA, ID, …"). A model that
asks "which city?" whenever it is unsure therefore scores well on these cases, which is why the
report shows "Clarification via analyze" next to them.

Methodology cases are scored on tool selection alone unless the run uses `--knowledge`, which
loads `rag/corpus` so `search_knowledge` returns passages and the turn ends in an answer.

## Run

```bash
uv run python scripts/run_eval.py --model oracle   # must score 100%; checks the set itself
uv run python scripts/run_eval.py --model stub     # offline baseline
uv run python scripts/run_eval.py --model oracle --knowledge   # with the methodology corpus
uv run python scripts/run_eval.py --model sagemaker --endpoint <name> --model-id <label>
```

Re-score saved runs on a corrected case file, with no model calls:

```bash
uv run python scripts/rescore_eval.py --cases evaluation/cases/v1.1.jsonl evaluation/reports/*/
```

Use `--family extrema` or `--limit 20` for quick smoke runs. A `--model-id` with a slash (Hugging
Face ids) is made folder-safe in the run id; the report keeps the original id. Changing a case changes the benchmark,
so add new cases in a new file (`v2.jsonl`) rather than editing `v1.jsonl`.
