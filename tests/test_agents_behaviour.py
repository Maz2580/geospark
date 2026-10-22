"""Agent behaviour with controlled inputs: goal parsing, nearby search and site selection.

Geocoding and Overpass are replaced by fakes with known coordinates, so distances, filtering
and ranking can be checked exactly. The LLM is made unavailable, so the rule-based fallback
parser is what runs, as it does whenever Ollama is down or busy.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from pyproj import Geod

from geospark.agents.geo_agent import GeoAgent
from geospark.agents.site_selector import SiteSelector
from geospark.knowledge.entities import SpatialEntity

GEOD = Geod(ellps="WGS84")
EIFFEL = (2.2945, 48.8584)


def offset(origin: tuple[float, float], azimuth: float, metres: float) -> list[float]:
    lon, lat, _ = GEOD.fwd(origin[0], origin[1], azimuth, metres)
    return [lon, lat]


def entity(name: str, coords: list[float], kind: str = "hospital") -> SpatialEntity:
    return SpatialEntity(id=name, name=name, entity_type=kind, geometry={"type": "Point", "coordinates": coords})


class FakeLauncher:
    """Answers geocode tool calls from a fixed table."""

    def __init__(self, places: dict[str, tuple[float, float]]) -> None:
        self.places = places
        self.queries: list[str] = []

    def handle_tool_call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        assert name == "geocode"
        self.queries.append(args["query"])
        coords = self.places.get(args["query"])
        if coords is None:
            return {"status": "error", "errors": ["not found"]}
        return {"status": "success", "result": {"features": [{
            "geometry": {"type": "Point", "coordinates": list(coords)},
            "properties": {"display_name": args["query"]},
        }]}}


class FakeOverpass:
    def __init__(self, by_type: dict[str, list[SpatialEntity]]) -> None:
        self.by_type = by_type
        self.calls: list[tuple[tuple[float, ...], str]] = []

    def load_amenities(self, bbox, amenity_type):
        self.calls.append((bbox, amenity_type))
        return self.by_type.get(amenity_type, [])


@pytest.fixture(autouse=True)
def no_llm():
    """Force the rule-based paths (no Ollama)."""
    with patch("httpx.post", side_effect=ConnectionError("LLM unavailable")):
        yield


# --- Fallback goal parsing ----------------------------------------------------------

@pytest.mark.parametrize(
    ("goal", "locations", "intent", "params"),
    [
        ("Find all hospitals within 2km of the Eiffel Tower", ["Eiffel Tower"], "find_nearby",
         {"radius_m": 2000, "amenity_type": "hospital"}),
        ("Schools near Federation Square, Melbourne within 500 m", ["Federation Square, Melbourne"],
         "find_nearby", {"radius_m": 500, "amenity_type": "school"}),
        ("What is the distance from Paris to Rio de Janeiro?", ["Paris", "Rio de Janeiro"], "distance", {}),
        ("How far is Paris, France from London, England?", ["Paris, France", "London, England"], "distance", {}),
        ("Is the Louvre inside Paris?", ["Louvre", "Paris"], "check_relationship", {}),
        ("Weather in New York City", ["New York City"], "weather", {}),
        ("Air quality in Delhi", ["Delhi"], "air_quality", {}),
        ("Any wildfires near Los Angeles", ["Los Angeles"], "fire_detection", {}),
        ("Find fire stations in Berlin", ["Berlin"], "find_nearby", {"amenity_type": "fire_station"}),
        ("Find pharmacies near Times Square within 1.5 km", ["Times Square"], "find_nearby",
         {"radius_m": 1500, "amenity_type": "pharmacy"}),
    ],
)
def test_fallback_parser(goal: str, locations: list[str], intent: str, params: dict) -> None:
    got_locations, got_intent, got_params = GeoAgent._fallback_parse(goal)
    assert got_locations == locations
    assert got_intent == intent
    for key, value in params.items():
        assert got_params[key] == value


# --- GeoAgent end to end --------------------------------------------------------------------


def _agent(launcher: FakeLauncher, overpass: FakeOverpass) -> GeoAgent:
    agent = GeoAgent.__new__(GeoAgent)
    agent.__init__()  # real init, then swap the network-facing parts
    agent._launcher = launcher
    agent._overpass = overpass
    return agent


def test_geoagent_finds_hospitals_within_radius_sorted() -> None:
    near = entity("Near Hospital", offset(EIFFEL, 45, 800))
    mid = entity("Mid Hospital", offset(EIFFEL, 200, 1500))
    far = entity("Far Hospital", offset(EIFFEL, 90, 2600))  # outside 2 km, inside the bbox query
    overpass = FakeOverpass({"hospital": [far, mid, near]})
    launcher = FakeLauncher({"Eiffel Tower": EIFFEL})

    result = _agent(launcher, overpass).run("Find all hospitals within 2km of the Eiffel Tower")

    assert launcher.queries == ["Eiffel Tower"]  # one place, not "Eiffel" and "Tower"
    found = result.findings["nearby"]["Eiffel Tower"]
    assert found["radius_m"] == 2000
    assert [i["name"] for i in found["items"]] == ["Near Hospital", "Mid Hospital"]
    assert found["items"][0]["distance_m"] == pytest.approx(800, abs=2)
    bbox, amenity = overpass.calls[0]
    assert amenity == "hospital"
    south, west, north, east = bbox  # Overpass order, 2 km in every direction
    assert GEOD.inv(west, EIFFEL[1], east, EIFFEL[1])[2] == pytest.approx(4000, rel=0.001)
    assert GEOD.inv(EIFFEL[0], south, EIFFEL[0], north)[2] == pytest.approx(4000, rel=0.001)
    assert result.summary  # rule-based summary even without the LLM


def test_geoagent_distance_between_two_places() -> None:
    launcher = FakeLauncher({"Paris": (2.3522, 48.8566), "Rio de Janeiro": (-43.1729, -22.9068)})
    result = _agent(launcher, FakeOverpass({})).run("What is the distance from Paris to Rio de Janeiro?")
    expected = GEOD.inv(2.3522, 48.8566, -43.1729, -22.9068)[2]
    text = str(result.findings)
    assert f"{round(expected / 1000)}" in text or f"{expected / 1000:.1f}" in text


def test_geoagent_reports_unknown_place() -> None:
    result = _agent(FakeLauncher({}), FakeOverpass({})).run("Find hospitals near Atlantis")
    assert any(step.error and "Atlantis" in step.error for step in result.steps)


# --- SiteSelector ---------------------------------------------------------------------------------


def _selector(launcher: FakeLauncher, overpass: FakeOverpass) -> SiteSelector:
    selector = SiteSelector.__new__(SiteSelector)
    selector.__init__()
    selector._launcher = launcher
    selector._overpass = overpass
    return selector


def test_site_selector_prefers_sites_close_to_all_criteria() -> None:
    center = (144.9631, -37.8136)
    school_a = entity("School A", offset(center, 0, 300), "school")
    school_b = entity("School B", offset(center, 180, 2500), "school")
    hospital = entity("Hospital", offset(center, 10, 450), "hospital")
    overpass = FakeOverpass({"school": [school_a, school_b], "hospital": [hospital]})

    result = _selector(FakeLauncher({"Melbourne": center}), overpass).find(
        within="Melbourne", near=["school", "hospital"], facility_type="pharmacy", radius_m=3000
    )

    assert result.best is not None
    # School A sits ~160 m from the hospital; School B is ~3 km from it
    assert result.best.name in {"School A area", "Hospital area"}
    names = [c.name for c in result.candidates]
    assert names.index("School B area") > names.index(result.best.name)
    assert all(earlier.score >= later.score for earlier, later in zip(result.candidates, result.candidates[1:], strict=False))


def test_site_selector_penalises_avoided_amenities() -> None:
    center = (144.9631, -37.8136)
    park_quiet = entity("Quiet Park", offset(center, 0, 1000), "park")
    park_busy = entity("Busy Park", offset(center, 180, 1000), "park")
    bar = entity("Bar", offset(center, 180, 1020), "bar")
    overpass = FakeOverpass({"park": [park_quiet, park_busy], "bar": [bar]})

    result = _selector(FakeLauncher({"Melbourne": center}), overpass).find(
        within="Melbourne", near=["park"], avoid=["bar"], radius_m=3000
    )
    scores = {c.name: c.score for c in result.candidates}
    assert scores["Quiet Park area"] > scores["Busy Park area"]


def test_site_selector_unknown_area() -> None:
    result = _selector(FakeLauncher({}), FakeOverpass({})).find(within="Atlantis", near=["school"])
    assert "Could not geocode" in result.summary and result.best is None
