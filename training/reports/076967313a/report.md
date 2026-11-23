# Training data report: `076967313a`

- 3000 examples (seed 13, requested 3000); dataset `23ccd46a4560`; prompt `planner-v2`
- Distinct questions: 93.9%; mean prompt length 3798 characters (about 949 tokens)
- Wording overlap with the eval set (max character 3-gram Jaccard per example): median 0.277, 95th percentile 0.485, max 0.597; anything at or above 0.6 was rejected

## Rejected candidates

| Reason | Count |
|---|---:|
| outcome_no_rows | 138 |
| near_duplicate_of_eval | 113 |
| builder_skip | 33 |
| holdout_question | 33 |
| duplicate | 28 |
| outcome_no_data | 8 |
| holdout_plan | 6 |

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
| train | 2639 | 88.0% |
| dev | 361 | 12.0% |

### tool

| Value | Count | Share |
|---|---:|---:|
| analyze | 2517 | 83.9% |
| respond | 483 | 16.1% |

### operation

| Value | Count | Share |
|---|---:|---:|
| change | 602 | 23.9% |
| series | 498 | 19.8% |
| rank | 488 | 19.4% |
| yoy_change | 312 | 12.4% |
| extrema | 275 | 10.9% |
| aggregate | 195 | 7.7% |
| coverage | 147 | 5.8% |

### scope

| Value | Count | Share |
|---|---:|---:|
| cities | 1852 | 73.6% |
| state_filter | 665 | 26.4% |

### metric

| Value | Count | Share |
|---|---:|---:|
| zhvi | 1528 | 60.7% |
| zori | 989 | 39.3% |

### respond_kind

| Value | Count | Share |
|---|---:|---:|
| unsupported | 259 | 53.6% |
| out_of_scope | 224 | 46.4% |

### template

| Value | Count | Share |
|---|---:|---:|
| std.yoy_change | 134 | 4.5% |
| std.extrema | 128 | 4.3% |
| std.change | 128 | 4.3% |
| std.series | 126 | 4.2% |
| std.coverage | 126 | 4.2% |
| clarify.ambiguous_in_state | 119 | 4.0% |
| clarify.fictional | 119 | 4.0% |
| clarify.multi_state | 118 | 3.9% |
| std.yoy_asof | 108 | 3.6% |
| clarify.typo | 94 | 3.1% |
| scope.rank_dollar | 77 | 2.6% |
| scope.state_aggregate | 77 | 2.6% |
| scope.rank_decline | 76 | 2.5% |
| scope.state_count | 76 | 2.5% |
| scope.rank_growth | 75 | 2.5% |
| scope.list_trailing | 74 | 2.5% |
| scope.list_mixed | 73 | 2.4% |
| follow.add | 73 | 2.4% |
| scope.rank_value | 72 | 2.4% |
| follow.op | 72 | 2.4% |
| follow.period | 71 | 2.4% |
| retry.scope_neither | 65 | 2.2% |
| follow.swap | 64 | 2.1% |
| retry.switch_unsupported | 63 | 2.1% |
| refusal.forecast | 61 | 2.0% |
| refusal.advice | 61 | 2.0% |
| refusal.missing | 60 | 2.0% |
| retry.scope_both | 60 | 2.0% |
| follow.metric | 59 | 2.0% |
| retry.missing_rank_by | 58 | 1.9% |
| follow.forecast | 56 | 1.9% |
| follow.rank | 55 | 1.8% |
| retry.bad_month | 54 | 1.8% |
| refusal.injection_with_data | 52 | 1.7% |
| refusal.sql | 51 | 1.7% |
| refusal.modeling | 46 | 1.5% |
| refusal.op | 44 | 1.5% |
| refusal.injection | 41 | 1.4% |
| refusal.sql_translate | 34 | 1.1% |

