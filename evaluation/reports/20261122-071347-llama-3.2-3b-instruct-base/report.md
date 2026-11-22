# Evaluation report: llama-3.2-3b-instruct-base

- Run: `20261122-071347-llama-3.2-3b-instruct-base` · cases: `evaluation/cases/v1.jsonl` (20 cases)
- Dataset `23ccd46a4560` · prompt `planner-v1` · code `c318c02` · knowledge base: unavailable

## Overall

| Metric | Result |
|---|---|
| Envelope valid (first output) | 20.0% (4/20) |
| Tool selection (first call) | 20.0% (4/20) |
| Response kind | 20.0% (4/20) |
| Plan match | 10.0% (2/20) |
| **Execution accuracy** | **10.5% (2/19)** |
| Faithful model answer | 100.0% (4/4) |
| Turn success | 10.0% (2/20) |
| Clarification cases reached via analyze | 0.0% (0/1) |
| Latency p50 / p95 (ms) | 1468.2 / 1622.5 |
| Mean model calls per turn | 2.0 |

## By family

| Family | Cases | Tool | Kind | Execution | Success |
|---|---:|---|---|---|---|
| single_city | 20 | 20.0% (4/20) | 20.0% (4/20) | 10.5% (2/19) | 10.0% (2/20) |

## Failures (18)

- **single_city-001** — Show Denver, CO's ZORI since 2020.  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-002** — How much did home values in Austin, TX change between January 2020 and December 2024?  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-003** — What's the year-over-year change in rent for Seattle?  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-004** — Plot Phoenix, AZ home values from 2016 through 2025.  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-005** — How did rents in Miami, FL change in 2023?  
  plan differs from gold; executed result differs from gold
- **single_city-006** — Give me the monthly ZHVI for Boise, ID in 2024.  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-008** — Percent change in Chicago rent from 2019 to 2024?  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-009** — Show me the home value trend for Raleigh, NC since 2018.  
  first tool None, expected 'analyze'; response kind 'error', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-010** — How have San Francisco rents changed since January 2020?  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-011** — Year over year change in Tampa, FL ZORI as of June 2025.  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-012** — Home value index for Columbus, Ohio during 2022.  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-013** — How much did Las Vegas, NV home values change from 2006 to 2012?  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-014** — Rent trend in Portland, OR from 2021 to 2023.  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-015** — What was the YoY change in Atlanta home values in December 2024?  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'clarify'; plan differs from gold
- **single_city-016** — Change in Salt Lake City home values over 2024.  
  plan differs from gold; executed result differs from gold
- **single_city-017** — Show Honolulu rent since 2019.  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-018** — How did Detroit, MI home values change between 2010 and 2020?  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
- **single_city-019** — Monthly rent index for Minneapolis, MN in 2025.  
  first tool None, expected 'analyze'; response kind 'unsupported', expected 'answer'; plan differs from gold; executed result differs from gold
