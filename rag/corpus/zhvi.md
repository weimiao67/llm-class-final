---
doc_id: zhvi
title: Zillow Home Value Index (ZHVI)
publisher: Zillow Research (summarized for this project)
source_url: https://www.zillow.com/research/methodology-neural-zhvi-32128/
retrieved: 2026-11-24
review: written in this project's own words from Zillow's methodology page; checked against screenshots of that page on 2026-11-24
---

## What ZHVI measures

ZHVI is Zillow's measure of the value of a typical home in a region and of how that value changes
each month. It draws on the full distribution of homes in the region, not just the homes that sold
that month, and it is available for many geographies and housing types (for example, all
single-family homes in one ZIP code). Because it follows the same homes over time, it reflects real
price changes rather than changes in which kinds of homes happened to sell.

## How ZHVI is calculated

ZHVI is built from Zestimates, Zillow's estimated values for individual homes, covering more than
100 million U.S. homes, including new construction and homes not listed for sale in years. Each
month Zillow takes a trimmed mean of the middle third of Zestimates in a region, and chains it over
time with a repeat-Zestimate index. That works like a repeat-sales index, except that instead of
waiting for the same home to sell twice, it compares each home's changing Zestimate every month.

## The 2023 neural Zestimate update

Starting with the January 2023 data release, the whole ZHVI history was recomputed from the neural
Zestimate, a neural-network model trained on long histories of sales, tax assessments, public
records, listings, and home details. The way the index is calculated did not change; only the
Zestimates behind it did. Zillow reports that the new Zestimates track market turning points better
and show stronger seasonal swings. Neural Zestimates aren't produced before 2012, so the earlier part
of the series is joined to the historical index with its seasonal patterns harmonized.

## Tiers and the series used here

The typical ZHVI summarizes the middle third of homes in a region, which matches this project's
source file, labeled with the 0.33 to 0.67 quantile band. Zillow also publishes other variants, for
example by housing type. This project uses the city-level series for all homes (single-family plus
condo and co-op), middle tier, smoothed and seasonally adjusted.

## Smoothing and seasonal adjustment

Zillow publishes ZHVI both raw and smoothed and seasonally adjusted; this project uses the smoothed,
seasonally adjusted series. Home values have a regular yearly rhythm: month-over-month growth is
typically slowest in December and fastest in May. Seasonal adjustment removes that rhythm, and
smoothing reduces month-to-month noise, so changes in the series reflect the underlying trend.

## Limitations of ZHVI

ZHVI is an index of estimated values, not a transaction price: it is not what any particular home
sold for, not a listing price, and not an appraisal of a specific property. A single home's value
can differ substantially from its region's typical value. Zillow recomputes the full history when
its inputs improve (as in January 2023), so past values can change between data releases.

## ZHVI compared with sale-price measures

Median sale prices reflect what actually traded, but they move with the mix of homes that happen to
sell each month, sometimes seasonally and sometimes randomly. Repeat-sales indices such as the S&P
CoreLogic Case-Shiller index control for that mix, but they weight homes like a trading portfolio,
so expensive and frequently traded homes count more. ZHVI instead aims at the typical home across
the whole housing stock, and it is published within weeks of each month's end.
