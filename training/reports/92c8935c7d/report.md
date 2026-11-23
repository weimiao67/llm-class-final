# Training data report: `92c8935c7d`

- 3000 examples (seed 13, requested 3000); dataset `23ccd46a4560`; prompt `planner-v2`
- Distinct questions: 93.7%; mean prompt length 3776 characters (about 944 tokens)
- Wording overlap with the eval set (max character 3-gram Jaccard per example): median 0.275, 95th percentile 0.5, max 0.597; anything at or above 0.6 was rejected

## Rejected candidates

| Reason | Count |
|---|---:|
| outcome_no_rows | 150 |
| near_duplicate_of_eval | 78 |
| holdout_question | 47 |
| duplicate | 33 |
| builder_skip | 28 |
| outcome_no_data | 17 |
| holdout_plan | 8 |

## Composition

### scenario

| Value | Count | Share |
|---|---:|---:|
| standard | 690 | 23.0% |
| scope | 570 | 19.0% |
| follow_up | 480 | 16.0% |
| clarify | 420 | 14.0% |
| refusal | 420 | 14.0% |
| retry | 240 | 8.0% |
| methodology | 180 | 6.0% |

### split

| Value | Count | Share |
|---|---:|---:|
| train | 2653 | 88.4% |
| dev | 347 | 11.6% |

### tool

| Value | Count | Share |
|---|---:|---:|
| analyze | 2372 | 79.1% |
| respond | 448 | 14.9% |
| search_knowledge | 180 | 6.0% |

### operation

| Value | Count | Share |
|---|---:|---:|
| change | 554 | 23.4% |
| series | 473 | 19.9% |
| rank | 434 | 18.3% |
| yoy_change | 291 | 12.3% |
| extrema | 260 | 11.0% |
| aggregate | 216 | 9.1% |
| coverage | 144 | 6.1% |

### scope

| Value | Count | Share |
|---|---:|---:|
| cities | 1744 | 73.5% |
| state_filter | 628 | 26.5% |

### metric

| Value | Count | Share |
|---|---:|---:|
| zhvi | 1424 | 60.0% |
| zori | 948 | 40.0% |

### respond_kind

| Value | Count | Share |
|---|---:|---:|
| unsupported | 234 | 37.3% |
| out_of_scope | 214 | 34.1% |
| search_knowledge | 180 | 28.7% |

### template

| Value | Count | Share |
|---|---:|---:|
| methodology.search | 180 | 6.0% |
| std.yoy_change | 126 | 4.2% |
| std.coverage | 125 | 4.2% |
| std.change | 119 | 4.0% |
| std.extrema | 118 | 3.9% |
| clarify.multi_state | 110 | 3.7% |
| clarify.fictional | 110 | 3.7% |
| clarify.ambiguous_in_state | 109 | 3.6% |
| std.series | 105 | 3.5% |
| std.yoy_asof | 97 | 3.2% |
| clarify.typo | 91 | 3.0% |
| follow.add | 82 | 2.7% |
| follow.op | 81 | 2.7% |
| scope.rank_decline | 74 | 2.5% |
| scope.rank_dollar | 74 | 2.5% |
| scope.state_aggregate | 73 | 2.4% |
| scope.state_count | 73 | 2.4% |
| follow.period | 72 | 2.4% |
| scope.rank_growth | 71 | 2.4% |
| scope.rank_value | 69 | 2.3% |
| scope.list_trailing | 68 | 2.3% |
| scope.list_mixed | 68 | 2.3% |
| follow.swap | 68 | 2.3% |
| follow.forecast | 61 | 2.0% |
| follow.metric | 60 | 2.0% |
| refusal.missing | 56 | 1.9% |
| follow.rank | 56 | 1.9% |
| refusal.forecast | 55 | 1.8% |
| retry.scope_neither | 54 | 1.8% |
| refusal.advice | 52 | 1.7% |
| retry.switch_unsupported | 52 | 1.7% |
| refusal.injection_with_data | 50 | 1.7% |
| retry.missing_rank_by | 49 | 1.6% |
| retry.scope_both | 47 | 1.6% |
| refusal.modeling | 46 | 1.5% |
| refusal.sql | 45 | 1.5% |
| refusal.op | 42 | 1.4% |
| refusal.injection | 39 | 1.3% |
| retry.bad_month | 38 | 1.3% |
| refusal.sql_translate | 35 | 1.2% |

