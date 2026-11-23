# Step 3 training data

`training/` generates the supervised fine-tuning data for the **planner** step of
Qwen2.5-3B-Instruct. Each example pairs a question (plus any history and conversation state)
with the exact tool call the planner should emit. The design is in §11 of the design doc, and the
baseline failures it targets are in [docs/evaluation.md](../docs/evaluation.md).

## How examples are made

1. **Templates** (`templates.py`, 37 of them) build one example each. The question comes from a
   **phrase grammar** (`grammar.py`): each sentence shape has interchangeable parts (openers,
   metric nouns and modifiers, period and operation phrasings) expanded with a seeded RNG, plus
   light noise (casing, punctuation, "yoy"). The gold call is built from the same slot values, so
   it is correct by construction.
2. **Slot values** (`pools.py`) come from the real dataset. Eval hold-out city names are excluded
   in every state. "City, ST" is used only when it names one place, and a bare "City" only when
   the name is unique in the data, so gold plans never add a state the user didn't write. Year
   ranges come from the data's coverage.
3. **Filters** (`build.py`) reject a candidate if:
   - its gold call doesn't run as intended through the real validator and tools (an answer with
     rows, or a clarification for ambiguous or unknown cities);
   - `evaluation.holdout.Holdout.conflicts()` finds the same plan meaning, an eval city, or an
     eval question;
   - it is a near-duplicate of an eval question (character 3-gram Jaccard ≥ 0.6);
   - it duplicates another generated example.
4. **Format:** messages are built with `agent.prompts.planner_messages`, exactly as at inference.
   Retry examples add the rejected call and the agent's real retry feedback
   (`retry_message(invalid_call_payload(...))`). The target is the final assistant turn, written
   with `canonical_json`: defaults dropped, keys in the order constrained decoding generates them.

| Scenario | Share | What it teaches |
|---|---:|---|
| standard | 25% | single-city change, series, extrema, coverage, and year-over-year, with period conventions |
| scope | 20% | `state_filter` for statewide questions vs. city lists; a state after a list applies to all |
| clarify | 15% | ambiguous names, multi-state names without a state, typos, fictional places |
| refusal | 15% | `unsupported` (missing fields or operations, SQL/code, injection) vs. `out_of_scope` (forecasts, advice, modeling); translating clear SQL intent; ignoring injected instructions |
| follow_up | 15% | switching metric, period, or city; adding a city; changing operation or ranking; forecast follow-ups |
| retry | 10% | fixing a rejected call, or switching to `unsupported` when the data can't answer |

## Train/dev split

A template's **last** sentence shape is reserved for dev (about 12% of examples). Dev questions
therefore use phrasings the model never trained on, while every concept is still trained. Use dev
for checkpoint selection and any further prompt tuning. The v1 eval set stays the final test.

## Run

```bash
uv run python scripts/build_training_data.py          # 3,000 examples, seed 13 (about 25 s)
```

- Data: `data/training/<version>/{train,dev}.jsonl` and `manifest.json`. This is git-ignored and
  uploaded to S3 for training in Step 3b.
- Report: `training/reports/<version>/report.md` (composition, rejection reasons, and wording
  overlap with the eval), `stats.json`, and `samples.md` (30 examples per scenario, for review).

The version is a hash of the seed, size, dataset version, prompt version, and generator code, so
the same inputs always give the same dataset.

Training itself (Step 3b) runs `training/job/train.py` as a SageMaker job; see
[docs/training.md](../docs/training.md).
