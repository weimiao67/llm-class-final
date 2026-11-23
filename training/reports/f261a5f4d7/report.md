# Training data report: `f261a5f4d7`

- 3000 examples (seed 13, requested 3000); dataset `23ccd46a4560`; prompt `planner-v2`
- Distinct questions: 93.1%; mean prompt length 3776 characters (about 944 tokens)
- Wording overlap with the eval set (max character 3-gram Jaccard per example): median 0.275, 95th percentile 0.492, max 0.597; anything at or above 0.6 was rejected

## Rejected candidates

| Reason | Count |
|---|---:|
| outcome_no_rows | 149 |
| near_duplicate_of_eval | 74 |
| duplicate | 35 |
| builder_skip | 26 |
| outcome_no_data | 17 |
| holdout_question | 9 |
| holdout_plan | 7 |

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
| train | 2661 | 88.7% |
| dev | 339 | 11.3% |

### tool

| Value | Count | Share |
|---|---:|---:|
| analyze | 2352 | 78.4% |
| respond | 468 | 15.6% |
| search_knowledge | 180 | 6.0% |

### operation

| Value | Count | Share |
|---|---:|---:|
| change | 542 | 23.0% |
| series | 460 | 19.6% |
| rank | 435 | 18.5% |
| yoy_change | 291 | 12.4% |
| extrema | 257 | 10.9% |
| aggregate | 224 | 9.5% |
| coverage | 143 | 6.1% |

### scope

| Value | Count | Share |
|---|---:|---:|
| cities | 1715 | 72.9% |
| state_filter | 637 | 27.1% |

### metric

| Value | Count | Share |
|---|---:|---:|
| zhvi | 1422 | 60.5% |
| zori | 930 | 39.5% |

### respond_kind

| Value | Count | Share |
|---|---:|---:|
| unsupported | 235 | 36.3% |
| out_of_scope | 233 | 36.0% |
| search_knowledge | 180 | 27.8% |

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
| follow.forecast | 80 | 2.7% |
| follow.add | 76 | 2.5% |
| follow.op | 75 | 2.5% |
| scope.rank_decline | 74 | 2.5% |
| scope.rank_dollar | 74 | 2.5% |
| scope.state_aggregate | 73 | 2.4% |
| scope.state_count | 73 | 2.4% |
| scope.rank_growth | 71 | 2.4% |
| scope.rank_value | 69 | 2.3% |
| scope.list_trailing | 68 | 2.3% |
| scope.list_mixed | 68 | 2.3% |
| follow.period | 67 | 2.2% |
| follow.rank | 64 | 2.1% |
| follow.swap | 63 | 2.1% |
| refusal.missing | 56 | 1.9% |
| refusal.forecast | 55 | 1.8% |
| follow.metric | 55 | 1.8% |
| retry.scope_neither | 54 | 1.8% |
| retry.switch_unsupported | 53 | 1.8% |
| refusal.advice | 52 | 1.7% |
| refusal.injection_with_data | 50 | 1.7% |
| retry.missing_rank_by | 50 | 1.7% |
| refusal.modeling | 46 | 1.5% |
| retry.scope_both | 46 | 1.5% |
| refusal.sql | 45 | 1.5% |
| refusal.op | 42 | 1.4% |
| refusal.injection | 39 | 1.3% |
| retry.bad_month | 37 | 1.2% |
| refusal.sql_translate | 35 | 1.2% |

