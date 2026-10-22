"""/ask answers carry the tools' provenance, units, caveats and found places (for the Proof panel)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from geospark.engine.core import answer_to_result
from geospark.mcp_servers.launcher import MCPServerLauncher

GEOCODE_REPLY = {
    "result": {"features": [{"geometry": {"type": "Point", "coordinates": [144.969, -37.818]},
                             "properties": {"display_name": "Federation Square"}}]},
    "metadata": {"status": "ok", "warnings": ["Another match 40 km away"],
                 "provenance": [{"source": "openstreetmap-nominatim", "name": "OpenStreetMap Nominatim",
                                 "licence": "ODbL-1.0"}]},
}


def _answer():
    distance = MCPServerLauncher().handle_tool_call("calculate_distance", {
        "explanation": "test",
        "point_a": {"type": "Point", "coordinates": [144.969, -37.818]},
        "point_b": {"type": "Point", "coordinates": [144.966, -37.815]},
    })
    failed = {"status": "error", "tool": "get_elevation", "error": {"message": "service down"}}
    return SimpleNamespace(answer="It is 425 m.", model="m", tool_calls=[
        {"tool": "geocode", "result": GEOCODE_REPLY},
        {"tool": "geocode", "result": GEOCODE_REPLY},
        {"tool": "calculate_distance", "result": distance},
        {"tool": "get_elevation", "result": failed},
    ])


def test_answer_collects_provenance_units_and_caveats_once() -> None:
    result = answer_to_result(_answer(), "ollama:m")
    assert [p.source for p in result.provenance] == ["openstreetmap-nominatim", "geospark-engine"]
    assert result.spatial_context.units["distance_m"] == "metre"
    assert result.warnings == ["Another match 40 km away", "Tool get_elevation failed: service down"]
    assert len(result.features) == 2 and result.sources[0] == "ollama:m"


def test_ask_endpoint_returns_the_checkable_part() -> None:
    from geospark import api

    with patch.object(api.get_engine(), "ask", return_value=answer_to_result(_answer(), "ollama:m")):
        body = TestClient(api.app).post("/api/v1/ask", json={"question": "How far?"}).json()
    assert body["status"] == "partial"  # a tool failed, so the answer is not fully checked
    assert body["provenance"][0]["licence"] == "ODbL-1.0"
    assert body["features"][0]["geometry"]["coordinates"] == [144.969, -37.818]
    assert body["tools_used"] == ["geocode", "geocode", "calculate_distance", "get_elevation"]


# --- the model must not supply coordinates for named places (Adelaide Oval -> Glenelg) ---------

ADELAIDE_OVAL = [138.5961558, -34.9155946]
GLENELG = [138.5102143, -34.9802]


def _place(name, coords):
    return SpatialResultForTest(name, coords)


class SpatialResultForTest:
    """A geocoder result, as the engine returns it."""

    def __new__(cls, name, coords):
        from geospark.protocol.provenance import Provenance
        from geospark.protocol.schema import SpatialFeature, SpatialResult

        return SpatialResult(
            features=[SpatialFeature(geometry={"type": "Point", "coordinates": coords},
                                     properties={"display_name": name})],
            provenance=[Provenance(source="openstreetmap-nominatim", name="OpenStreetMap Nominatim",
                                   licence="ODbL-1.0")],
        )


def _distance_call(args):
    reply = MCPServerLauncher().handle_tool_call("calculate_distance", {"explanation": "test", **args})
    return {"tool": "calculate_distance", "args": args, "result": reply}


def test_coordinates_the_model_made_up_mark_the_answer_partial() -> None:
    """The live failure: qwen2.5:7b skipped geocode and typed coordinates from memory."""
    invented = {"point_a": {"type": "Point", "coordinates": [138.6007, -34.9285]},
                "point_b": {"type": "Point", "coordinates": [138.5100, -35.0200]}}
    answer = SimpleNamespace(answer="About 12.25 km.", model="m", tool_calls=[_distance_call(invented)])
    result = answer_to_result(answer, "ollama:m", "How far is Adelaide Oval from Glenelg beach?")
    assert result.quality["unverified_coordinates"] == 2
    assert any("no geocode call" in w for w in result.warnings)

    from geospark import api

    with patch.object(api.get_engine(), "ask", return_value=result):
        body = TestClient(api.app).post("/api/v1/ask", json={"question": "q"}).json()
    assert body["status"] == "partial"


def test_coordinates_from_geocode_or_the_question_are_trusted() -> None:
    geocoded = {"tool": "geocode", "args": {"query": "Adelaide Oval"},
                "result": {"result": {"features": [{"geometry": {"type": "Point", "coordinates": ADELAIDE_OVAL},
                                                    "properties": {}}]}, "metadata": {}}}
    from_user = {"point_a": {"type": "Point", "coordinates": ADELAIDE_OVAL},
                 "point_b": {"type": "Point", "coordinates": [151.2153, -33.8568]}}
    answer = SimpleNamespace(answer="...", model="m", tool_calls=[geocoded, _distance_call(from_user)])
    result = answer_to_result(answer, "ollama:m", "Distance from Adelaide Oval to -33.8568, 151.2153?")
    assert "unverified_coordinates" not in result.quality


def test_distance_by_place_name_is_geocoded_on_the_server() -> None:
    names = {"Adelaide Oval": _place("Adelaide Oval, North Adelaide", ADELAIDE_OVAL),
             "Glenelg beach": _place("Glenelg Jetty, Glenelg", GLENELG)}
    with patch("geospark.engine.core.Engine.execute", side_effect=lambda q: names[q.metadata["query"]]):
        call = _distance_call({"place_a": "Adelaide Oval", "place_b": "Glenelg beach"})
    reply = call["result"]["result"]
    assert round(reply["distance_m"]) == 10630  # the geodesic between the two geocoded points
    assert [p["query"] for p in reply["places"]] == ["Adelaide Oval", "Glenelg beach"]
    result = answer_to_result(SimpleNamespace(answer="10.6 km", model="m", tool_calls=[call]), "ollama:m",
                              "How far is Adelaide Oval from Glenelg beach?")
    assert "unverified_coordinates" not in result.quality
    assert {p.source for p in result.provenance} == {"openstreetmap-nominatim", "geospark-engine"}
    assert len(result.features) == 2  # both places go on the map


def test_unknown_place_name_fails_the_tool_instead_of_guessing() -> None:
    from geospark.protocol.schema import SpatialResult

    with patch("geospark.engine.core.Engine.execute", return_value=SpatialResult()):
        reply = MCPServerLauncher().handle_tool_call(
            "calculate_distance", {"explanation": "t", "place_a": "Nowhereville", "place_b": "Glenelg"})
    assert reply["status"] == "error" and "Nowhereville" in reply["errors"][0]
