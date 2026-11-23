# Training data report: `93a8b1a171`

- 3000 examples (seed 13, requested 3000); dataset `23ccd46a4560`; prompt `planner-v2`
- Distinct questions: 93.9%; mean prompt length 3798 characters (about 949 tokens)
- Wording overlap with the eval set (max character 3-gram Jaccard per example): median 0.277, 95th percentile 0.487, max 0.597; anything at or above 0.6 was rejected

## Rejected candidates

| Reason | Count |
|---|---:|
| outcome_no_rows | 146 |
| near_duplicate_of_eval | 113 |
| duplicate | 33 |
| builder_skip | 31 |
| holdout_question | 31 |
| outcome_no_data | 8 |
| holdout_plan | 7 |

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
| train | 2643 | 88.1% |
| dev | 357 | 11.9% |

### tool

| Value | Count | Share |
|---|---:|---:|
| analyze | 2514 | 83.8% |
| respond | 486 | 16.2% |

### operation

| Value | Count | Share |
|---|---:|---:|
| change | 596 | 23.7% |
| series | 495 | 19.7% |
| rank | 489 | 19.5% |
| yoy_change | 317 | 12.6% |
| extrema | 273 | 10.9% |
| aggregate | 196 | 7.8% |
| coverage | 148 | 5.9% |

### scope

| Value | Count | Share |
|---|---:|---:|
| cities | 1848 | 73.5% |
| state_filter | 666 | 26.5% |

### metric

| Value | Count | Share |
|---|---:|---:|
| zhvi | 1527 | 60.7% |
| zori | 987 | 39.3% |

### respond_kind

| Value | Count | Share |
|---|---:|---:|
| unsupported | 262 | 53.9% |
| out_of_scope | 224 | 46.1% |

### template

| Value | Count | Share |
|---|---:|---:|
| std.yoy_change | 134 | 4.5% |
| std.change | 129 | 4.3% |
| std.extrema | 128 | 4.3% |
| std.series | 126 | 4.2% |
| std.coverage | 126 | 4.2% |
| clarify.multi_state | 118 | 3.9% |
| clarify.fictional | 118 | 3.9% |
| clarify.ambiguous_in_state | 117 | 3.9% |
| std.yoy_asof | 107 | 3.6% |
| clarify.typo | 97 | 3.2% |
| scope.rank_dollar | 77 | 2.6% |
| scope.state_aggregate | 77 | 2.6% |
| scope.rank_decline | 76 | 2.5% |
| scope.state_count | 76 | 2.5% |
| scope.rank_growth | 75 | 2.5% |
| scope.list_trailing | 74 | 2.5% |
| scope.list_mixed | 73 | 2.4% |
| follow.add | 73 | 2.4% |
| follow.op | 73 | 2.4% |
| scope.rank_value | 72 | 2.4% |
| follow.period | 71 | 2.4% |
| retry.scope_neither | 66 | 2.2% |
| retry.switch_unsupported | 65 | 2.2% |
| follow.swap | 63 | 2.1% |
| refusal.missing | 61 | 2.0% |
| refusal.forecast | 61 | 2.0% |
| refusal.advice | 59 | 2.0% |
| follow.metric | 59 | 2.0% |
| retry.missing_rank_by | 58 | 1.9% |
| retry.scope_both | 58 | 1.9% |
| follow.forecast | 56 | 1.9% |
| follow.rank | 55 | 1.8% |
| retry.bad_month | 53 | 1.8% |
| refusal.injection_with_data | 51 | 1.7% |
| refusal.modeling | 48 | 1.6% |
| refusal.sql | 48 | 1.6% |
| refusal.op | 47 | 1.6% |
| refusal.injection | 41 | 1.4% |
| refusal.sql_translate | 34 | 1.1% |

