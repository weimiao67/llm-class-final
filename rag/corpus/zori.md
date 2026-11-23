---
doc_id: zori
title: Zillow Observed Rent Index (ZORI)
publisher: Zillow Research (summarized for this project)
source_url: https://www.zillow.com/research/methodology-zori-repeat-rent-27092/
retrieved: 2026-11-24
review: written in this project's own words from Zillow's methodology page; checked against screenshots of that page on 2026-11-24
---

## What ZORI measures

ZORI measures how asking rents change over time, controlling for changes in the quality and mix of
the rentals that happen to be available. Zillow introduced it in May 2020, with April 2020 data.
Median or average listed rents can move just because different kinds of units are on the market at
different times; ZORI is designed to show actual market movement in rents instead.

## How ZORI is calculated

ZORI is a repeat-rent index: it measures rent differences for the same rental unit over time, then
combines those differences across all properties listed for rent on Zillow more than once. The
method follows the repeat-sales tradition (Bailey, Muth, and Nourse, 1963; Case and Shiller, late
1980s) and is closest to the repeat-rent index of Ambrose, Coulson, and Yoshida: changes in log rents
are regressed on the months between listings, and the coefficients give the month-to-month changes
of the index. In its later stages, Zillow weights observations by how representative they are of
the rental market rather than by the time between listings.

## Weighting to the rental market

To represent the whole rental market, not just units posted on Zillow, ZORI weights each unit type
by its share of rented units in U.S. Census Bureau data (the American Community Survey) relative to
its share of Zillow listings. Unit types are defined by the decade the building was built and its
size: single-unit (detached or attached), 2 to 4 units, or 5 or more units. Units that appear more
often in Zillow's data get less weight, and under-represented ones get more.

## Housing types in ZORI

Because the weights cover single-unit homes and small and large multifamily buildings, ZORI
reflects the rental stock across housing types. The series used here is for all homes plus
multifamily (single-family, condo and co-op, and apartment rentals).

## Asking rent versus rent paid

ZORI is based on asking rents for units listed on the market. Asking rents can differ from the rent
written into a signed lease, and ZORI says nothing about units that were never listed during the
period, such as leases renewed without a listing.

## Dollar level of ZORI

ZORI is reported in dollars. Zillow attaches a dollar value to the latest month, the weighted mean
of asking rents in the middle 30% of the distribution (the 35th to 65th percentile), and uses the
index's month-to-month changes to chain that dollar value back in time. The mean of the middle band
captures small market changes while reducing noise.

## Smoothing and coverage of ZORI

ZORI is smoothed with a three-month simple moving average, and a seasonally adjusted version uses a
proprietary method that is robust to outlier periods such as the 2020 pandemic; this project uses
the smoothed, seasonally adjusted series. Zillow calculates ZORI for the nation, metros, counties,
cities, and ZIP codes wherever there is enough data, and checks each series for data-quality
problems before publishing it. In this dataset, ZORI starts in January 2015 and covers fewer cities
than home values do.
