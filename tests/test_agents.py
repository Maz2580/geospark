"""Tests for autonomous agents — models, channel integration, and intent routing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from geospark.agents.geo_agent import AgentResult, AgentStep, GeoAgent
from geospark.agents.spatial_report import (
    AccessibilityScore,
    AirQualitySnapshot,
    LocationReport,
    NearbyItem,
    SpatialReport,
    WeatherSnapshot,
)

# --- Pydantic Model Tests ---


class TestWeatherSnapshot:
    def test_default_values(self):
        w = WeatherSnapshot()
        assert w.temperature_c is None
        assert w.conditions == ""

    def test_with_data(self):
        w = WeatherSnapshot(
            temperature_c=22.5,
            feels_like_c=21.0,
            humidity_pct=65,
            wind_speed_kmh=12.3,
            precipitation_mm=0.0,
            conditions="Partly cloudy",
        )
        assert w.temperature_c == 22.5
        assert w.conditions == "Partly cloudy"

    def test_serialization(self):
        w = WeatherSnapshot(temperature_c=15.0, conditions="Clear sky")
        d = w.model_dump()
        assert d["temperature_c"] == 15.0
        assert d["conditions"] == "Clear sky"
        assert d["humidity_pct"] is None


class TestAirQualitySnapshot:
    def test_default_values(self):
        aq = AirQualitySnapshot()
        assert aq.pm25 is None
        assert aq.pm25_category == ""

    def test_with_data(self):
        aq = AirQualitySnapshot(
            station_name="Melbourne CBD",
            distance_m=1200.0,
            pm25=8.5,
            pm25_category="Good",
            no2=15.0,
            o3=30.0,
        )
        assert aq.station_name == "Melbourne CBD"
        assert aq.pm25_category == "Good"

    def test_serialization(self):
        aq = AirQualitySnapshot(pm25=12.0, pm25_category="Good")
        d = aq.model_dump()
        assert d["pm25"] == 12.0
        assert d["no2"] is None


class TestLocationReport:
    def test_default_no_channels(self):
        r = LocationReport(query="test")
        assert r.weather is None
        assert r.air_quality is None
        assert r.nearby == []

    def test_with_weather_and_air_quality(self):
        r = LocationReport(
            query="Melbourne",
            coordinates=[144.9631, -37.8136],
            weather=WeatherSnapshot(temperature_c=18.0, conditions="Clear sky"),
            air_quality=AirQualitySnapshot(pm25=6.0, pm25_category="Good"),
        )
        assert r.weather.temperature_c == 18.0
        assert r.air_quality.pm25 == 6.0

    def test_serialization_roundtrip(self):
        r = LocationReport(
            query="Paris",
            coordinates=[2.3522, 48.8566],
            elevation_m=35.0,
            weather=WeatherSnapshot(temperature_c=12.0, conditions="Overcast"),
            air_quality=AirQualitySnapshot(pm25=20.0, pm25_category="Moderate"),
            nearby=[NearbyItem(name="Louvre", amenity_type="museum", distance_m=500)],
            accessibility=[AccessibilityScore(service="hospital", nearest_name="APHP", distance_m=800, available=True)],
        )
        d = r.model_dump()
        assert d["weather"]["temperature_c"] == 12.0
        assert d["air_quality"]["pm25"] == 20.0
        assert len(d["nearby"]) == 1

        # Roundtrip
        r2 = LocationReport.model_validate(d)
        assert r2.weather.conditions == "Overcast"
        assert r2.air_quality.pm25_category == "Moderate"


class TestAgentModels:
    def test_agent_step(self):
        s = AgentStep(action="weather", description="Weather at Paris")
        assert s.error is None
        assert s.duration_s == 0.0

    def test_agent_result(self):
        r = AgentResult(goal="Check weather in London")
        assert r.steps == []
        assert r.findings == {}


# --- SpatialReport Channel Integration Tests ---


class TestSpatialReportWeather:
    def test_fetch_weather_returns_snapshot(self):
        """Weather channel returns valid data → WeatherSnapshot populated."""
        report = SpatialReport.__new__(SpatialReport)

        mock_result = MagicMock()
        mock_result.errors = []
        mock_result.is_empty = False
        mock_result.features = [
            {
                "type": "current_weather",
                "temperature_c": 22.0,
                "feels_like_c": 20.5,
                "humidity_pct": 55,
                "wind_speed_kmh": 15.0,
                "precipitation_mm": 0.0,
                "weather_description": "Clear sky",
            }
        ]

        with patch("asyncio.run", return_value=mock_result), patch("geospark.data_channels.weather.WeatherChannel"):
            result = report._fetch_weather(48.8566, 2.3522)

        assert result is not None
        assert result.temperature_c == 22.0
        assert result.conditions == "Clear sky"

    def test_fetch_weather_returns_none_on_error(self):
        """Weather channel fails → returns None gracefully."""
        report = SpatialReport.__new__(SpatialReport)

        mock_result = MagicMock()
        mock_result.errors = ["API error"]
        mock_result.is_empty = False

        with patch("asyncio.run", return_value=mock_result), patch("geospark.data_channels.weather.WeatherChannel"):
            result = report._fetch_weather(48.8566, 2.3522)

        assert result is None

    def test_fetch_weather_returns_none_on_exception(self):
        """Weather channel throws → returns None gracefully."""
        report = SpatialReport.__new__(SpatialReport)

        with patch("asyncio.run", side_effect=Exception("boom")):
            result = report._fetch_weather(48.8566, 2.3522)

        assert result is None


class TestSpatialReportAirQuality:
    def test_fetch_air_quality_returns_snapshot(self):
        """Air quality channel returns valid data → AirQualitySnapshot populated."""
        report = SpatialReport.__new__(SpatialReport)

        mock_result = MagicMock()
        mock_result.errors = []
        mock_result.is_empty = False
        mock_result.features = [
            {
                "station_name": "CBD Station",
                "distance_m": 500,
                "measurements": {
                    "pm25": {"value": 8.0},
                    "no2": {"value": 12.0},
                    "o3": {"value": 25.0},
                },
                "aqi_category": "Good",
            }
        ]

        with patch("asyncio.run", return_value=mock_result), patch("geospark.data_channels.air_quality.AirQualityChannel"):
            result = report._fetch_air_quality(48.8566, 2.3522)

        assert result is not None
        assert result.pm25 == 8.0
        assert result.pm25_category == "Good"
        assert result.station_name == "CBD Station"

    def test_fetch_air_quality_returns_none_when_unconfigured(self):
        """Air quality without API key → returns None gracefully."""
        report = SpatialReport.__new__(SpatialReport)

        mock_result = MagicMock()
        mock_result.errors = ["OPENAQ_API_KEY not set"]
        mock_result.is_empty = False

        with patch("asyncio.run", return_value=mock_result), patch("geospark.data_channels.air_quality.AirQualityChannel"):
            result = report._fetch_air_quality(48.8566, 2.3522)

        assert result is None


# --- GeoAgent Intent Routing Tests ---


class TestGeoAgentIntentRouting:
    """Test that the GeoAgent routes to correct channel methods based on intent."""

    def _make_agent(self):
        """Create a GeoAgent with mocked dependencies."""
        agent = GeoAgent.__new__(GeoAgent)
        agent._ollama_url = "http://localhost:11434"
        agent._model = "qwen2.5:7b"
        agent._launcher = MagicMock()
        agent._overpass = MagicMock()
        agent._graph = MagicMock()
        agent.engine = MagicMock()
        return agent

    def test_parse_goal_fallback_weather(self):
        """Fallback parser detects weather intent from keywords."""
        agent = self._make_agent()

        # Mock Ollama to fail so fallback kicks in
        with patch("httpx.post", side_effect=Exception("no ollama")):
            _locations, intent, _params = agent._parse_goal(
                "What is the weather in Tokyo"
            )

        assert intent == "weather"

    def test_parse_goal_fallback_air_quality(self):
        agent = self._make_agent()

        with patch("httpx.post", side_effect=Exception("no ollama")):
            _locations, intent, _params = agent._parse_goal(
                "Check air quality and pollution levels in Delhi"
            )

        assert intent == "air_quality"

    def test_parse_goal_fallback_fire(self):
        agent = self._make_agent()

        with patch("httpx.post", side_effect=Exception("no ollama")):
            _locations, intent, _params = agent._parse_goal(
                "Are there any active wildfires near California"
            )

        assert intent == "fire_detection"

    def test_parse_goal_fallback_environmental(self):
        agent = self._make_agent()

        with patch("httpx.post", side_effect=Exception("no ollama")):
            _locations, intent, _params = agent._parse_goal(
                "What are the environmental conditions in Melbourne"
            )

        assert intent == "environmental"

    def test_parse_goal_fallback_distance(self):
        """Existing intents still work."""
        agent = self._make_agent()

        with patch("httpx.post", side_effect=Exception("no ollama")):
            _locations, intent, _params = agent._parse_goal(
                "How far is Paris from London"
            )

        assert intent == "distance"

    def test_parse_goal_fallback_find_nearby(self):
        """Default intent is find_nearby."""
        agent = self._make_agent()

        with patch("httpx.post", side_effect=Exception("no ollama")):
            _locations, intent, _params = agent._parse_goal(
                "Find hospitals near the Eiffel Tower"
            )

        assert intent == "find_nearby"


class TestGeoAgentChannelMethods:
    """Test channel methods handle responses correctly."""

    def _make_agent(self):
        agent = GeoAgent.__new__(GeoAgent)
        agent._ollama_url = "http://localhost:11434"
        agent._model = "qwen2.5:7b"
        agent._launcher = MagicMock()
        agent._overpass = MagicMock()
        agent._graph = MagicMock()
        agent.engine = MagicMock()
        return agent

    def test_get_weather_populates_findings(self):
        agent = self._make_agent()
        result = AgentResult(goal="Weather in Paris")
        geocoded = {
            "Paris": {"coordinates": [2.3522, 48.8566], "name": "Paris"},
        }

        mock_ch_result = MagicMock()
        mock_ch_result.errors = []
        mock_ch_result.features = [
            {
                "type": "current_weather",
                "temperature_c": 15.0,
                "weather_description": "Overcast",
            },
            {"type": "daily_forecast", "date": "2026-04-06", "temp_max_c": 18.0},
        ]

        with patch("asyncio.run", return_value=mock_ch_result), patch("geospark.data_channels.weather.WeatherChannel"):
            agent._get_weather(result, geocoded)

        assert "weather" in result.findings
        assert "Paris" in result.findings["weather"]
        assert any(s.action == "weather" for s in result.steps)

    def test_get_weather_handles_error(self):
        agent = self._make_agent()
        result = AgentResult(goal="Weather in Paris")
        geocoded = {
            "Paris": {"coordinates": [2.3522, 48.8566], "name": "Paris"},
        }

        mock_ch_result = MagicMock()
        mock_ch_result.errors = ["API timeout"]

        with patch("asyncio.run", return_value=mock_ch_result), patch("geospark.data_channels.weather.WeatherChannel"):
            agent._get_weather(result, geocoded)

        assert "weather" not in result.findings
        assert any(s.error for s in result.steps)

    def test_detect_fires_populates_findings(self):
        agent = self._make_agent()
        result = AgentResult(goal="Fires near Amazon")
        geocoded = {
            "Amazon": {"coordinates": [-60.0, -3.0], "name": "Amazon"},
        }

        mock_ch_result = MagicMock()
        mock_ch_result.errors = []
        mock_ch_result.features = [
            {"type": "active_fire", "coordinates": [-59.5, -2.8], "confidence": 85},
            {"type": "active_fire", "coordinates": [-59.8, -3.1], "confidence": 72},
        ]

        with patch("asyncio.run", return_value=mock_ch_result), patch("geospark.data_channels.fires.FiresChannel"):
            agent._detect_fires(result, geocoded)

        assert "fires" in result.findings
        assert result.findings["fires"]["Amazon"]["count"] == 2

    def test_channel_method_skips_missing_coordinates(self):
        agent = self._make_agent()
        result = AgentResult(goal="Weather check")
        geocoded = {
            "Unknown": {"coordinates": None, "name": "Unknown"},
        }

        agent._get_weather(result, geocoded)
        assert len(result.steps) == 0


# --- Narrative Tests ---


class TestNarrativeWithChannels:
    def test_fallback_includes_weather(self):
        """Fallback summary includes weather when available."""
        report = SpatialReport.__new__(SpatialReport)
        report._ollama_url = "http://fake:11434"
        report._model = "test"

        loc = LocationReport(
            query="Test City",
            address="Test City, Country",
            coordinates=[0, 0],
            elevation_m=100.0,
            weather=WeatherSnapshot(temperature_c=25.0, conditions="Sunny"),
            air_quality=AirQualitySnapshot(pm25=10.0, pm25_category="Good"),
        )

        with patch("httpx.post", side_effect=Exception("no LLM")):
            summary = report._generate_narrative(loc)

        assert "25.0°C" in summary
        assert "Sunny" in summary
        assert "PM2.5 10.0" in summary
        assert "Good" in summary

    def test_fallback_without_channels(self):
        """Fallback summary works without weather/air quality."""
        report = SpatialReport.__new__(SpatialReport)
        report._ollama_url = "http://fake:11434"
        report._model = "test"

        loc = LocationReport(
            query="Test City",
            address="Test City, Country",
            coordinates=[0, 0],
            elevation_m=50.0,
        )

        with patch("httpx.post", side_effect=Exception("no LLM")):
            summary = report._generate_narrative(loc)

        assert "Test City" in summary
        assert "50.0m" in summary
