---
doc_id: data_coverage
title: Data coverage, geography, and updates
publisher: Housing Market AI Analyst project
source_url: https://www.zillow.com/research/data/
retrieved: 2026-11-24
review: project-written; coverage figures come from the dataset loaded in this project; publication rules checked against Zillow's methodology pages on 2026-11-24
---

## Geography of the city series

The data is Zillow's city-level series. Each region is a city as Zillow defines it, with its state
and county; its boundaries are Zillow's, which may not match official city limits
exactly. Many city names repeat: the same name can exist in several states, or in several counties
of one state, which is why the analyst asks which one you mean when a name is ambiguous.

## Coverage in this dataset

Home values (ZHVI) cover about 24,200 cities from March 2000 to October 2026. Rents (ZORI) cover
about 4,400 cities from January 2015 to October 2026. A city can have home value data but no rent
data, and a city's series can start later than the index itself.

## Why some months are missing

Zillow publishes a value only when it has enough data for a city in that month, and it checks each
series for data-quality problems before publishing, sometimes deciding not to publish one. Months without a
published value are left as gaps: the analyst never interpolates or estimates them, and charts
show them as breaks in the line. Smaller places and rents have more gaps than large cities and
home values.

## How often the data is updated

Zillow publishes these series monthly, and may revise earlier months when it updates methods or
inputs. This project works from a fixed snapshot identified by its dataset version; newer data
requires re-importing the source files.
