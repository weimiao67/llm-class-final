---
doc_id: analyst_scope
title: What the analyst can and can't answer
publisher: Housing Market AI Analyst project
source_url: https://github.com/weimiao67/llm-class-final
retrieved: 2026-11-24
review: project-written description of this system's own rules
---

## Supported analyses

The analyst answers descriptive questions about ZHVI and ZORI for cities and states: values over a
period, changes and percent changes, year-over-year change, highest and lowest months, rankings,
aggregates across cities (average, median, minimum, maximum, count), and which months have data.
Every number comes from the database through a validated plan, and the rows behind an answer are
shown with it.

## Out of scope

The analyst does not forecast or predict, give buying, selling, or investment advice, or build
statistical models such as regressions or clusters. It has no data on bedrooms, square footage,
sales counts, mortgage rates, crime, schools, taxes, or income. It does not run SQL or code supplied
by a user. When a question falls outside these limits, it says so and offers a related
historical analysis where one exists.
