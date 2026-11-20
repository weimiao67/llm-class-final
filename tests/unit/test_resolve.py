from housing.db import Region
from tools.resolve import CityResolver
from tools.schemas import CityRef


def region(rid, city, state, county):
    return Region(rid, city, state, county, frozenset({"zhvi"}))


def test_city_suffix_is_not_stripped():
    resolver = CityResolver(
        {
            "1": region("1", "Washington", "NJ", "Warren County"),
            "2": region("2", "Washington Borough", "NJ", "Warren County"),
        }
    )
    res = resolver.resolve(CityRef(city="Washington Borough", state="NJ"))
    assert [m.region_id for m in res.matches] == ["2"]
    assert [m.region_id for m in resolver.resolve(CityRef(city="washington")).matches] == ["1"]


def test_county_suffix_is_optional():
    resolver = CityResolver({"1": region("1", "Mead", "CO", "Weld County")})
    assert resolver.resolve(CityRef(city="Mead", county="weld")).matches


def test_suggestions_stay_within_state():
    resolver = CityResolver(
        {
            "1": region("1", "Boulder", "CO", "Boulder County"),
            "2": region("2", "Boulder", "UT", "Garfield County"),
            "3": region("3", "Acres Green", "CO", "Douglas County"),
        }
    )
    assert resolver.resolve(CityRef(city="Bouldr", state="CO")).suggestions == ["Boulder, CO"]
