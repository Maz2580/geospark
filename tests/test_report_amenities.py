"""Tests for the location report's amenity lookup and how it reports failure."""

from unittest.mock import MagicMock, patch

import httpx

from geospark.agents.spatial_report import AccessibilityScore, LocationReport, SpatialReport
from geospark.knowledge.loaders import OverpassLoader

BBOX = (-28.83, 153.25, -28.79, 153.30)

OVERPASS_REPLY = {
    "elements": [
        # A hospital mapped as a building outline: no lat/lon, only a centre
        {"type": "way", "id": 1, "center": {"lat": -28.807, "lon": 153.291},
         "tags": {"amenity": "hospital", "name": "Lismore Base Hospital"}},
        {"type": "node", "id": 2, "lat": -28.81, "lon": 153.28,
         "tags": {"amenity": "school", "name": "Lismore Public School"}},
        {"type": "node", "id": 3, "lat": -28.81, "lon": 153.28, "tags": {"amenity": "cafe"}},
    ]
}


def _response(status: int, payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("bad", request=MagicMock(), response=resp)
    return resp


class TestOverpassLoader:
    def test_identifies_itself_and_queries_ways_as_well_as_nodes(self) -> None:
        with patch("geospark.knowledge.loaders.httpx.post", return_value=_response(200, OVERPASS_REPLY)) as post:
            OverpassLoader().load_amenities_by_type(BBOX, ["hospital", "school"])

        kwargs = post.call_args.kwargs
        assert "GeoSpark" in kwargs["headers"]["User-Agent"]
        assert 'nwr["amenity"~"^(hospital|school)$"]' in kwargs["data"]["data"]
        assert "out center;" in kwargs["data"]["data"]

    def test_groups_by_type_and_keeps_outline_mapped_places(self) -> None:
        with patch("geospark.knowledge.loaders.httpx.post", return_value=_response(200, OVERPASS_REPLY)):
            found = OverpassLoader().load_amenities_by_type(BBOX, ["hospital", "school", "police"])

        assert [e.name for e in found["hospital"]] == ["Lismore Base Hospital"]
        assert found["hospital"][0].geometry == {"type": "Point", "coordinates": [153.291, -28.807]}
        assert [e.name for e in found["school"]] == ["Lismore Public School"]
        assert found["police"] == []

    def test_falls_back_to_the_second_endpoint(self) -> None:
        replies = [_response(504), _response(200, OVERPASS_REPLY)]
        with patch("geospark.knowledge.loaders.httpx.post", side_effect=replies) as post:
            found = OverpassLoader().load_amenities(BBOX, "hospital")

        assert post.call_count == 2
        assert len(found) == 1

    def test_raises_when_every_endpoint_fails(self) -> None:
        with patch("geospark.knowledge.loaders.httpx.post", side_effect=httpx.ConnectError("down")):
            try:
                OverpassLoader().load_amenities_by_type(BBOX, ["hospital"])
            except RuntimeError as err:
                assert "Overpass" in str(err)
            else:
                raise AssertionError("a failed lookup must raise, not return nothing")


class TestReportDoesNotInventAbsence:
    def _reporter(self) -> SpatialReport:
        reporter = SpatialReport.__new__(SpatialReport)
        reporter._ollama_url = "http://ollama.invalid"
        reporter._model = "test"
        return reporter

    def test_prompt_marks_failed_lookups_as_not_available(self) -> None:
        report = LocationReport(
            query="Lismore", address="Lismore, NSW", elevation_m=11.7, radius_m=2000,
            data_gaps=["nearby services", "weather", "air quality"],
            accessibility=[AccessibilityScore(service="hospital", checked=False)],
        )
        captured = {}

        def fake_post(url, json, timeout):
            captured["prompt"] = json["messages"][0]["content"]
            reply = MagicMock()
            reply.json.return_value = {"message": {"content": "ok"}}
            return reply

        with patch("httpx.post", side_effect=fake_post):
            self._reporter()._generate_narrative(report)

        prompt = captured["prompt"]
        assert "hospital: NOT AVAILABLE (lookup failed)" in prompt
        assert "none within search radius" not in prompt
        assert "Weather: NOT AVAILABLE" in prompt
        assert "Air quality: NOT AVAILABLE" in prompt
        assert "Use ONLY the facts listed below" in prompt
        assert "Search radius: 2000m" in prompt

    def test_fallback_text_says_services_could_not_be_checked(self) -> None:
        report = LocationReport(query="Lismore", address="Lismore, NSW", data_gaps=["nearby services"])
        with patch("httpx.post", side_effect=httpx.ConnectError("no llm")):
            text = self._reporter()._generate_narrative(report)

        assert "could not be checked" in text
        assert "Found 0 amenities" not in text
