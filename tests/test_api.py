"""Tests for the GeoSpark REST API endpoints."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="FastAPI not installed (install with pip install -e '.[api]')")

from fastapi.testclient import TestClient  # noqa: E402

from geospark.api import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert isinstance(data["tools"], list)


class TestStatusEndpoint:
    def test_status_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert isinstance(data["uptime_seconds"], float)
        assert data["uptime_seconds"] >= 0
        assert "python_version" in data
        assert isinstance(data["memory"], dict)
        assert isinstance(data["tools"], dict)
        assert "loaded" in data["tools"]
        assert "count" in data["tools"]
        assert data["tools"]["count"] == len(data["tools"]["loaded"])

    def test_status_environment_default(self, client: TestClient) -> None:
        resp = client.get("/api/v1/status")
        data = resp.json()
        assert data["environment"] == "development"


class TestInfoEndpoint:
    def test_info_returns_system_info(self, client: TestClient) -> None:
        resp = client.get("/api/v1/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "GeoSpark"
        assert data["protocol"] == "GSP v0.1"


class TestToolsEndpoint:
    def test_list_tools(self, client: TestClient) -> None:
        resp = client.get("/api/v1/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert "loaded" in data
        assert "available" in data
        assert isinstance(data["available"], list)
