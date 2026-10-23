"""The agent failures found on the live site, as tests.

- The public Overpass servers refuse or time out under load, so nearby-place lookups failed
  and the Spatial Report and Site Selector came back empty.
- The Site Selector then ranked an invented "city center" and the model explained why it was
  near a hospital and a school.
- The coordinator read "Melbourne CBD near schools" as a place name, and sent
  "Analyze Federation Square" to the generic agent, which looked up hospitals.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from geospark.agents import amenities
from geospark.agents.amenities import AmenityLookupError, find_amenities
from geospark.agents.coordinator import (
    AgentCoordinator,
    classify_intent,
    parse_site_goal,
    report_location,
)
from geospark.agents.site_selector import SiteSelector
from geospark.knowledge.entities import SpatialEntity
from geospark.protocol.provenance import source_provenance
from geospark.protocol.schema import SpatialFeature, SpatialResult

FED_SQ = (-37.8177, 144.9691)


class DownOverpass:
    calls = 0

    def load_amenities_by_type(self, bbox, types, timeout=None):
        DownOverpass.calls += 1
        raise RuntimeError("Overpass API request failed: [Errno 61] Connection refused")


def overture_places(lat, lon, radius_m, category=None, **_):
    """What Overture returns for a category search: some matches, some broader neighbours."""
    rows = {
        "pharmacy": [("Flinders St Pharmacy", "pharmacy_and_drug_store", 0.95), ("Pop-up Chemist", "pharmacy", 0.5),
                     ("Collins Chemist", "pharmacy", 0.8)],
        "school": [("Melbourne High", "high_school", 0.9), ("Driving School", "place_of_learning", 0.9)],
    }[category]
    result = SpatialResult(provenance=[source_provenance("overture-maps")])
    for i, (name, cat, conf) in enumerate(rows):
        result.features.append(SpatialFeature(
            geometry={"type": "Point", "coordinates": [lon + 0.001 * (i + 1), lat]},
            properties={"name": name, "category": cat, "confidence": conf, "id": f"{category}-{i}"}))
    return result


def _overture(theme, lat, lon, radius_m, category=None, limit=None):
    assert theme == "places"
    overture_places.last_radius = radius_m
    return overture_places(lat, lon, radius_m, category)


# --- amenity lookups: OpenStreetMap first, Overture Maps when it fails ------------------------

def test_overpass_failure_falls_back_to_overture_with_strict_categories() -> None:
    with patch("geospark.tools.overture.client.query", side_effect=_overture):
        lookup = find_amenities(*FED_SQ, 3000, ["pharmacy", "school"], DownOverpass())
    assert lookup.source == "overture-maps"
    assert [e.name for e in lookup.by_type["pharmacy"]] == ["Flinders St Pharmacy", "Collins Chemist"]  # 0.5 dropped
    assert [e.name for e in lookup.by_type["school"]] == ["Melbourne High"]  # driving school is not a school
    assert overture_places.last_radius == 2000 and lookup.radius_m == 2000  # Overture's cap, and it says so
    assert any("Overture Maps" in w for w in lookup.warnings) and any("2000 m" in w for w in lookup.warnings)
    assert lookup.provenance[0].source == "overture-maps"


def test_a_failed_overpass_is_skipped_for_a_while() -> None:
    DownOverpass.calls = 0
    with patch("geospark.tools.overture.client.query", side_effect=_overture):
        find_amenities(*FED_SQ, 1000, ["school"], DownOverpass())
        find_amenities(*FED_SQ, 1000, ["school"], DownOverpass())
    assert DownOverpass.calls == 1  # the second request went straight to Overture


def test_when_both_sources_fail_it_says_so() -> None:
    with patch("geospark.tools.overture.client.query", side_effect=RuntimeError("S3 unreachable")), \
         pytest.raises(AmenityLookupError, match="Overture Maps also failed"):
        find_amenities(*FED_SQ, 1000, ["school"], DownOverpass())


def test_overpass_is_used_when_it_answers() -> None:
    class UpOverpass:
        def load_amenities_by_type(self, bbox, types, timeout=None):
            assert timeout == amenities.OVERPASS_TIMEOUT_S  # a bounded wait, not the default 40 s
            return {t: [SpatialEntity(id="1", name="OSM Hospital", entity_type=t,
                                      geometry={"type": "Point", "coordinates": [144.97, -37.818]})] for t in types}

    lookup = find_amenities(*FED_SQ, 1000, ["hospital"], UpOverpass())
    assert lookup.source == "openstreetmap-overpass" and not lookup.warnings


# --- Site Selector: never rank an invented place ------------------------------------------------

def _selector() -> SiteSelector:
    selector = SiteSelector.__new__(SiteSelector)
    selector.__init__()

    class Launcher:
        def handle_tool_call(self, name, args):
            return {"status": "success", "result": {"features": [
                {"geometry": {"type": "Point", "coordinates": [8.541, 47.3744]}, "properties": {}}]}}

    selector._launcher = Launcher()
    selector._overpass = DownOverpass()
    return selector


def test_site_selector_reports_a_failed_lookup_instead_of_inventing_a_site() -> None:
    llm = patch("httpx.post", side_effect=AssertionError("the model must not narrate missing data"))
    with patch("geospark.tools.overture.client.query", side_effect=RuntimeError("down")), llm:
        result = _selector().find("Zurich", near=["hospital", "school"], facility_type="pharmacy")
    assert result.candidates == [] and result.best is None
    assert result.data_gaps == ["hospital", "school"]
    assert "could not be retrieved" in result.summary


def test_site_selector_with_nothing_found_ranks_nothing() -> None:
    empty = SpatialResult(provenance=[source_provenance("overture-maps")])
    with patch("geospark.tools.overture.client.query", return_value=empty), \
         patch("httpx.post", side_effect=AssertionError("no model call for an empty result")):
        result = _selector().find("Zurich", near=["school"], facility_type="pharmacy")
    assert result.candidates == [] and "No school found" in result.summary


def test_site_selector_needs_something_to_be_near() -> None:
    result = _selector().find("Zurich", near=[], facility_type="pharmacy")
    assert result.candidates == [] and "near" in result.summary


# --- Coordinator: route and read the sentence correctly ---------------------------------------

@pytest.mark.parametrize("goal", ["Analyze Federation Square, Melbourne", "Profile Fitzroy, Melbourne",
                                  "Report on Bondi Beach", "What is it like around Southbank?"])
def test_place_analysis_goes_to_the_spatial_report(goal: str) -> None:
    assert classify_intent(goal, AgentCoordinator().registry).matched_agent == "spatial_report"


@pytest.mark.parametrize(("goal", "place"), [
    ("Analyze Federation Square, Melbourne", "Federation Square, Melbourne"),
    ("Tell me about Bondi Beach", "Bondi Beach"),
    ("What is it like around Fitzroy?", "Fitzroy"),
])
def test_report_location_drops_the_request_words(goal: str, place: str) -> None:
    assert report_location(goal) == place


@pytest.mark.parametrize(("goal", "expected"), [
    ("Find the best location for a cafe in Melbourne CBD near schools",
     {"facility_type": "cafe", "within": "Melbourne CBD", "near": ["school"]}),
    ("Where should I open a pharmacy in Zurich near hospitals and schools but away from industrial areas?",
     {"facility_type": "pharmacy", "within": "Zurich", "near": ["hospital", "school"], "avoid": ["industrial_area"]}),
    ("Best spot for a gym in Fitzroy, Melbourne close to parks and cafes",
     {"facility_type": "gym", "within": "Fitzroy, Melbourne", "near": ["park", "cafe"]}),
])
def test_site_goal_parsing(goal: str, expected: dict) -> None:
    assert parse_site_goal(goal) == expected


def test_site_selection_is_still_recognised() -> None:
    goal = "Find the best location for a cafe in Melbourne CBD near schools"
    assert classify_intent(goal, AgentCoordinator().registry).matched_agent == "site_selector"


def test_hospitals_are_never_taken_from_overture() -> None:
    """Overture returned private practices, a bar and a hospital in Cameroon near the Eiffel Tower."""
    with patch("geospark.tools.overture.client.query", side_effect=_overture) as overture:
        mixed = find_amenities(*FED_SQ, 2000, ["hospital", "school"], DownOverpass())
    assert "hospital" not in mixed.by_type and mixed.unavailable == ["hospital"]
    assert [c.kwargs.get("category") for c in overture.call_args_list] == ["school"]  # never asked for hospitals
    amenities.reset()
    with patch("geospark.tools.overture.client.query", side_effect=_overture), \
         pytest.raises(AmenityLookupError, match="no reliable fallback"):
        find_amenities(*FED_SQ, 2000, ["hospital"], DownOverpass())


def test_site_selector_does_not_rank_on_hospitals_it_could_not_retrieve() -> None:
    with patch("geospark.tools.overture.client.query", side_effect=_overture), \
         patch("httpx.post", side_effect=AssertionError("no model call")):
        result = _selector().find("Zurich", near=["hospital"], facility_type="pharmacy")
    assert result.candidates == [] and "could not be" in result.summary


def test_report_counts_every_service_not_only_the_listed_ones() -> None:
    from geospark.agents.spatial_report import SpatialReport, WeatherSnapshot

    class Launcher:
        def handle_tool_call(self, name, args):
            if name == "geocode":
                return {"status": "success", "result": {"features": [{
                    "geometry": {"type": "Point", "coordinates": [144.969, -37.818]},
                    "properties": {"display_name": "Federation Square"}}]}}
            return {"status": "success", "result": {"elevation_m": 20.0}}

    class Overpass:  # 40 restaurants, all closer than the 5 pharmacies
        def load_amenities_by_type(self, bbox, services, timeout=None):
            def ent(kind, i, d):
                return SpatialEntity(id=f"{kind}{i}", name=f"{kind} {i}", entity_type=kind,
                                     geometry={"type": "Point", "coordinates": [144.969 + d, -37.818]})
            out = {s: [] for s in services}
            out["restaurant"] = [ent("restaurant", i, 0.0001 * (i + 1)) for i in range(40)]
            out["pharmacy"] = [ent("pharmacy", i, 0.006 + 0.0001 * i) for i in range(5)]
            return out

    report = SpatialReport.__new__(SpatialReport)
    report.__init__()
    report._launcher, report._overpass = Launcher(), Overpass()
    with patch.object(SpatialReport, "_fetch_weather", return_value=WeatherSnapshot(temperature_c=20.0)), \
         patch.object(SpatialReport, "_fetch_air_quality", return_value=None), \
         patch("httpx.post", side_effect=ConnectionError("no LLM")):
        result = report.analyze("Federation Square", radius_m=2000)
    assert result.counts_by_type["restaurant"] == 40 and result.counts_by_type["pharmacy"] == 5
    listed = [n.amenity_type for n in result.nearby]
    assert listed.count("restaurant") == 10 and listed.count("pharmacy") == 5  # restaurants don't crowd out the rest


def test_site_selector_does_not_rank_on_part_of_the_criteria() -> None:
    with patch("geospark.tools.overture.client.query", side_effect=_overture), \
         patch("httpx.post", side_effect=AssertionError("no model call")):
        result = _selector().find("Zurich", near=["hospital", "school"], facility_type="pharmacy")
    assert result.candidates == [] and result.data_gaps == ["hospital"]
    assert "hospital could not be retrieved" in result.summary


def test_geoagent_never_turns_a_failed_lookup_into_none_found() -> None:
    from geospark.agents.geo_agent import AgentResult, AgentStep, GeoAgent

    result = AgentResult(goal="Find all hospitals within 2km of the Eiffel Tower",
                         findings={"geocoded": {"Eiffel Tower": {"coordinates": [2.29, 48.86]}}},
                         steps=[AgentStep(action="find_nearby", description="Search hospital near Eiffel Tower",
                                          error="Nearby places could not be retrieved")])
    agent = GeoAgent.__new__(GeoAgent)
    agent.__init__()
    with patch("httpx.post", side_effect=AssertionError("the model must not be asked")):
        summary = agent._generate_summary(result)
    assert summary.startswith("This could not be answered") and "none" not in summary.lower()


@pytest.mark.parametrize(("goal", "radius"), [
    ("Find all hospitals within 2km of Federation Square, Melbourne", 2000),
    ("Schools near Southbank within 500 m", 500),
    ("Pharmacies within 1.5 kilometres of Bondi Beach", 1500),
])
def test_a_stated_distance_beats_the_models_guess(goal: str, radius: int) -> None:
    """Live, the model sometimes dropped "within 2km" and searched its default 3 km."""
    from unittest.mock import MagicMock

    from geospark.agents.geo_agent import GeoAgent

    reply = MagicMock()
    reply.json.return_value = {"message": {"content": json.dumps({
        "locations": ["Federation Square"], "intent": "find_nearby",
        "params": {"amenity_type": "hospital", "radius_m": 3000}})}}
    agent = GeoAgent.__new__(GeoAgent)
    agent.__init__()
    with patch("httpx.post", return_value=reply):
        _, _, params = agent._parse_goal(goal)
    assert params["radius_m"] == radius


def test_without_a_stated_distance_the_models_value_stands() -> None:
    from unittest.mock import MagicMock

    from geospark.agents.geo_agent import GeoAgent

    reply = MagicMock()
    reply.json.return_value = {"message": {"content": json.dumps({
        "locations": ["Fitzroy"], "intent": "find_nearby", "params": {"amenity_type": "cafe", "radius_m": 1000}})}}
    agent = GeoAgent.__new__(GeoAgent)
    agent.__init__()
    with patch("httpx.post", return_value=reply):
        _, _, params = agent._parse_goal("Cafes near Fitzroy")
    assert params["radius_m"] == 1000
