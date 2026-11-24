# Model: the fine-tuned planner

The planner is **Qwen2.5-3B-Instruct with a LoRA adapter merged into its weights**, trained on
3,000 synthetic examples that were each checked against the real data before training. It is
served from a SageMaker TGI endpoint (`final-wm-qwen-lora`). The same model also writes the final
answer prose; it was trained only on planning.

| | Base Qwen2.5-3B | **Fine-tuned (data v2)** |
|---|---:|---:|
| Execution accuracy (eval v1, 131 data cases) | 51.1% | **89.3%** |
| Turn success (all 200 cases) | 55.5% | **92.5%** |
| Valid first output | 94.0% | **100.0%** |
| Planner retries in 200 cases | 25 | **0** |
| Latency p50 / p95 | 1.2 / 2.9 s | 1.2 / 2.3 s |

Full results, per-family scores, and error analysis: [evaluation.md](evaluation.md).

## Choosing the base model

Two 3B-class families were compared on the same prompt and eval set before any training
(details in [evaluation.md](evaluation.md), "Model selection"):

| Candidate | Result |
|---|---|
| Llama-3.2-3B-Instruct | 27.5% execution accuracy with the improved prompt (16.0% with the first) |
| Phi-4-mini-instruct (3.8B) | Not servable on TGI 3.3.6: its partial rotary embedding (48 of 64 frequency pairs) doesn't match TGI's Phi-3 code |
| **Qwen2.5-3B-Instruct** | **51.1%**, fewer model calls, faster. Selected. |

The base model's failures were systematic, which made it a good fit for supervised fine-tuning:
statewide questions answered with a guessed city list instead of `state_filter`, the wrong refusal
kind, and analyzing questions it should decline.

## Training data

The data is generated, not collected: a **phrase grammar** writes each question, and the gold tool
call is built from the same slot values, so it is correct by construction. Every candidate then
goes through the project's own validator and tools; only examples whose call does what it should
on the real data are kept. Design and code: [training/README.md](../training/README.md).

| Step | What it does |
|---|---|
| Templates | 40 templates in 7 scenarios, from single-city changes to retries after a rejected call |
| Slot values | Real city names and coverage from the dataset. Eval hold-out cities are excluded everywhere; "City, ST" is used only when it names one place. |
| Execution filter | The gold call must run through the real validator and operations and give the intended outcome (rows, or a clarification for ambiguous names) |
| Leakage filters | No plan, city, or question from the eval hold-out; no question within 0.6 character-3-gram Jaccard of an eval question |
| Format | Messages built with the inference-time prompt code; target is the canonical JSON tool call |

**Data v2** (`f261a5f4d7`, deterministic, seed 13): 3,000 examples, 2,661 train / 339 dev. 317
candidates were rejected along the way:

| Rejection reason | Count |
|---|---:|
| Plan validated but returned no result | 149 |
| Near-duplicate of an eval question | 74 |
| Duplicate of another example | 35 |
| Template couldn't build a valid example from the drawn slots | 26 |
| Validator found no data for that city and metric | 17 |
| Eval hold-out question | 9 |
| Eval hold-out plan | 7 |

| Scenario | Examples | Teaches |
|---|---:|---|
| standard | 690 | single-city series, change, extrema, coverage, year-over-year |
| scope | 570 | `state_filter` for statewide questions vs. city lists |
| follow_up | 480 | switching period, city, operation, or (after a city question) metric |
| clarify | 420 | ambiguous names, multi-state names without a state, typos, fictional places |
| refusal | 420 | `unsupported` vs. `out_of_scope`, SQL requests, injected instructions |
| retry | 240 | fixing a call the validator rejected |
| methodology | 180 | `search_knowledge` for questions about how the indexes work |

The dev split uses each template's last sentence shape, so dev questions use phrasings the model
never trained on. The closest training question to any eval question has a 3-gram similarity of
0.597 (median 0.275).

## LoRA training

`training/job/train.py`, run as a SageMaker training job ([training.md](training.md)):

| Setting | Value |
|---|---|
| Method | LoRA with TRL `SFTTrainer`, bf16 |
| Rank / alpha / dropout | 16 / 32 / 0.05 |
| Target modules | all attention and MLP projections (`q,k,v,o,gate,up,down_proj`) |
| Loss | final assistant turn only (the tool call), via completion-only loss |
| Learning rate | 2e-4, cosine schedule, 3% warmup |
| Batch | 4 × 4 gradient accumulation = 16 per step |
| Epochs | 1 (a 2-epoch run on data v1 had flat dev loss: 0.0373 → 0.0376) |
| Max length | 2,048 tokens (longest example ≈ 1,200, nothing truncated) |
| Instance | `ml.g5.xlarge` (A10G 24 GB) |
| Time / peak GPU memory | 36.7 min / 8.5 GB |
| Training loss / dev loss | 0.284 → 0.014 / 0.047 |

After training, the job merges the adapter into the base weights (`merge_and_unload`), embeds the
chat template in `tokenizer_config.json` (TGI reads it there; transformers 4.57 writes it only to
`chat_template.jinja`), and saves a `model.tar.gz` that the TGI container loads directly.

## Two training rounds

| Round | Data | Execution accuracy | What changed |
|---|---|---:|---|
| v2-lora | data v1 `93a8b1a171`, 2 epochs | 84.0% | Fixed statewide scope, refusal kinds, declining. Regressed on methodology (73% → 27%: no `search_knowledge` examples) and follow-ups (60% → 45%: every training follow-up named "City, ST" in the history). |
| **v3-lora** | **data v2 `f261a5f4d7`, 1 epoch** | **89.3%** | Added methodology examples and follow-ups whose history names only the city. Methodology 100%, follow-ups 85%. |

Both regressions were found on the eval set, and the fixes are general coverage fixes, not
eval-specific phrasings. Still, the data-v2 score is somewhat optimistic for that reason.

## Known limitations

- **Metric switch after a state ranking** ("Rank Colorado…" → "What about rent?") is answered as
  `unsupported`; the training data has no such follow-up ([evaluation.md](evaluation.md), "Found
  in the live demo").
- Remaining eval failures cluster in a few phrasings outside the grammar: "before/after Y"
  periods, "highest … among" read as the wrong operation, and flipped sort order for "cheapest".
- The answer writer is the same model without answer-specific training. 89.7% of its first
  answers pass the number check; the rest are regenerated or replaced by a template
  ([sampling.md](sampling.md)).
