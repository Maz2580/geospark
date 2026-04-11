"""Tests for the LLM gateway /health pre-flight endpoint."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from geospark.api import app
from geospark.llm_gateway import (
    _compute_status,
    _estimate_cold_load_s,
    _get_load_average,
    _track_inflight,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestComputeStatus:
    """Tests for the status decision logic."""

    def test_ok_when_idle(self) -> None:
        status, _ = _compute_status(load_1m=0.5, queue_depth=0, ollama_reachable=True)
        assert status == "ok"

    def test_ok_at_threshold_boundary(self) -> None:
        status, _ = _compute_status(load_1m=10.0, queue_depth=5, ollama_reachable=True)
        assert status == "ok"  # exactly at the threshold, not above

    def test_degraded_when_load_above_10(self) -> None:
        status, reason = _compute_status(load_1m=12.5, queue_depth=0, ollama_reachable=True)
        assert status == "degraded"
        assert "12.5" in reason

    def test_degraded_when_queue_above_5(self) -> None:
        status, _ = _compute_status(load_1m=1.0, queue_depth=6, ollama_reachable=True)
        assert status == "degraded"

    def test_busy_when_load_above_20(self) -> None:
        """Matches UMAMI agent's abort threshold."""
        status, reason = _compute_status(load_1m=25.0, queue_depth=0, ollama_reachable=True)
        assert status == "busy"
        assert "25.0" in reason

    def test_busy_when_queue_above_10(self) -> None:
        status, _ = _compute_status(load_1m=1.0, queue_depth=15, ollama_reachable=True)
        assert status == "busy"

    def test_busy_when_ollama_unreachable(self) -> None:
        status, reason = _compute_status(load_1m=0.1, queue_depth=0, ollama_reachable=False)
        assert status == "busy"
        assert "unreachable" in reason.lower()


class TestEstimateColdLoad:
    """Tests for the cold-load estimation heuristic."""

    def test_idle_baseline(self) -> None:
        assert _estimate_cold_load_s(0.0) == 8

    def test_low_load(self) -> None:
        assert _estimate_cold_load_s(2.0) == 8  # Below the scaling threshold

    def test_scales_with_load(self) -> None:
        assert _estimate_cold_load_s(10.0) == 20
        assert _estimate_cold_load_s(20.0) == 40
        assert _estimate_cold_load_s(30.0) == 60

    def test_never_below_baseline(self) -> None:
        """Even with load=0, baseline is 8 seconds."""
        assert _estimate_cold_load_s(0.0) >= 8
        assert _estimate_cold_load_s(-1.0) >= 8  # Shouldn't happen but defensive


class TestLoadAverage:
    """Tests for load average retrieval."""

    def test_returns_three_values(self) -> None:
        values = _get_load_average()
        assert len(values) == 3
        assert all(isinstance(v, float) for v in values)

    def test_fallback_on_oserror(self) -> None:
        # create=True lets us patch os.getloadavg on Windows where it doesn't exist natively
        with patch("os.getloadavg", side_effect=OSError("not supported"), create=True):
            values = _get_load_average()
            assert values == (0.0, 0.0, 0.0)

    def test_fallback_on_attributeerror(self) -> None:
        """On Windows, os.getloadavg() doesn't exist — our helper should still return zeros."""
        with patch("os.getloadavg", side_effect=AttributeError("no such attr"), create=True):
            values = _get_load_average()
            assert values == (0.0, 0.0, 0.0)


class TestInflightTracker:
    """Tests for the queue-depth tracking context manager."""

    def test_increments_and_decrements(self) -> None:
        from geospark import llm_gateway

        start = llm_gateway._in_flight_requests
        with _track_inflight():
            assert llm_gateway._in_flight_requests == start + 1
        assert llm_gateway._in_flight_requests == start

    def test_decrements_on_exception(self) -> None:
        from geospark import llm_gateway

        start = llm_gateway._in_flight_requests
        with pytest.raises(RuntimeError, match="boom"), _track_inflight():
            assert llm_gateway._in_flight_requests == start + 1
            raise RuntimeError("boom")
        assert llm_gateway._in_flight_requests == start

    def test_nested_tracking(self) -> None:
        from geospark import llm_gateway

        start = llm_gateway._in_flight_requests
        with _track_inflight(), _track_inflight():
            assert llm_gateway._in_flight_requests == start + 2
        assert llm_gateway._in_flight_requests == start


class TestHealthEndpoint:
    """Integration tests for the /api/v1/llm/health endpoint."""

    def test_endpoint_returns_required_fields(self, client: TestClient) -> None:
        """Even when Ollama is unreachable, all schema fields should be present."""
        resp = client.get("/api/v1/llm/health")
        assert resp.status_code == 200
        data = resp.json()

        # UMAMI agent's required schema
        required = [
            "status",
            "loaded_models",
            "load_average_1m",
            "estimated_cold_load_s",
            "queue_depth",
        ]
        for field in required:
            assert field in data, f"Missing required field: {field}"

        # Type checks
        assert data["status"] in ("ok", "degraded", "busy")
        assert isinstance(data["loaded_models"], list)
        assert isinstance(data["load_average_1m"], int | float)
        assert isinstance(data["estimated_cold_load_s"], int)
        assert isinstance(data["queue_depth"], int)

    def test_endpoint_reports_ollama_unreachable(self, client: TestClient) -> None:
        """When Ollama isn't running, endpoint should still respond with busy status."""
        with patch("geospark.llm_gateway.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.side_effect = Exception("connection refused")
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            resp = client.get("/api/v1/llm/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ollama_reachable"] is False
            # When Ollama is unreachable, status is busy
            assert data["status"] == "busy"
            assert "error" in data

    def test_endpoint_parses_loaded_models(self, client: TestClient) -> None:
        """When Ollama returns loaded models, they should appear in the response."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={
            "models": [
                {
                    "name": "qwen2.5:7b",
                    "size": 4_600_000_000,
                    "expires_at": "2026-04-11T14:00:00Z",
                }
            ]
        })

        async def mock_get(url):
            return mock_resp

        with patch("geospark.llm_gateway.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get = mock_get
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            resp = client.get("/api/v1/llm/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ollama_reachable"] is True
            assert "qwen2.5:7b" in data["loaded_models"]
            # Detail list should have size info
            assert len(data["loaded_models_detail"]) == 1
            assert data["loaded_models_detail"][0]["size_gb"] == 4.6

    def test_endpoint_empty_loaded_models(self, client: TestClient) -> None:
        """When no models loaded (cold Ollama), loaded_models should be empty list."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"models": []})

        async def mock_get(url):
            return mock_resp

        with patch("geospark.llm_gateway.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get = mock_get
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            resp = client.get("/api/v1/llm/health")
            data = resp.json()
            assert data["loaded_models"] == []
            assert data["ollama_reachable"] is True

    def test_endpoint_includes_extra_fields(self, client: TestClient) -> None:
        """Beyond UMAMI's required schema, we also provide useful extras."""
        resp = client.get("/api/v1/llm/health")
        data = resp.json()
        extras = [
            "load_average_5m",
            "load_average_15m",
            "ollama_reachable",
            "reason",
            "ollama_url",
        ]
        for field in extras:
            assert field in data
