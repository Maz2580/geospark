"""Tests for the GeoSpark REST API endpoints."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="FastAPI not installed (install with pip install -e '.[api]')")

from fastapi.testclient import TestClient  # noqa: E402

import geospark  # noqa: E402
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
        assert data["version"] == geospark.__version__
        assert isinstance(data["tools"], list)


class TestStatusEndpoint:
    def test_status_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == geospark.__version__
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


class TestToolStatusIsHonest:
    def test_planned_tools_are_not_listed_as_available(self, client: TestClient) -> None:
        data = client.get("/api/v1/tools").json()
        assert "change_detection" not in data["available"] and "change_detection" in data["planned"]
        assert data["details"]["ndvi"]["status"] == "partial"
        assert all(info["description"] for info in data["details"].values())

    def test_every_planned_tool_really_is_not_implemented(self) -> None:
        from geospark.protocol.schema import SpatialQuery
        from geospark.tools.registry import TOOL_STATUS, ToolRegistry

        for name, (state, _) in TOOL_STATUS.items():
            if state != "planned":
                continue
            registry = ToolRegistry()
            registry.load_tool(name)
            tool = registry.get_tool(name)
            assert tool is not None
            result = tool.execute(SpatialQuery(operation=tool.supported_operations[0]))
            assert result.errors and "not implemented" in result.errors[0].lower(), name
