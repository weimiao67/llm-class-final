# Training data report: `96da580bfc`

- 3000 examples (seed 13, requested 3000); dataset `23ccd46a4560`; prompt `planner-v2`
- Distinct questions: 94.2%; mean prompt length 3802 characters (about 950 tokens)
- Wording overlap with the eval set (max character 3-gram Jaccard per example): median 0.277, 95th percentile 0.486, max 0.598; anything at or above 0.6 was rejected

## Rejected candidates

| Reason | Count |
|---|---:|
| outcome_no_rows | 124 |
| near_duplicate_of_eval | 100 |
| duplicate | 33 |
| holdout_question | 29 |
| builder_skip | 26 |
| outcome_no_data | 7 |
| holdout_plan | 5 |

## Composition

### scenario

| Value | Count | Share |
|---|---:|---:|
| standard | 750 | 25.0% |
| scope | 600 | 20.0% |
| clarify | 450 | 15.0% |
| refusal | 450 | 15.0% |
| follow_up | 450 | 15.0% |
| retry | 300 | 10.0% |

### split

| Value | Count | Share |
|---|---:|---:|
| train | 2644 | 88.1% |
| dev | 356 | 11.9% |

### tool

| Value | Count | Share |
|---|---:|---:|
| analyze | 2515 | 83.8% |
| respond | 485 | 16.2% |

### operation

| Value | Count | Share |
|---|---:|---:|
| change | 597 | 23.7% |
| series | 500 | 19.9% |
| rank | 489 | 19.4% |
| yoy_change | 311 | 12.4% |
| extrema | 278 | 11.1% |
| aggregate | 195 | 7.8% |
| coverage | 145 | 5.8% |

### scope

| Value | Count | Share |
|---|---:|---:|
| cities | 1852 | 73.6% |
| state_filter | 663 | 26.4% |

### metric

| Value | Count | Share |
|---|---:|---:|
| zhvi | 1519 | 60.4% |
| zori | 996 | 39.6% |

### respond_kind

| Value | Count | Share |
|---|---:|---:|
| unsupported | 265 | 54.6% |
| out_of_scope | 220 | 45.4% |

### template

| Value | Count | Share |
|---|---:|---:|
| std.yoy_change | 133 | 4.4% |
| std.change | 130 | 4.3% |
| std.extrema | 129 | 4.3% |
| std.series | 126 | 4.2% |
| std.coverage | 126 | 4.2% |
| clarify.multi_state | 116 | 3.9% |
| clarify.fictional | 116 | 3.9% |
| clarify.ambiguous_in_state | 115 | 3.8% |
| std.yoy_asof | 106 | 3.5% |
| clarify.typo | 103 | 3.4% |
| scope.rank_decline | 77 | 2.6% |
| scope.rank_dollar | 77 | 2.6% |
| scope.state_aggregate | 76 | 2.5% |
| scope.state_count | 76 | 2.5% |
| scope.rank_growth | 75 | 2.5% |
| scope.list_mixed | 74 | 2.5% |
| follow.add | 74 | 2.5% |
| scope.rank_value | 73 | 2.4% |
| follow.op | 73 | 2.4% |
| scope.list_trailing | 72 | 2.4% |
| follow.period | 70 | 2.3% |
| follow.swap | 67 | 2.2% |
| retry.scope_neither | 67 | 2.2% |
| retry.switch_unsupported | 64 | 2.1% |
| follow.metric | 61 | 2.0% |
| retry.missing_rank_by | 61 | 2.0% |
| refusal.forecast | 60 | 2.0% |
| refusal.missing | 59 | 2.0% |
| retry.scope_both | 59 | 2.0% |
| refusal.advice | 58 | 1.9% |
| follow.forecast | 55 | 1.8% |
| refusal.op | 53 | 1.8% |
| refusal.injection_with_data | 53 | 1.8% |
| refusal.sql | 50 | 1.7% |
| follow.rank | 50 | 1.7% |
| retry.bad_month | 49 | 1.6% |
| refusal.modeling | 47 | 1.6% |
| refusal.injection | 39 | 1.3% |
| refusal.sql_translate | 31 | 1.0% |

