"""Failures found by testing the live site as an outside user, as tests.

- Ask got the height of Mount Kosciuszko wrong: the model typed coordinates from memory.
- Ask said the Eiffel Tower is not in Paris: it compared two points.
- Ask had no tool for "how many hospitals within 1 km" or for the weather.
- Supermarkets, parks and hotels always came back as zero: only amenity=* was queried.
- "Mount Wellington, Hobart" found nothing, and the agent used a peak in New York instead.
- Every flow template failed at its first step, and the run still said "completed".
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from geospark.agents.amenities import AmenityLookup
from geospark.agents.geo_agent import GeoAgent
from geospark.engine.core import answer_to_result
from geospark.flows import FlowRunner, get_template
from geospark.knowledge.entities import SpatialEntity
from geospark.knowledge.loaders import OverpassLoader
from geospark.mcp_servers.launcher import MCPServerLauncher
from geospark.mcp_servers.places import _singular
from geospark.protocol.provenance import Provenance, source_provenance
from geospark.protocol.schema import SpatialContext, SpatialFeature, SpatialOperation, SpatialResult
from geospark.tools.geocoding.nominatim import NominatimGeocoder

EIFFEL = [2.2945, 48.8584]
PARIS = {"type": "Polygon", "coordinates": [[[2.22, 48.81], [2.47, 48.81], [2.47, 48.91], [2.22, 48.91], [2.22, 48.81]]]}
KOSCIUSZKO = [148.2635, -36.4558]


def _geocoded(name: str, coords: list[float]) -> SpatialResult:
    return SpatialResult(
        features=[SpatialFeature(geometry={"type": "Point", "coordinates": coords}, properties={"display_name": name})],
        provenance=[Provenance(source="openstreetmap-nominatim", name="OpenStreetMap Nominatim", licence="ODbL-1.0")],
    )


def _call(tool: str, **args):
    return MCPServerLauncher().handle_tool_call(tool, {"explanation": "test", **args})


# --- Ask: place names instead of coordinates ------------------------------------------------------

def test_is_the_eiffel_tower_in_paris_uses_the_boundary_of_paris() -> None:
    with patch("geospark.agents.amenities.place_boundary", side_effect=lambda n: PARIS if n == "Paris" else None), \
         patch("geospark.engine.core.Engine.execute", return_value=_geocoded("Tour Eiffel", EIFFEL)):
        reply = _call("check_spatial_relationship", place_a="Eiffel Tower", place_b="Paris", relationship="within")
    assert reply["status"] == "success" and reply["result"]["holds"] is True
    assert [p["used"] for p in reply["result"]["places"]] == ["point", "boundary (OpenStreetMap, simplified)"]


def test_a_point_cannot_contain_anything() -> None:
    """The live failure: two geocoded points, so 'within' was always false."""
    eiffel = {"type": "Point", "coordinates": EIFFEL}
    paris_point = {"type": "Point", "coordinates": [2.35, 48.85]}
    reply = _call("check_spatial_relationship", geometry_a=eiffel, geometry_b=paris_point, relationship="within")
    assert reply["status"] == "error" and "no area" in reply["errors"][0]


def test_a_container_without_a_boundary_is_refused_not_answered_no() -> None:
    with patch("geospark.agents.amenities.place_boundary", return_value=None):
        reply = _call("check_spatial_relationship", place_a="Eiffel Tower", place_b="Louvre", relationship="within")
    assert reply["status"] == "error" and "has no boundary" in reply["errors"][0]


def test_elevation_of_a_named_mountain_is_geocoded_on_the_server() -> None:
    def execute(query):
        if query.operation == SpatialOperation.GEOCODE:
            return _geocoded("Mount Kościuszko", KOSCIUSZKO)
        assert list(query.geometry.coordinates[:2]) == KOSCIUSZKO
        return SpatialResult(features=[SpatialFeature(geometry=query.geometry.model_dump(), properties={"elevation_m": 2209.0})],
                             sources=["copernicus-dem-glo30"])

    with patch("geospark.engine.core.Engine.execute", side_effect=execute):
        call = {"tool": "get_elevation", "args": {"place": "Mount Kosciuszko"},
                "result": _call("get_elevation", place="Mount Kosciuszko")}
    assert call["result"]["result"]["elevation_m"] == 2209.0
    result = answer_to_result(SimpleNamespace(answer="2209 m", model="m", tool_calls=[call]), "ollama:m",
                              "What is the elevation of Mount Kosciuszko?")
    assert "unverified_coordinates" not in result.quality
    assert result.features and result.features[0].geometry["coordinates"] == KOSCIUSZKO


def test_elevation_from_remembered_coordinates_is_still_flagged() -> None:
    reply = {"status": "success", "result": {"elevation_m": 1249.4}, "metadata": {}}
    call = {"tool": "get_elevation", "args": {"latitude": -36.8306, "longitude": 148.2979}, "result": reply}
    result = answer_to_result(SimpleNamespace(answer="1249 m", model="m", tool_calls=[call]), "ollama:m",
                              "What is the elevation of Mount Kosciuszko?")
    assert result.quality["unverified_coordinates"] == 1


# --- Ask: nearby places and weather ---------------------------------------------------------------

def _entity(name: str, lon: float, lat: float, kind: str = "hospital") -> SpatialEntity:
    return SpatialEntity(id=name, name=name, entity_type=kind, geometry={"type": "Point", "coordinates": [lon, lat]})


def test_how_many_hospitals_within_1km_counts_only_inside_the_radius() -> None:
    lookup = AmenityLookup(by_type={"hospital": [_entity("Near", 144.9700, -37.8180), _entity("Far", 144.9900, -37.8180)]},
                           source="openstreetmap-overpass", provenance=[source_provenance("openstreetmap-overpass")],
                           radius_m=1000)
    with patch("geospark.agents.amenities.find_amenities", return_value=lookup) as find, \
         patch("geospark.engine.core.Engine.execute", return_value=_geocoded("Federation Square", [144.9691, -37.8177])):
        reply = _call("find_nearby_places", place="Federation Square", types=["Hospitals"], radius_m=1000)
    assert find.call_args.args[3] == ["hospital"]
    body = reply["result"]
    assert body["counts"] == {"hospital": 1} and body["nearest"]["hospital"][0]["name"] == "Near"
    result = answer_to_result(SimpleNamespace(answer="1", model="m", tool_calls=[
        {"tool": "find_nearby_places", "args": {"place": "Federation Square"}, "result": reply}]), "ollama:m", "q")
    assert {f.properties.get("name") for f in result.features} >= {"Near"}


def test_nearby_lookup_failure_is_an_error_not_zero() -> None:
    from geospark.agents.amenities import AmenityLookupError

    with patch("geospark.agents.amenities.find_amenities", side_effect=AmenityLookupError("both down")):
        reply = _call("find_nearby_places", latitude=-37.8, longitude=144.9, types=["school"])
    assert reply["status"] == "error"


def test_everyday_words_become_openstreetmap_values() -> None:
    assert [_singular(w) for w in ("Pharmacies", "gyms", "doctors", "bus stops", "cafes")] == [
        "pharmacy", "fitness_centre", "doctors", "bus_stop", "cafe"]


def test_weather_for_a_named_place() -> None:
    from geospark.data_channels.base import ChannelResult

    async def search(self, **kwargs):
        assert round(kwargs["lat"], 2) == -42.88
        return ChannelResult(channel="weather", source="open-meteo", features=[
            {"type": "current_weather", "temperature_c": 12.5}, {"type": "daily_forecast", "date": "2026-10-25"}])

    with patch("geospark.data_channels.weather.WeatherChannel.search", search), \
         patch("geospark.engine.core.Engine.execute", return_value=_geocoded("Hobart", [147.3281, -42.8825])):
        reply = _call("get_weather", place="Hobart")
    assert reply["status"] == "success"
    assert reply["result"]["current"]["temperature_c"] == 12.5 and len(reply["result"]["forecast"]) == 1


def test_a_failed_call_that_was_retried_correctly_does_not_mark_the_answer_partial() -> None:
    """Lat/lon swapped on the first call, fixed on the second: the answer is complete."""
    failed = {"status": "error", "error": {"message": "coordinates outside [-180, 180]"}}
    ok = {"status": "success", "result": {"distance_m": 713860.0}, "metadata": {}}
    calls = [{"tool": "calculate_distance", "args": {}, "result": failed},
             {"tool": "calculate_distance", "args": {}, "result": ok}]
    result = answer_to_result(SimpleNamespace(answer="713.86 km", model="m", tool_calls=calls), "ollama:m", "q")
    assert "failed_tools" not in result.quality
    assert any("retried successfully" in w for w in result.warnings)


# --- OpenStreetMap: not everything is an amenity ---------------------------------------------------

def test_supermarkets_and_parks_are_queried_by_their_own_keys() -> None:
    elements = {"elements": [
        {"type": "node", "id": 1, "lat": -37.80, "lon": 144.96, "tags": {"shop": "supermarket", "name": "Coles"}},
        {"type": "node", "id": 2, "lat": -37.80, "lon": 144.96, "tags": {"leisure": "park", "name": "Carlton Gardens"}},
        {"type": "node", "id": 3, "lat": -37.80, "lon": 144.96, "tags": {"amenity": "school", "name": "A school"}},
    ]}
    with patch.object(OverpassLoader, "_query", return_value=elements) as query:
        found = OverpassLoader().load_amenities_by_type((-37.81, 144.95, -37.79, 144.97), ["supermarket", "park", "school"])
    ql = query.call_args.args[0]
    assert '["shop"~"^(supermarket)$"]' in ql and '["leisure"~"^(park)$"]' in ql and '["amenity"~"^(school)$"]' in ql
    assert {k: [e.name for e in v] for k, v in found.items()} == {
        "supermarket": ["Coles"], "park": ["Carlton Gardens"], "school": ["A school"]}


# --- Geocoding "Mount Wellington, Hobart" ----------------------------------------------------------

def test_a_name_in_an_area_is_searched_inside_that_area() -> None:
    peak = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [147.2373, -42.8960]},
            "properties": {"display_name": "kunanyi / Mount Wellington, Tasmania", "type": "peak", "importance": 0.4}}
    hobart = {"type": "Feature", "bbox": [147.0, -43.0, 147.5, -42.7], "geometry": {"type": "Point", "coordinates": [147.33, -42.88]},
              "properties": {"display_name": "Hobart"}}

    def get_json(path, params, timeout=10):
        if params["q"] == "Mount Wellington, Hobart":
            return {"features": []}
        if params["q"] == "Hobart":
            return {"features": [hobart]}
        assert params["q"] == "Mount Wellington" and params["bounded"] == 1
        return {"features": [peak]}

    with patch("geospark.tools.geocoding.client.get_json", side_effect=get_json):
        from geospark.protocol.schema import SpatialQuery

        result = NominatimGeocoder().execute(SpatialQuery(operation=SpatialOperation.GEOCODE,
                                                          metadata={"query": "Mount Wellington, Hobart"}))
    assert result.features[0].geometry["coordinates"] == [147.2373, -42.8960]
    assert "No exact match" in result.warnings[0]


# --- GeoAgent ------------------------------------------------------------------------------------------

def test_the_agent_keeps_a_comma_joined_place_together() -> None:
    goal = "What is the elevation of Mount Wellington, Hobart?"
    assert GeoAgent._join_comma_places(goal, ["Mount Wellington", "Hobart"], "elevation") == ["Mount Wellington, Hobart"]
    # a distance between two places keeps both
    goal = "How far is Paris, France from London, UK?"
    assert GeoAgent._join_comma_places(goal, ["Paris", "France", "London", "UK"], "distance") == ["Paris, France", "London, UK"]


def test_an_elevation_question_is_not_a_nearby_search() -> None:
    _, intent, _ = GeoAgent._fallback_parse("What is the elevation of Mount Wellington, Hobart?")
    assert intent == "elevation"
    assert GeoAgent._asks_elevation("How high is the summit above sea level?")
    assert not GeoAgent._asks_elevation("Find hospitals near Hobart")


# --- Flows -----------------------------------------------------------------------------------------

def _engine_for_templates():
    engine = MagicMock()
    engine.available_tools = ["geocoder", "terrain"]

    def execute(query):
        if query.operation == SpatialOperation.GEOCODE:
            coords = {"Paris, France": [2.35, 48.86], "London, UK": [-0.13, 51.51]}[query.metadata["query"]]
            return _geocoded(query.metadata["query"], coords)
        if query.operation == SpatialOperation.DISTANCE:
            assert query.geometry is not None and query.metadata["geometry_b"]["coordinates"] == [-0.13, 51.51]
            return SpatialResult(features=[SpatialFeature(geometry=query.geometry.model_dump(),
                                                          properties={"distance_km": 343.5})],
                                 spatial_context=SpatialContext(summary="ok"))
        raise AssertionError(query.operation)

    engine.execute.side_effect = execute
    return engine


def test_the_distance_template_measures_and_routes() -> None:
    run = FlowRunner(engine=_engine_for_templates()).run(get_template("distance_analysis", max_distance_km=300))
    assert run.status == "completed", run.errors
    assert run.step_results["calculate_distance"]["values"]["distance_km"] == 343.5
    assert run.step_results["compare_threshold"]["parameters"]["distance"] == 343.5
    assert run.step_results["compare_threshold"]["routes_taken"] == ["over_threshold"]


def test_a_failed_step_fails_the_run_and_its_dependents_are_not_run() -> None:
    engine = MagicMock()
    engine.available_tools = ["geocoder"]
    engine.execute.return_value = SpatialResult(errors=["Geocoding service unavailable"])
    run = FlowRunner(engine=engine).run(get_template("area_survey"))
    assert run.status == "failed"
    assert run.step_results["elevation"]["status"] == "skipped"
    assert engine.execute.call_count == 1


def test_the_ndvi_template_says_it_cannot_finish() -> None:
    engine = MagicMock()
    engine.available_tools = ["geocoder", "ndvi"]

    def execute(query):
        if query.operation == SpatialOperation.GEOCODE:
            return _geocoded("Valencia", [-0.37, 39.47])
        return SpatialResult(features=[SpatialFeature(geometry={"type": "Point", "coordinates": [-0.37, 39.47]},
                                                      properties={"scene_id": "S2A"})])

    engine.execute.side_effect = execute
    run = FlowRunner(engine=engine).run(get_template("vegetation_monitor"))
    assert run.status == "failed"
    assert "Missing input" in run.step_results["threshold_check"]["errors"][0]
    assert any("partial" in w for w in run.step_results["ndvi"]["warnings"])


def test_an_unknown_template_is_404_not_500() -> None:
    from geospark import api

    client = TestClient(api.app)
    assert client.get("/api/v1/flows/templates/nope").status_code == 404
    assert client.post("/api/v1/flows/templates/nope/run", json={}).status_code == 404


def test_overture_supermarkets_are_grocery_stores() -> None:
    """Overture has no "supermarket" category: Coles and Woolworths are food_and_beverage_store /
    grocery_store, so the fallback reported no supermarkets near Federation Square."""
    from geospark.agents.amenities import _from_overture

    def overture(theme, lat, lon, radius_m, category):
        assert category == "grocery_store"
        places = [("Coles", "food_and_beverage_store", "grocery_store", 0.99),
                  ("BWS", "food_and_beverage_store", "liquor_store", 0.8)]
        return SpatialResult(features=[SpatialFeature(
            geometry={"type": "Point", "coordinates": [144.967, -37.817]},
            properties={"name": n, "category": c, "taxonomy": t, "confidence": conf}) for n, c, t, conf in places])

    with patch("geospark.tools.overture.client.query", side_effect=overture):
        lookup = _from_overture(-37.8177, 144.9691, 1000, ["supermarket"])
    assert [e.name for e in lookup.by_type["supermarket"]] == ["Coles"]
