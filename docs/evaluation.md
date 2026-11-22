# Evaluation results

All runs use the frozen 200-case set `evaluation/cases/v1.jsonl` (see
[evaluation/README.md](../evaluation/README.md) for the cases and metrics) and dataset version
`23ccd46a4560`. Each run's full report is under `evaluation/reports/<run-id>/`.

## Summary

| Run | Model | Prompt | Decoding | Turn success | Execution accuracy | Report |
|---|---|---|---|---:|---:|---|
| v0 | Llama-3.2-3B-Instruct (base) | planner-v1 | greedy, structure-only schema | 31.0% | 16.0% | [`20261122-071857-…`](../evaluation/reports/20261122-071857-llama-3.2-3b-instruct-base/report.md) |
| v1 | Llama-3.2-3B-Instruct (base) | planner-v2 | greedy, scoped schema + state codes | pending | pending | |

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

## v1 changes (planner-v2), measured next

- The decoding schema splits the plan into city-scoped and state-scoped variants. The grammar then
  enforces "exactly one" scope, and state fields are limited to the 51 state codes.
- The retry feedback tells the model to fix the call, or to switch to `respond(unsupported)` when
  the data can't answer the question, and never to relay the error.
- The prompt states when to use each tool and the scope rule.
- Results now keep the raw planner outputs, plan, and trace for every case.
