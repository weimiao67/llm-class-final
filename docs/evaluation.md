# Evaluation results

All runs use the frozen 200-case set `evaluation/cases/v1.jsonl` (see
[evaluation/README.md](../evaluation/README.md) for the cases and metrics) and dataset version
`23ccd46a4560`. Each run's full report is under `evaluation/reports/<run-id>/`.

## Summary

> **Methodology cases measure tool choice.** Every run below was made before the knowledge base
> existed (Step 4a), so the 15 methodology cases were scored on choosing `search_knowledge`, not
> on the answer. "Methodology 100%" means the model chose the right tool every time; its full
> answers from the knowledge base haven't been scored yet. See
> [Methodology answers](#methodology-answers-not-yet-scored) at the end.

| Run | Model | Prompt | Decoding | Turn success | Execution accuracy | Report |
|---|---|---|---|---:|---:|---|
| v0 | Llama-3.2-3B-Instruct (base) | planner-v1 | greedy, structure-only schema | 31.0% | 16.0% | [`20261122-071857-…`](../evaluation/reports/20261122-071857-llama-3.2-3b-instruct-base/report.md) |
| v1 | Llama-3.2-3B-Instruct (base) | planner-v2 | greedy, scoped schema + state codes | 37.5% | 27.5% | [`20261123-064147-…`](../evaluation/reports/20261123-064147-llama-3.2-3b-instruct-planner-v2/report.md) |
| v1-qwen | Qwen2.5-3B-Instruct (base) | planner-v2 | same as v1 | 55.5% | 51.1% | [`20261123-075101-…`](../evaluation/reports/20261123-075101-qwen2.5-3b-instruct-planner-v2/report.md) |
| v2-lora | **Qwen2.5-3B + LoRA** (data `93a8b1a171`, 2 epochs) | planner-v2 | same as v1 | **84.0%** | **84.0%** | [`20261123-171002-…`](../evaluation/reports/20261123-171002-qwen2.5-3b-lora-93a8b1a171/report.md) |
| v2-lora, no constraint | Qwen2.5-3B + LoRA | planner-v2 | greedy, **no** schema | 84.0% | 84.0% | [`20261123-171407-…`](../evaluation/reports/20261123-171407-qwen2.5-3b-lora-93a8b1a171-unconstrained/report.md) |
| v3-lora | **Qwen2.5-3B + LoRA** (data v2 `f261a5f4d7`, 1 epoch) | planner-v2 | same as v1 | **92.5%** | **89.3%** | [`20261123-191702-…`](../evaluation/reports/20261123-191702-qwen2.5-3b-lora-f261a5f4d7/report.md) |
| v3-lora, no constraint | Qwen2.5-3B + LoRA (data v2) | planner-v2 | greedy, **no** schema | 92.5% | 90.1% | [`20261123-192137-…`](../evaluation/reports/20261123-192137-qwen2.5-3b-lora-f261a5f4d7-unconstrained/report.md) |

## Model selection

The design (§9.1) compares two model families before fine-tuning one.

| Candidate | Result |
|---|---|
| `meta-llama/Llama-3.2-3B-Instruct` | Runs on TGI 3.3.6; runs v0 and v1 below |
| `microsoft/Phi-4-mini-instruct` (3.8B) | **Not servable on TGI 3.3.6.** The shard fails at startup with `size of tensor a (48) must match the size of tensor b (64)`. Phi-4-mini applies rotary position embeddings to only 75% of each 128-dimension head (`partial_rotary_factor: 0.75`, so 48 frequency pairs), but TGI's Phi-3 code assumes the full head (64 pairs). Serving it would need the vLLM-based LMI container, a separate deploy path and client, so it was dropped. |
| `Qwen/Qwen2.5-3B-Instruct` | Second family instead: same size as Llama-3.2-3B, standard `Qwen2ForCausalLM` architecture, not gated. Released under the Qwen Research License (fine for coursework). **Selected for fine-tuning** (see v1-qwen below). |

## v0: baseline, Llama-3.2-3B-Instruct, planner-v1

| Metric | Result |
|---|---|
| Envelope valid (first output) | 53.5% (107/200) |
| Tool selection (first call) | 41.5% (83/200) |
| Plan match | 15.4% (24/156) |
| **Execution accuracy** | **16.0% (21/131)** |
| Faithful model answer | 90.0% (45/50) |
| Turn success | 31.0% (62/200) |
| Latency p50 / p95 | 1.3 s / 2.5 s |

The model is fast and rarely invents numbers in its answers, but it plans poorly. Three interface
problems explain most of the 138 failures:

1. **Scope.** 93 first outputs failed validation, most because the plan set both or neither of
   `cities` and `state_filter`. The decoding schema allowed both, because only Pydantic enforced
   "exactly one".
2. **Retry.** After a validation error, the model usually passed the error message on to the user
   as an `unsupported` reply (70 cases) instead of fixing the plan.
3. **Tool choice.** 10 data questions went to `search_knowledge`, and 9 went to `respond`.

**Caveat on v0's boundary and injection scores:** 5 of the 19 successes on cases that expect
`respond` (boundary-008 bedrooms, boundary-011 mortgage rates, boundary-016 Gini, boundary-017
standard deviation, and injection-004 admin dump) were accidental. The model tried `analyze`, the
plan was rejected, and the relayed error happened to be scored as `unsupported`. Without those, v0
scores 14/29 on respond-expected cases. A lower score on these families in v1 therefore doesn't by
itself mean a regression.

## v1: planner-v2 (same model)

Changes from v0:

- The decoding schema splits the plan into city-scoped and state-scoped variants, so the grammar
  enforces "exactly one" scope, and state fields are limited to the 51 state codes.
- The retry feedback tells the model to fix the call, or to switch to `respond(unsupported)` when
  the data can't answer the question, and never to relay the error.
- The prompt states when to use each tool and the scope rule.

| Metric | v0 | v1 |
|---|---:|---:|
| Envelope valid (first output) | 53.5% | **79.0%** |
| Tool selection (first call) | 41.5% | **69.5%** |
| Response kind | 42.0% | **71.0%** |
| Plan match | 15.4% | 26.3% |
| **Execution accuracy** | 16.0% | **27.5%** |
| Faithful model answer | 90.0% (45/50) | 63.6% (75/118) |
| Turn success | 31.0% | **37.5%** |
| Latency p50 / p95 | 1.3 s / 2.5 s | 1.6 s / 3.4 s |

The interface fixes worked: the model now mostly picks the right tool and produces valid calls.
Methodology reached 100%, extrema 100% tool selection, and aggregate success went from 5% to 40%.
**Plan content is now the bottleneck.** Of the 77 data questions with a wrong plan (a plan can
have several problems):

| Problem | Plans | Example |
|---|---:|---|
| Scope: a city's state used as `state_filter` | 38 | "Miami, FL" → `state_filter: "FL"` (all Florida cities) |
| Period: end month invented | 37 | "from 2019 to 2024" → `2019-01` to `2024-10`. The "-10" is copied from the catalog's last month (2026-10). |
| Operation for "which cities…" questions | 26 | "growth" → `yoy_change`/`change` instead of `rank`; "highest values in Oregon" → `extrema` |
| `rank_by`: "growth" → `change` instead of `pct_change` | 17 | "Rank Colorado cities by ZHVI growth" |

**Faithfulness** dropped because the model now writes many more answers (118 vs. 50), and because
of a bug in the check. 70 of the 187 numbers it flagged (37%) come from the result's own warning
text, which the check didn't count as evidence. That bug is fixed after this run, so v1
understates faithfulness.

**Caveat on tuning:** v0 → v1 changes were designed from failures on this same eval set. They are
general (schema shape, retry wording, tool rules), but further prompt iteration against v1 would
overfit the benchmark. Later prompt work should be tuned on a separate dev set (e.g. held-out
synthetic data from Step 3), keeping v1 as the final test.

## v1-qwen: Qwen2.5-3B-Instruct, planner-v2 (model-family comparison)

Same prompt, schema, and eval as Llama v1, with no Qwen-specific tuning.

| Metric | Llama v1 | Qwen v1 |
|---|---:|---:|
| Envelope valid (first output) | 79.0% | **94.0%** |
| Tool selection (first call) | 69.5% | **86.0%** |
| Response kind | **71.0%** | 65.0% |
| Plan match | 26.3% | **48.7%** |
| **Execution accuracy** | 27.5% | **51.1%** |
| Faithful model answer | ~77% (estimated, see below) | **88.8%** |
| Turn success | 37.5% | **55.5%** |
| Latency p50 / p95 | 1.6 s / 3.4 s | **1.2 s / 2.9 s** |
| Mean model calls per turn | 2.23 | **1.6** |

| Family (turn success) | Llama v1 | Qwen v1 |
|---|---:|---:|
| single_city | 17.1% | **82.9%** |
| extrema | 20.0% | **90.0%** |
| ambiguous | 40.0% | **93.3%** |
| follow_up | 50.0% | **60.0%** |
| coverage | 20.0% | **50.0%** |
| aggregate | **40.0%** | 20.0% |
| multi_city | **23.3%** | 20.0% |
| boundary | **56.0%** | 36.0% |
| injection | 30.0% | 30.0% |
| methodology | **100.0%** | 73.3% |

**Decision: fine-tune Qwen2.5-3B-Instruct in Step 3.** The 23.6-point execution-accuracy gap is
well outside the noise (about ±8 points at 95% confidence with 131 scored cases), and Qwen is also
faster and needs fewer model calls. Its LoRA target modules use the same names as Llama's
(`q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`), so the A5/A6
training recipe carries over.

Qwen's remaining failures are systematic, which suits supervised fine-tuning:

1. **City lists instead of the state filter.** For "Rank Colorado cities…" it lists cities from its
   own knowledge without states (`Denver, Colorado Springs, Aurora`) instead of setting
   `state_filter: "CO"`. Each bare name is ambiguous, so the turn ends in a clarification (23 of the
   multi-city and aggregate failures). It also drops a state written after a list, over-applying
   the "never add a state" rule.
2. **Refusal kind.** Missing fields (mortgage rates, home sales) get `out_of_scope` instead of
   `unsupported`. The refusal is still right; only the label is wrong.
3. **Analyzing instead of declining.** "Should I buy a house in Miami?" and "Cluster California
   cities" go to `analyze` and then stop at the ambiguous-city check.

**Faithfulness note:** the Qwen run used the fixed grounding check (warning text counts as
evidence). Llama v1 was scored before the fix. Re-checking its saved flagged numbers gives about
77% (91/118, at most 80%) instead of the reported 63.6%.

## v2-lora: Qwen2.5-3B-Instruct + LoRA (Step 3)

Training (`training/job/train.py`, data `93a8b1a171`: 2,643 train / 357 dev):

| Setting | Value |
|---|---|
| LoRA | r 16, alpha 32, all projections |
| Learning rate | 2e-4, cosine |
| Epochs | 2 |
| Batch | 16 per step |
| Loss | final tool call only |
| Instance | `ml.g5.xlarge` |
| Training time | 73.5 min |
| Peak GPU memory | 8.5 GB |

Training loss fell from 0.359 to 0.0036. Dev loss was 0.0373 after epoch 1 and 0.0376 after
epoch 2: flat, so the second epoch memorized training examples rather than generalizing better.
One epoch would likely match it.

| Metric | Qwen base | **Qwen + LoRA** | LoRA, no constraint |
|---|---:|---:|---:|
| Envelope valid (first output) | 94.0% | **99.5%** | 99.5% |
| Tool selection (first call) | 86.0% | **93.5%** | 93.5% |
| Response kind | 65.0% | **87.5%** | 87.0% |
| Plan match | 48.7% | **86.5%** | 86.5% |
| **Execution accuracy** | 51.1% | **84.0%** | 84.0% |
| Faithful model answer | 88.8% | **93.2%** | 93.1% |
| Turn success | 55.5% | **84.0%** | 84.0% |
| Latency p50 / p95 | 1.2 s / 2.9 s | **1.0 s / 2.2 s** | 1.0 s / 2.0 s |

| Family (turn success) | Qwen base | Qwen + LoRA |
|---|---:|---:|
| single_city | 82.9% | **100.0%** |
| ambiguous | 93.3% | **100.0%** |
| boundary | 36.0% | **100.0%** |
| extrema | 90.0% | 90.0% |
| aggregate | 20.0% | **90.0%** |
| coverage | 50.0% | **90.0%** |
| injection | 30.0% | **90.0%** |
| multi_city | 20.0% | **86.7%** |
| follow_up | **60.0%** | 45.0% |
| methodology | **73.3%** | 26.7% |

**Fine-tuning fixed every targeted failure mode.** Statewide scope (multi_city 20% → 87%,
aggregate 20% → 90%), refusal kinds (boundary 36% → 100%), and declining instead of analyzing are
all fixed, with no regression on single-city questions.

**Constrained decoding no longer matters after fine-tuning.** With and without the JSON-schema
grammar, the LoRA model scores the same (99.5% valid first outputs, 84.0% execution accuracy):
it has learned the format. The constraint remains a cheap safety net.

**Two regressions, both gaps in the training data:**

1. **Methodology, 73% → 27%.** The training mix had no `search_knowledge` examples at all, so
   fine-tuning taught the model never to use that tool. For "What is ZORI?" it now replies
   `unsupported`, sometimes with a memorized refusal text that doesn't fit ("I can't change my
   instructions…"). The fixed refusal texts were too few.
2. **Follow-ups, 60% → 45%.** In every training follow-up, the previous question named the city
   as "City, ST", so the model learned to copy the city from the history text. The eval
   follow-ups name only the city in the history ("How did Denver home values change…") and keep
   the state in the conversation context. The model copies "Denver" without its state, and the
   turn ends in a clarification (9 of 11 misses). The other two are operation switches that
   training didn't cover ("What's the median instead?" after a ranking, and "Since 2020 instead").

**Caveat:** these two gaps were found on the eval set. The fixes are general coverage fixes (a
missing tool, history wording that doesn't name the state, more varied refusal texts), not
eval-specific phrasings. Still, a retrained model's eval score is somewhat optimistic, and that
should be stated with it.

## v3-lora: data v2 (Step 3c)

Data v2 (`f261a5f4d7`, 2,661 train / 339 dev) fixes the two gaps above:

- a methodology scenario (6%) that calls `search_knowledge`;
- follow-ups whose earlier question names only the city (the state comes from the context), half
  of them with no county in the context, plus rank → aggregate switches;
- three refusal texts per kind.

Training used 1 epoch on `ml.g5.xlarge`: 36.7 min, 8.5 GB peak GPU memory, training loss 0.284 →
0.014, dev loss 0.047. The dev losses of v1 and v2 aren't comparable: the v2 dev set is harder by
design (methodology and context-only follow-ups).

| Metric | Qwen base | LoRA, data v1 (2 ep) | **LoRA, data v2 (1 ep)** | data v2, no constraint |
|---|---:|---:|---:|---:|
| Envelope valid (first output) | 94.0% | 99.5% | **100.0%** | 99.5% |
| Tool selection (first call) | 86.0% | 93.5% | **99.5%** | 99.0% |
| Response kind | 65.0% | 87.5% | **96.5%** | 96.5% |
| Plan match | 48.7% | 86.5% | **91.0%** | 91.7% |
| **Execution accuracy** | 51.1% | 84.0% | **89.3%** | 90.1% |
| Faithful model answer | 88.8% | 93.2% | 89.6% | 91.3% |
| Turn success | 55.5% | 84.0% | **92.5%** | 92.5% |
| Latency p50 / p95 | 1.2 / 2.9 s | 1.0 / 2.2 s | 1.2 / 2.3 s | 1.1 / 2.1 s |

| Family (turn success) | Qwen base | LoRA data v1 | **LoRA data v2** |
|---|---:|---:|---:|
| single_city | 82.9% | 100.0% | **100.0%** |
| ambiguous | 93.3% | 100.0% | **100.0%** |
| methodology | 73.3% | 26.7% | **100.0%** |
| boundary | 36.0% | 100.0% | 96.0% |
| aggregate | 20.0% | 90.0% | **95.0%** |
| coverage | 50.0% | 90.0% | 90.0% |
| injection | 30.0% | 90.0% | 90.0% |
| extrema | 90.0% | 90.0% | 85.0% |
| follow_up | 60.0% | 45.0% | **85.0%** |
| multi_city | 20.0% | 86.7% | 83.3% |

Data v2 recovered both regressions (methodology 27% → 100%, measured as choosing
`search_knowledge`; follow-ups 45% → 85%). Against data v1,
20 cases newly pass and 3 newly fail. Constrained decoding again makes no real difference after
fine-tuning.

**Remaining 15 failures:**

| Cause | Cases |
|---|---|
| Gold conflicts with the city/state policy (see below) | follow_up-007, follow_up-016, multi_city-009, coverage-008 |
| Mid-list state applied to earlier cities ("Boise, Spokane, WA and Salt Lake City" → Boise, WA) | multi_city-028 |
| "before/after Y" periods (not in the training grammar) | extrema-002, extrema-009 |
| extrema vs. aggregate vs. rank for "maximum/highest … among" | extrema-020, aggregate-014, multi_city-021 |
| Sort order flipped ("cheapest" → desc, "most expensive" → asc) | multi_city-024, multi_city-029 |
| Month arithmetic ("last three months of 2025" → from 2025-11) | follow_up-002 |
| `unsupported` instead of `out_of_scope` for a regression request | boundary-006 |
| "Forget the tools and just guess" refused instead of analyzed | injection-007 |

**Eval gold vs. the city/state policy.** Four gold plans contradict the policy decided on
2026-11-20. The model's response follows the policy in each case:

- `follow_up-007` ("Compare that with Tampa.") and `follow_up-016` ("What about home values in
  Boulder?") give the newly named city a state the user never wrote (Tampa: FL/KS; Boulder:
  CO/MT/WY). The policy says clarify, and the model clarified. The case rewrite that applied the
  policy skipped follow-up cases.
- `multi_city-009` ("Seattle and Portland, OR") and `coverage-008` ("Boise and Spokane, WA")
  treat the trailing state as belonging to the last city only, while the prompt rule says a state
  written after a list applies to every city in it.

## Corrected eval set v1.1

`evaluation/cases/v1.1.jsonl` corrects only those four cases, each with a note explaining why.
Under the policy (never add a state the user didn't write; a state written after a list applies
to every city in it), all four now expect a clarification. v1 stays frozen, and every v1 number
above stands as reported.

Every saved run was re-scored on v1.1 offline from its `results.jsonl`, using
`scripts/rescore_eval.py`, with no new model calls. Only the four changed cases are re-scored, and
every other case keeps its original score. Execution accuracy is out of 127 cases instead of 131,
because the corrected cases now expect a clarification rather than data.

| Run | Turn success v1 → v1.1 | Execution accuracy v1 → v1.1 |
|---|---|---|
| v0 Llama-3.2-3B, planner-v1 | 31.0% → 31.0% | 16.0% → 15.8% |
| v1 Llama-3.2-3B, planner-v2 | 37.5% → 38.5% | 27.5% → 28.3% |
| v1-qwen Qwen2.5-3B base | 55.5% → 54.5% | 51.1% → 50.4% |
| v2-lora (data v1, 2 epochs) | 84.0% → 86.0% | 84.0% → 86.6% |
| v2-lora, no constraint | 84.0% → 86.0% | 84.0% → 86.6% |
| **v3-lora (data v2, 1 epoch)** | **92.5% → 94.5%** | **89.3% → 92.1%** |
| v3-lora, no constraint | 92.5% → 93.5% | 90.1% → 92.1% |

The corrections don't just favor the fine-tuned models: base Qwen loses a point, because it had
"passed" these cases by adding states the user never wrote. `multi_city-028` ("Boise, Spokane, WA
and Salt Lake City", where the state sits mid-list) is left unchanged, since reading it is
genuinely ambiguous.


## Found in the live demo (Step 4c)

Running the demo script through the deployed app (EC2 + the data-v2 endpoint) turned up one miss
the eval set doesn't cover: switching the metric right after a **state ranking**.

| Conversation (data-v2 LoRA, live) | Result |
|---|---|
| "Rank Colorado cities by ZHVI growth in 2025" → "What about rent?" | `respond: unsupported` ("I can't change the analysis") instead of the ZORI ranking |
| same ranking → "What about rent growth for the same cities and year?" | correct ZORI ranking (52 cities) |
| "What was Mead, CO's highest ZHVI month in 2025?" → "What about rent there?" | correct plan; Mead has no ZORI data, so it reports that |

Why: in data v2, 50 follow-ups switch the metric relative to the previous turn's context, and all
50 follow a single-city question (`change` or `series`). None follow a state ranking: all 59
follow-ups to a state ranking keep the metric. The eval set has the same blind spot: both of its
"rent" follow-ups (`follow_up-001`, `follow_up-020`) follow a single-city question, so the 85%
follow-up score doesn't measure this case.

The demo uses the explicit phrasing. Fixing the model would need metric-switch follow-ups after
rankings and aggregates in the training data, with new eval cases for them (v1 stays frozen).

## Methodology answers: not yet scored

The runs above score methodology cases only on choosing `search_knowledge` (see the note at the
top). The answer path itself has this evidence so far:

- The **oracle** run with the knowledge base (`--knowledge`) answers all 15 methodology cases
  with sources. It uses the gold calls, so it tests retrieval and the answer path, not the model.
- **Retrieval for the model's own queries:** running the 15 queries the data-v2 model produced
  through the BM25 index, 14 retrieve a relevant section in the top 3 (nearly always first). The
  miss is a bad query, not bad retrieval: for "Does ZORI include single-family homes?" the model
  searched `ZORI sale price vs rent`, so "Housing types in ZORI" isn't retrieved.
- **Live demo:** "What is ZORI and how is it smoothed?" was answered correctly, with sources, by
  the data-v2 model on the deployed app.

To score the full answers, run the eval with `--knowledge` against the endpoint
(`scripts/run_eval.py --model sagemaker --endpoint final-wm-qwen-lora --knowledge ...`).

