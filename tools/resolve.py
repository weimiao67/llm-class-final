"""City-name resolution. Ambiguity is reported, never guessed."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from housing.db import Region
from tools.schemas import CityRef, ResolvedRegion

SUGGEST_MIN_SCORE = 75


@dataclass
class Resolution:
    matches: list[ResolvedRegion]
    suggestions: list[str]

    @property
    def ambiguous(self) -> bool:
        return len(self.matches) > 1


def _norm(text: str | None) -> str:
    """Normalize a city name. Suffixes are kept: 'Lebanon Borough' is not 'Lebanon'."""
    return " ".join((text or "").lower().split())


def _norm_county(text: str | None) -> str:
    """Normalize a county name so 'Weld' and 'Weld County' compare equal."""
    text = _norm(text)
    for suffix in (" county", " parish", " borough"):
        text = text.removesuffix(suffix)
    return text


class CityResolver:
    def __init__(self, regions: dict[str, Region]):
        self._by_city: dict[str, list[Region]] = defaultdict(list)
        for region in regions.values():
            self._by_city[_norm(region.city)].append(region)
        # (normalized city, "City, ST") pairs for fuzzy suggestions, optionally per state.
        self._names: dict[str | None, list[tuple[str, str]]] = defaultdict(list)
        for city, state in sorted({(r.city, r.state) for r in regions.values()}):
            entry = (_norm(city), f"{city}, {state}")
            self._names[None].append(entry)
            self._names[state].append(entry)

    def resolve(self, ref: CityRef) -> Resolution:
        candidates = self._by_city.get(_norm(ref.city), [])
        if ref.state:
            candidates = [r for r in candidates if r.state == ref.state]
        if ref.county:
            candidates = [
                r for r in candidates if _norm_county(r.county) == _norm_county(ref.county)
            ]
        matches = [
            ResolvedRegion(region_id=r.region_id, city=r.city, state=r.state, county=r.county)
            for r in sorted(candidates, key=lambda r: (r.state, r.county or "", r.region_id))
        ]
        suggestions: list[str] = []
        if not matches:
            pool = self._names.get(ref.state, [])
            hits = process.extract(
                _norm(ref.city), [name for name, _ in pool], scorer=fuzz.ratio, limit=5
            )
            suggestions = [pool[idx][1] for _, score, idx in hits if score >= SUGGEST_MIN_SCORE]
        return Resolution(matches=matches, suggestions=suggestions)
