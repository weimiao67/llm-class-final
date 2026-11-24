# Sampling and decoding

Each turn makes two kinds of model calls, and they are decoded differently on purpose:

- **Planning** (the tool call) must be exact and reproducible, so it is **greedy and constrained**
  by a JSON schema.
- **Answer writing** (one or two sentences of prose) should read naturally, so it is **sampled at
  a low temperature**. A deterministic check then rejects any answer whose numbers aren't in the
  tool result.

The profiles are in `agent/decoding.py`; `tgi_parameters()` maps them to TGI Messages-API fields.

| Profile | Used for | Decoding | Temperature / top-p | Max new tokens | Constraint |
|---|---|---|---|---:|---|
| `plan` | first planner call | greedy | 0 / – | 256 | JSON schema |
| `plan_retry` | planner call after a rejected plan (at most 2) | greedy | 0 / – | 256 | JSON schema |
| `answer` | final answer | **nucleus sampling** | **0.3 / 0.9**, frequency penalty 0.05 | 200 | none |
| `answer_greedy` | answer regeneration after a failed check | greedy | 0 / – | 200 | none |

The retry profile decodes the same way as `plan`; what changes is the input: the rejected call
and the validator's message are added to the conversation, so greedy decoding gets a different
prompt and can reach a different plan.

## Planning: greedy + schema-constrained

**Why greedy.** A plan is a structured query, not prose: there is one right answer, and sampling
can only add wrong ones. Greedy decoding also makes runs reproducible, so an eval difference comes
from the model or prompt, not from chance.

**How the constraint works.** Each planner request sends TGI a JSON schema as
`response_format: {"type": "json_object", "value": <schema>}`. TGI compiles it into a grammar and,
at every step, masks out the tokens that would break it, so the model can only emit a well-formed
tool call: `analyze` with a plan, `search_knowledge` with a query, or `respond` with a kind and
text.

The schema is `decoding_schema()` in `tools/schemas.py`, a **structure-only** copy of the full
Pydantic schema:

- It keeps object shapes, required fields, types, and enums (tools, metrics, operations,
  aggregates, ranking fields, response kinds).
- It drops length limits, regex patterns, and numeric bounds. With them, TGI's grammar compiler
  hung on the endpoint (a 2,000-character text limit becomes a huge automaton). Pydantic still
  enforces every one of those rules after decoding; a violation goes back to the model as a normal
  retry, so removing them from the grammar doesn't loosen validation.
- It adds two rules the base models broke most often. The plan is split into a **city-scoped**
  variant (a non-empty `cities` list, no `state_filter`) and a **state-scoped** variant
  (`state_filter`, no `cities`), so "exactly one of cities or state" is enforced by the grammar.
  State fields are an enum of the 51 state codes, so the model can't write "Colorado" or "CA, USA".

`scripts/smoke_endpoint.py` checks on a live endpoint that TGI accepts the schema, that the reply
is a valid tool call, that the constraint is really enforced (asked to reply "hello", the model
still returns a tool call), and that greedy decoding gives the same output twice.

## Answer writing: low-temperature nucleus sampling + a grounding check

**Why sample.** The answer is short prose over numbers the model is given. Greedy decoding tends to
produce stiff, repetitive phrasing across turns; a low temperature (0.3) with nucleus sampling
(top-p 0.9) and a light repetition penalty gives natural variety while staying close to the most
likely wording. It isn't constrained: the content, not the format, is what matters here.

**Why that is safe.** Sampling could introduce a wrong number, so every answer goes through
`unsupported_numbers()` in `agent/grounding.py`. Each number in the answer must match, at the
precision the answer states it, a number in the tool result, a year in the result, or a number
the user typed. Then:

1. **Sampled answer** (`answer`). If every number is grounded, it is used (`answer_source: model`).
2. **Greedy regeneration** (`answer_greedy`). If not, the model tries once more without sampling
   (`model_regenerated`).
3. **Template.** If that fails too, code writes the answer from the result (`template`).

Methodology answers follow the same path, with the retrieved passages as the evidence. Turns that
end in a clarification or refusal use text written by code (`system`) and make no answer call.

## Results

From the saved eval runs (200 cases each):

| Answer step | Base Qwen2.5-3B | **Fine-tuned (data v2)** |
|---|---:|---:|
| Turns that reach the answer step | 118 | 155 |
| First sampled answer passes the check | 106 (89.8%) | **139 (89.7%)** |
| Rescued by greedy regeneration | 2 of 12 | 3 of 16 |
| Template fallback | 10 | 13 |
| Reason for every rejected answer | ungrounded number | ungrounded number |

Every number a user sees has passed the check or was written by code. In the fine-tuned run, the
16 rejected answers were of two kinds:

- **11 had a number the model computed or mis-scaled itself**, the error the check exists for.
  For example, Cleveland's 2023 change was written as 33,821.90 instead of 3,382.19, and a Las
  Vegas answer included 1,903,638.82, which is in no result.
- **5 had a stray small integer** ("1", or "96" and "3" in an answer to an injection attempt)
  that isn't in the result. These are mostly harmless, but the check can't tell them apart from
  invented counts, so it rejects them too.

| Planning | Base Qwen2.5-3B | **Fine-tuned (data v2)** |
|---|---:|---:|
| Valid first output (constrained) | 94.0% | **100.0%** |
| Planner retries in 200 cases | 25 (in 12 turns) | **0** |
| Mean model calls per turn | 1.60 | 1.71 |

The fine-tuned model makes slightly more calls per turn only because more of its turns reach the
answer step instead of stopping at a clarification.

**Constrained vs. unconstrained decoding** (same fine-tuned model, greedy, schema on or off):

| | Constrained | No constraint |
|---|---:|---:|
| Valid first output | 100.0% | 99.5% |
| Execution accuracy | 89.3% | 90.1% |
| Turn success | 92.5% | 92.5% |
| Latency p50 / p95 | 1.2 / 2.3 s | 1.1 / 2.1 s |

After fine-tuning, the model has learned the format, and the constraint makes no measurable
difference to accuracy (the 0.8-point gap is one case). The project keeps it on as a cheap safety
net: it guarantees a parseable call, and costs about 0.1 s at the median turn. For the base model the
constraint matters more: even with it, 6% of first outputs were invalid and 25 retries were
needed.

## Bounds on every turn

| Limit | Value | Where |
|---|---|---|
| Planner retries after a rejected plan | 2 | `MAX_PLAN_RETRIES`, `agent/orchestrator.py` |
| Earlier messages sent to the planner | 6 | `MAX_HISTORY_MESSAGES` |
| Time budget per turn | 60 s | `TURN_TIMEOUT_S`; checked before each model call |
| Model client attempts per call | bounded, with total-attempt limit | `agent/model_clients/sagemaker.py` |

## Not measured

- The base model **without** the constraint (the fine-tuned model was measured both ways; the base
  model only with it).
- A temperature sweep for the answer step. Every answer passes the grounding check regardless of
  temperature, so the choice affects wording, not correctness; 0.3 was chosen and not tuned.
