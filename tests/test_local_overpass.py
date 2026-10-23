"""A self-hosted Overpass (GEOSPARK_OVERPASS_URL) for Australia, with the public servers as fallback."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from geospark.agents import amenities
from geospark.agents.amenities import find_amenities
from geospark.knowledge.loaders import OverpassLoader
from geospark.utils.geo import overpass_bbox

LOCAL = "http://geospark-overpass/api/interpreter"
FED_SQ = (-37.8177, 144.9691)
ZURICH = (47.3744, 8.5410)
HOSPITAL = {"elements": [{"type": "node", "id": 1, "lat": -37.80, "lon": 144.96,
                          "tags": {"amenity": "hospital", "name": "Royal Melbourne Hospital"}}]}


@pytest.fixture(autouse=True)
def local_overpass(monkeypatch):
    monkeypatch.setenv("GEOSPARK_OVERPASS_URL", LOCAL)
    OverpassLoader._cache.clear()
    yield
    OverpassLoader._cache.clear()


@pytest.mark.parametrize(("place", "inside"), [
    ((-37.818, 144.969), True), ((-42.88, 147.33), True), ((-10.58, 142.22), True),   # Melbourne, Hobart, Thursday Is
    ((-29.04, 167.95), True), ((-10.45, 105.69), True),                                # Norfolk, Christmas Is
    ((47.37, 8.54), False), ((-9.44, 147.18), False), ((-8.56, 125.57), False),       # Zurich, Port Moresby, Dili
    ((-22.27, 166.45), False), ((-44.67, 167.93), False),                              # Noumea, Milford Sound
])
def test_coverage_is_the_extract_boundary_not_its_rectangle(place, inside) -> None:
    assert OverpassLoader().covers(overpass_bbox(*place, 500)) is inside


def test_no_local_server_configured_means_no_coverage(monkeypatch) -> None:
    monkeypatch.delenv("GEOSPARK_OVERPASS_URL")
    assert OverpassLoader().covers(overpass_bbox(*FED_SQ, 500)) is False


def test_inside_coverage_the_local_server_answers_and_the_public_ones_are_not_asked() -> None:
    with patch.object(OverpassLoader, "_post", return_value=HOSPITAL) as post, \
         patch.object(OverpassLoader, "_race", side_effect=AssertionError("public servers asked")):
        found = OverpassLoader().load_amenities_by_type(overpass_bbox(*FED_SQ, 2000), ["hospital"])
    assert post.call_args.args[0] == LOCAL and post.call_args.args[2] <= OverpassLoader.LOCAL_TIMEOUT_S
    assert [e.name for e in found["hospital"]] == ["Royal Melbourne Hospital"]


def test_an_empty_local_answer_is_used_inside_coverage() -> None:
    with patch.object(OverpassLoader, "_post", return_value={"elements": []}), \
         patch.object(OverpassLoader, "_race", side_effect=AssertionError("public servers asked")):
        found = OverpassLoader().load_amenities_by_type(overpass_bbox(*FED_SQ, 2000), ["hospital"])
    assert found == {"hospital": []}


def test_outside_coverage_the_public_servers_are_asked() -> None:
    with patch.object(OverpassLoader, "_post", side_effect=AssertionError("local server asked")), \
         patch.object(OverpassLoader, "_race", return_value={"elements": []}) as race:
        OverpassLoader().load_amenities_by_type(overpass_bbox(*ZURICH, 2000), ["hospital"])
    assert race.called


def test_a_failing_local_server_falls_back_to_the_public_ones() -> None:
    with patch.object(OverpassLoader, "_post", side_effect=RuntimeError("connection refused")), \
         patch.object(OverpassLoader, "_race", return_value=HOSPITAL) as race:
        found = OverpassLoader().load_amenities_by_type(overpass_bbox(*FED_SQ, 2000), ["hospital"])
    assert race.called and len(found["hospital"]) == 1


def test_public_cooldown_does_not_block_the_local_server() -> None:
    amenities._mark_overpass_down()  # the public servers just refused us
    with patch.object(OverpassLoader, "_post", return_value=HOSPITAL), \
         patch.object(OverpassLoader, "_race", side_effect=AssertionError("public servers asked in cooldown")):
        lookup = find_amenities(*FED_SQ, 2000, ["hospital"])
    assert lookup.source == "openstreetmap-overpass" and len(lookup.by_type["hospital"]) == 1


def test_in_cooldown_a_failing_local_server_does_not_retry_the_public_ones() -> None:
    amenities._mark_overpass_down()
    with patch.object(OverpassLoader, "_post", side_effect=RuntimeError("down")), \
         patch.object(OverpassLoader, "_race", side_effect=AssertionError("public servers asked in cooldown")), \
         patch("geospark.tools.overture.client.query", side_effect=RuntimeError("down")), \
         pytest.raises(amenities.AmenityLookupError):
        find_amenities(*FED_SQ, 2000, ["school"])
