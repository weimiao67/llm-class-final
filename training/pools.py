"""Slot-value pools drawn from the real dataset, with every eval hold-out city name excluded."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from housing.db import HousingDB

STATE_NAMES = {
    "AK": "Alaska", "AL": "Alabama", "AR": "Arkansas", "AZ": "Arizona", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DC": "District of Columbia", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "IA": "Iowa", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "MA": "Massachusetts", "MD": "Maryland", "ME": "Maine", "MI": "Michigan", "MN": "Minnesota",
    "MO": "Missouri", "MS": "Mississippi", "MT": "Montana", "NC": "North Carolina",
    "ND": "North Dakota", "NE": "Nebraska", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NV": "Nevada", "NY": "New York", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VA": "Virginia",
    "VT": "Vermont", "WA": "Washington", "WI": "Wisconsin", "WV": "West Virginia",
    "WY": "Wyoming",
}  # fmt: skip

# Made-up place names for "not found" examples (checked against the data at load time).
FICTIONAL = [
    "Riverwood Falls", "Lake Marisol", "Port Avalon", "Cedar Hollow", "North Elmsbury",
    "Glenmoor Heights", "Silverbrook", "Fairhaven Bluffs", "Oakshade", "Maple Crossing",
    "Westerly Pines", "Brightwater", "Stonebridge Hills", "Elk Meadow Junction", "Quillport",
]  # fmt: skip

TOP_CITIES = 1500  # most draws come from bigger, familiar cities
TOP_SHARE = 0.75
MIN_STATE_CITIES = 8  # statewide questions only for states with enough cities


@dataclass(frozen=True)
class City:
    region_id: str
    name: str
    state: str
    county: str | None
    size_rank: int
    metrics: frozenset[str]


class Pools:
    def __init__(
        self, db: HousingDB, holdout_city_names: set[str], min_state_cities: int = MIN_STATE_CITIES
    ):
        holdout = {n.strip().lower() for n in holdout_city_names}
        ranks = {
            r["region_id"]: r["sr"]
            for r in db.query(
                "SELECT region_id, min(size_rank) AS sr FROM observations GROUP BY region_id", []
            )
        }
        everything = [
            City(r.region_id, r.city, r.state, r.county, ranks[r.region_id], r.metrics)
            for r in db.regions.values()
        ]
        states_of: dict[str, set[str]] = defaultdict(set)
        per_state_count: dict[tuple[str, str], int] = defaultdict(int)
        for c in everything:
            states_of[c.name.lower()].add(c.state)
            per_state_count[(c.name.lower(), c.state)] += 1
        self.known_names = set(states_of)
        allowed = [c for c in everything if c.name.lower() not in holdout]

        # "City, ST" must resolve to one place; a bare "City" must be unique in the whole data.
        self.in_state: dict[str, list[City]] = {}
        self.bare: dict[str, list[City]] = {}
        for metric in ("zhvi", "zori"):
            ok = sorted(
                (c for c in allowed if metric in c.metrics
                 and per_state_count[(c.name.lower(), c.state)] == 1),
                key=lambda c: c.size_rank,
            )  # fmt: skip
            self.in_state[metric] = ok
            self.bare[metric] = [c for c in ok if len(states_of[c.name.lower()]) == 1]

        self.by_state: dict[str, dict[str, list[City]]] = {"zhvi": {}, "zori": {}}
        for metric, cities in self.in_state.items():
            groups: dict[str, list[City]] = defaultdict(list)
            for c in cities:
                groups[c.state].append(c)
            self.by_state[metric] = dict(groups)
        self.states = {
            m: sorted(s for s, cs in self.by_state[m].items() if len(cs) >= min_state_cities)
            for m in ("zhvi", "zori")
        }
        self.ambiguous_in_state = sorted(
            {(c.name, c.state) for c in allowed if per_state_count[(c.name.lower(), c.state)] > 1}
        )
        self.multi_state_names = sorted(
            {c.name for c in allowed if len(states_of[c.name.lower()]) >= 3 and "zhvi" in c.metrics}
        )
        self.fictional = [n for n in FICTIONAL if n.lower() not in self.known_names]

    def city(self, rng: random.Random, metric: str, *, bare: bool = False) -> City:
        cities = (self.bare if bare else self.in_state)[metric]
        top = cities[:TOP_CITIES]
        return rng.choice(top if rng.random() < TOP_SHARE else cities)

    def cities_in_state(self, rng: random.Random, metric: str, state: str, k: int) -> list[City]:
        cities = self.by_state[metric].get(state, [])
        if len(cities) < k:
            return []
        return rng.sample(cities[: max(k, 60)], k)  # bigger cities read more naturally

    def state(self, rng: random.Random, metric: str) -> str:
        return rng.choice(self.states[metric])

    def typo(self, rng: random.Random, metric: str) -> tuple[str, str] | None:
        """A misspelled real city ("Pueblo" -> "Peublo") that does not exist in the data."""
        city = self.city(rng, metric)
        name = city.name
        if len(name) < 5:
            return None
        i = rng.randrange(1, len(name) - 2)
        if name[i] == " " or name[i + 1] == " ":
            return None
        typo = name[:i] + name[i + 1] + name[i] + name[i + 2 :]
        return (typo, city.state) if typo.lower() not in self.known_names else None
