"""Quantities an answer states must trace back to a tool result (small-model safety).

Live: Ask's 7B model reported a 3,136,548 m² buffer as "3,137 square kilometres". A quantity that no
tool returned, even allowing unit changes, rounding, and the sum or difference of two results, marks
the answer partial and is named in a warning.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from geospark.engine.core import answer_to_result


def _call(tool: str, result: dict) -> dict:
    return {"tool": tool, "args": {}, "result": {"status": "success", "result": result, "metadata": {}}}


BUFFER = _call("spatial_operation", {"features": [{"properties": {"area_m2": 3136548.48, "radius_m": 1000}}]})
OPERA_BONDI = _call("calculate_distance", {"distance_m": 6473.2, "distance_km": 6.4732})
GOLD = _call("calculate_distance", {"distance_m": 70580.0})
SUNSHINE = _call("calculate_distance", {"distance_m": 90520.0})


def _flags(answer: str, calls: list, question: str = "q"):
    result = answer_to_result(SimpleNamespace(answer=answer, model="m", tool_calls=calls), "ollama:m", question)
    return result.quality.get("unsupported_numbers")


@pytest.mark.parametrize(("answer", "calls"), [
    ("About 6.47 kilometres or 6,473 metres.", [OPERA_BONDI]),
    ("Roughly 6.5 km.", [OPERA_BONDI]),
    ("About 6 km, i.e. 6000 m.", [OPERA_BONDI]),  # a round number is stated to its own precision
    ("The buffer covers about 3.14 km² (3,136,548 m²), radius 1000 m.", [BUFFER]),
    ("The Gold Coast (70.58 km) is about 20 km closer than the Sunshine Coast (90.52 km).", [GOLD, SUNSHINE]),
    ("Within the 500 m you asked about there are 3 cafes.", [OPERA_BONDI]),
])
def test_traceable_quantities_pass(answer, calls) -> None:
    assert _flags(answer, calls, "Cafes within 500 m?") is None


@pytest.mark.parametrize(("answer", "calls", "flagged"), [
    ("The buffer covers approximately 3,137 square kilometers.", [BUFFER], "3,137 square kilometers"),
    ("It is 64.7 km away.", [OPERA_BONDI], "64.7 km"),
    ("The Gold Coast is 30 km closer.", [GOLD, SUNSHINE], "30 km"),
])
def test_quantities_no_tool_returned_are_flagged(answer, calls, flagged) -> None:
    assert _flags(answer, calls) == [flagged]


def test_no_tools_means_nothing_to_check_against() -> None:
    assert _flags("Paris is about 340 km from London.", []) is None


def test_ask_marks_such_an_answer_partial() -> None:
    from geospark import api

    result = answer_to_result(SimpleNamespace(answer="It covers 3,137 square kilometres.", model="m",
                                              tool_calls=[BUFFER]), "ollama:m", "How big is a 1 km buffer?")
    with patch.object(api.get_engine(), "ask", return_value=result):
        body = TestClient(api.app).post("/api/v1/ask", json={"question": "How big is a 1 km buffer?"}).json()
    assert body["status"] == "partial" and any("3,137 square kilometres" in w for w in body["warnings"])


def test_space_grouped_thousands_are_read_as_one_number() -> None:
    melb_perth = _call("calculate_distance", {"distance_m": 2726638.6032, "distance_km": 2726.6386})
    assert _flags("Geodesic distance: 2 726 638.60 m, or 2\u202f726.64 km.", [melb_perth]) is None


def test_an_empty_answer_after_tool_calls_is_cannot_answer() -> None:
    """Live (workstation, Qwen 3.5 4B): tool calls, then no answer text; it was marked ok."""
    from geospark import api

    result = answer_to_result(SimpleNamespace(answer="", model="m", tool_calls=[OPERA_BONDI]), "ollama:m", "How far?")
    assert result.quality["no_answer"] is True
    with patch.object(api.get_engine(), "ask", return_value=result):
        body = TestClient(api.app).post("/api/v1/ask", json={"question": "How far?"}).json()
    assert body["status"] == "cannot_answer"


def test_numbers_from_a_tools_own_caveat_are_traceable() -> None:
    """A model repeating GeoSpark's caveat ("about 0.08 m in capital cities") isn't inventing a number."""
    call = {"tool": "convert_height", "args": {}, "result": {"status": "success", "result": {"height_m": 35.2574},
                                                              "metadata": {"warnings": ["... about 0.08 m in capital cities)."]}}}
    assert _flags("AHD 35.26 m; uncertainty about 0.08 m.", [call]) is None


def test_an_answer_that_contradicts_itself_is_partial() -> None:
    """Live (Qwen 3.5 4B): first line 'Sunshine Coast is closer', table and last line: Gold Coast."""
    answer = ("**Sunshine Coast is closer to Brisbane than Gold Coast.** Gold Coast ~70.6 km, Sunshine Coast ~90.5 km. "
              "Therefore, **Gold Coast is closer to Brisbane by approximately 19.9 kilometers**.")
    result = answer_to_result(SimpleNamespace(answer=answer, model="m", tool_calls=[GOLD, SUNSHINE]), "ollama:m", "q")
    assert result.quality["self_contradiction"] == ["Sunshine Coast is closer", "Gold Coast is closer"]
    fine = "The Gold Coast is closer (70.6 km) than the Sunshine Coast (90.5 km). Gold Coast is closer by 19.9 km."
    assert "self_contradiction" not in answer_to_result(
        SimpleNamespace(answer=fine, model="m", tool_calls=[GOLD, SUNSHINE]), "ollama:m", "q").quality


def test_one_point_can_be_given_without_the_outer_list() -> None:
    """Live (Qwen 3.5 4B): it always sent [x, y]; the tool failed and the model invented EPSG codes."""
    from geospark import geodesy

    assert geodesy.transform("EPSG:28355", "EPSG:7855", [321242.045, 5812466.767]).coordinates[0][0] == pytest.approx(321242.536, abs=0.002)
    with pytest.raises(geodesy.GeodesyError, match="list of points"):
        geodesy.transform("EPSG:28355", "EPSG:7855", "321242, 5812466")


def test_a_comparison_that_contradicts_the_measured_distances_is_partial() -> None:
    """Live (Qwen 3.5 4B): 'Sunshine Coast is closer ... it's actually closer' (the Gold Coast)."""
    gold = {"tool": "calculate_distance", "args": {"place_a": "Brisbane", "place_b": "Gold Coast"},
            "result": {"status": "success", "result": {"distance_m": 70580.0, "places": [{"query": "Brisbane"}, {"query": "Gold Coast"}]}, "metadata": {}}}
    sun = {"tool": "calculate_distance", "args": {"place_a": "Brisbane", "place_b": "Sunshine Coast"},
           "result": {"status": "success", "result": {"distance_m": 90520.0, "places": [{"query": "Brisbane"}, {"query": "Sunshine Coast"}]}, "metadata": {}}}
    wrong = ("**Sunshine Coast is closer to Brisbane** than Gold Coast. The corrected calculation for Gold Coast shows "
             "it's actually closer at approximately 70.6 km compared to Sunshine Coast at approximately 90.5 km.")
    result = answer_to_result(SimpleNamespace(answer=wrong, model="m", tool_calls=[gold, sun]), "ollama:m", "q")
    assert result.quality["contradicts_tools"] == ["Sunshine Coast is closer"]
    right = "The Gold Coast is closer to Brisbane (70.6 km) than the Sunshine Coast (90.5 km)."
    assert "contradicts_tools" not in answer_to_result(
        SimpleNamespace(answer=right, model="m", tool_calls=[gold, sun]), "ollama:m", "q").quality


def test_a_stated_precision_is_not_a_measurement() -> None:
    assert _flags("Easting 321242.536 m (rounded to 0.001 m), accurate to ±0.01 m.",
                  [_call("transform_coordinates", {"coordinates": [[321242.5357, 5812468.2389]]})]) is None


# --- reading two places together ("Brisbane to Gold Coast") ------------------------------------

def _found(*candidates):
    from geospark.protocol.schema import SpatialFeature, SpatialResult

    return SpatialResult(features=[SpatialFeature(geometry={"type": "Point", "coordinates": [lon, lat]},
                                                  properties={"display_name": name, "importance": imp, "country_code": cc})
                                   for name, lon, lat, imp, cc in candidates])


BRISBANE = _found(("Brisbane, Queensland, Australia", 153.0235, -27.4690, 0.70, "au"))
GOLD_COAST = _found(("Ghana", -1.0, 7.9, 0.75, "gh"), ("Gold Coast, Queensland, Australia", 153.4146, -28.0024, 0.55, "au"))


def _distance(names, monkeypatch, prefer=""):
    from geospark.mcp_servers.launcher import MCPServerLauncher

    monkeypatch.setenv("GEOSPARK_GEOCODE_PREFER_COUNTRY", prefer)
    with patch("geospark.engine.core.Engine.execute", side_effect=lambda q: names[q.metadata["query"]]):
        return MCPServerLauncher().handle_tool_call(
            "calculate_distance", {"explanation": "t", "place_a": "Brisbane", "place_b": "Gold Coast"})


def test_the_other_place_decides_an_ambiguous_name(monkeypatch) -> None:
    """Live (no preferred country): 'Gold Coast' was Ghana, 16,549 km from Brisbane, with no warning."""
    reply = _distance({"Brisbane": BRISBANE, "Gold Coast": GOLD_COAST}, monkeypatch)
    assert reply["result"]["distance_m"] == pytest.approx(70_600, rel=0.01)
    assert "same country" in reply["metadata"]["warnings"][0]


def test_the_operators_country_is_never_swapped_away(monkeypatch) -> None:
    """'London to Perth' on an Australian server stays Perth, Western Australia."""
    london = _found(("Greater London, England", -0.1278, 51.5074, 0.85, "gb"))
    perth = _found(("Perth, Western Australia", 115.8605, -31.9505, 0.70, "au"), ("Perth, Scotland", -3.4372, 56.3950, 0.62, "gb"))
    from geospark.mcp_servers.launcher import MCPServerLauncher

    monkeypatch.setenv("GEOSPARK_GEOCODE_PREFER_COUNTRY", "au")
    with patch("geospark.engine.core.Engine.execute", side_effect=lambda q: {"London": london, "Perth": perth}[q.metadata["query"]]):
        reply = MCPServerLauncher().handle_tool_call("calculate_distance", {"explanation": "t", "place_a": "London", "place_b": "Perth"})
    assert reply["result"]["distance_m"] > 14_000_000
