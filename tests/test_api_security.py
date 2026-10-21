"""Security tests for the public API: each one pins a hole that M2 closed.

The API is open on purpose; these tests check the boundary between what anyone may do
and what needs the operator token (or a gateway partner key).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from geospark import security
from geospark.api import app
from geospark.protocol.schema import SpatialContext, SpatialResult
from geospark.sandbox import sandboxes

ADMIN = "test-admin-token-0123456789"
PARTNER = "partner-key-umami-0123456789"
SESSION_A = "aaaaaaaa-1111-2222-3333-444444444444"
SESSION_B = "bbbbbbbb-1111-2222-3333-444444444444"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    """Production-like configuration with isolated storage."""
    monkeypatch.setenv("GEOSPARK_ENV", "production")
    monkeypatch.setenv("GEOSPARK_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("GEOSPARK_GATEWAY_KEYS", f"other-key-xyz-000000, {PARTNER}")
    monkeypatch.setenv("GEOSPARK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEOSPARK_RATE_LIMIT_ENABLED", "false")
    monkeypatch.delenv("GEOSPARK_API_KEY", raising=False)
    sandboxes.reset()
    security.reset_llm_slots()
    yield TestClient(app)
    sandboxes.reset()
    security.reset_llm_slots()


def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": ADMIN}


# --- Startup -----------------------------------------------------------------


def test_production_refuses_to_start_without_admin_token(monkeypatch) -> None:
    monkeypatch.setenv("GEOSPARK_ENV", "production")
    monkeypatch.delenv("GEOSPARK_ADMIN_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GEOSPARK_ADMIN_TOKEN"):
        security.check_startup_config()


def test_development_starts_without_admin_token(monkeypatch) -> None:
    monkeypatch.delenv("GEOSPARK_ENV", raising=False)
    monkeypatch.delenv("GEOSPARK_ADMIN_TOKEN", raising=False)
    security.check_startup_config()


# --- Operator routes ---------------------------------------------------------

ADMIN_ROUTES = [
    "/api/v1/admin/audit",
    "/api/v1/admin/audit/stats",
    "/api/v1/admin/audit/dates",
    "/api/v1/admin/usage",
    "/api/v1/admin/usage/keys",
]


@pytest.mark.parametrize("path", ADMIN_ROUTES)
def test_admin_routes_reject_anonymous(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ADMIN_ROUTES)
def test_admin_routes_reject_wrong_token(client: TestClient, path: str) -> None:
    assert client.get(path, headers={"X-Admin-Token": "nope"}).status_code == 401
    assert client.get(path, headers={"Authorization": f"Bearer {PARTNER}"}).status_code == 401


@pytest.mark.parametrize("path", ADMIN_ROUTES)
def test_admin_routes_accept_admin_token(client: TestClient, path: str) -> None:
    assert client.get(path, headers=admin_headers()).status_code == 200
    assert client.get(path, headers={"Authorization": f"Bearer {ADMIN}"}).status_code == 200


def test_audit_date_must_be_a_date(client: TestClient) -> None:
    resp = client.get("/api/v1/admin/audit", params={"date": "../../etc/passwd"}, headers=admin_headers())
    assert resp.status_code == 400


def test_flow_writes_are_operator_only(client: TestClient) -> None:
    assert client.post("/api/v1/flows", json={"name": "x", "steps": []}).status_code == 401
    assert client.delete("/api/v1/flows/abc").status_code == 401


# --- Public routes stay public -------------------------------------------------


def test_public_compute_needs_no_key(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/distance", json={"lat_a": 48.8584, "lon_a": 2.2945, "lat_b": 48.8606, "lon_b": 2.3376}
    )
    assert resp.status_code == 200
    assert resp.json()["distance_km"] == pytest.approx(3.172, abs=0.01)


def test_public_health_and_status(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/status").status_code == 200


# --- LLM gateway ---------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/v1/llm/chat", "/api/v1/llm/generate", "/api/v1/llm/embeddings"])
def test_gateway_rejects_anonymous(client: TestClient, path: str) -> None:
    body = {"messages": [{"role": "user", "content": "hi"}], "prompt": "hi", "input": "hi"}
    assert client.post(path, json=body).status_code == 401


def test_gateway_accepts_partner_key(client: TestClient) -> None:
    """A partner key passes auth (Ollama isn't running here, so the call itself fails)."""
    body = {"messages": [{"role": "user", "content": "hi"}]}
    with patch("geospark.llm_gateway.httpx.AsyncClient", side_effect=RuntimeError("no ollama")):
        resp = client.post("/api/v1/llm/chat", json=body, headers={"Authorization": f"Bearer {PARTNER}"})
    assert resp.status_code != 401


def test_gateway_health_hides_internal_url(client: TestClient) -> None:
    data = client.get("/api/v1/llm/health").json()
    assert "ollama_url" not in data
    assert "11434" not in str(data)


# --- Paid-model fallback ---------------------------------------------------------


def _fake_answer() -> SpatialResult:
    return SpatialResult(
        spatial_context=SpatialContext(summary="ok", total_features=0), sources=["ollama:qwen2.5:7b"]
    )


def test_ask_rejects_paid_model(client: TestClient) -> None:
    with patch("geospark.engine.core.Engine.ask", return_value=_fake_answer()) as ask:
        resp = client.post("/api/v1/ask", json={"question": "hi", "model": "anthropic/claude-opus-4"})
    assert resp.status_code == 400
    ask.assert_not_called()


@pytest.mark.parametrize("model", [None, "qwen2.5:7b", "meta-llama/llama-3.3-70b-instruct:free", "best"])
def test_ask_allows_local_and_free_models(client: TestClient, model: str | None) -> None:
    with patch("geospark.engine.core.Engine.ask", return_value=_fake_answer()):
        resp = client.post("/api/v1/ask", json={"question": "hi", "model": model})
    assert resp.status_code == 200


def test_admin_may_pick_any_model(client: TestClient) -> None:
    with patch("geospark.engine.core.Engine.ask", return_value=_fake_answer()):
        resp = client.post(
            "/api/v1/ask", json={"question": "hi", "model": "openai/gpt-5"}, headers=admin_headers()
        )
    assert resp.status_code == 200


# --- SSRF ------------------------------------------------------------------------


def test_flow_build_ignores_caller_supplied_ollama_url(client: TestClient) -> None:
    seen: dict[str, object] = {}

    def fake_chat_fn(**kwargs):
        seen.update(kwargs)
        return lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop"))

    with patch("geospark.flows.make_ollama_chat_fn", side_effect=fake_chat_fn):
        resp = client.post(
            "/api/v1/flows/build",
            json={"goal": "geocode Paris", "ollama_url": "http://169.254.169.254/latest/meta-data"},
        )
    assert "base_url" not in seen
    assert "169.254" not in resp.text


def test_flow_build_rejects_paid_model(client: TestClient) -> None:
    resp = client.post("/api/v1/flows/build", json={"goal": "x", "model": "openai/gpt-5"})
    assert resp.status_code == 400


# --- Context path traversal -------------------------------------------------------


def _ctx(uri: str) -> dict:
    return {"uri": uri, "category": "missions", "name": "t"}


@pytest.mark.parametrize(
    "uri",
    [
        "geospark://missions/../../../tmp/pwn",
        "geospark://missions//tmp/pwn",
        "geospark://../outside",
        "geospark://missions/a/../../b",
        "geospark://missions/.hidden",
    ],
)
def test_context_save_rejects_traversal(client: TestClient, tmp_path, uri: str) -> None:
    resp = client.post("/api/v1/context/save", json=_ctx(uri), headers={"X-GeoSpark-Session": SESSION_A})
    assert resp.status_code == 400
    assert not list(tmp_path.parent.glob("**/pwn"))


def test_context_load_rejects_traversal(client: TestClient) -> None:
    resp = client.get("/api/v1/context/load", params={"uri": "geospark://missions/../../etc"})
    assert resp.status_code == 400


def test_context_delete_rejects_traversal(client: TestClient) -> None:
    resp = client.delete("/api/v1/context/missions/..%2F..%2Fx")
    assert resp.status_code in (400, 404)


# --- Per-visitor sandboxes ---------------------------------------------------------


def test_contexts_are_private_per_visitor(client: TestClient) -> None:
    a = {"X-GeoSpark-Session": SESSION_A}
    b = {"X-GeoSpark-Session": SESSION_B}
    assert client.post("/api/v1/context/save", json=_ctx("geospark://missions/demo"), headers=a).status_code == 200
    assert client.get("/api/v1/context/list", headers=a).json()["count"] == 1
    assert client.get("/api/v1/context/list", headers=b).json()["count"] == 0
    # Visitor B can't delete visitor A's context either
    assert client.delete("/api/v1/context/missions/demo", headers=b).status_code == 404
    assert client.get("/api/v1/context/list", headers=a).json()["count"] == 1


def test_memory_is_private_per_visitor(client: TestClient) -> None:
    a = {"X-GeoSpark-Session": SESSION_A}
    b = {"X-GeoSpark-Session": SESSION_B}
    with patch("geospark.memory.intelligence._get_embedding", return_value=None):
        resp = client.post("/api/v1/memory/fact", json={"content": "The Louvre is in Paris"}, headers=a)
    assert resp.status_code == 200
    assert client.get("/api/v1/memory/stats", headers=a).json()["total_facts"] == 1
    assert client.get("/api/v1/memory/stats", headers=b).json()["total_facts"] == 0
    assert client.get("/api/v1/memory/stats", headers=admin_headers()).json()["total_facts"] == 0


def test_memory_quota(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("GEOSPARK_SANDBOX_MAX_MEMORIES", "2")
    a = {"X-GeoSpark-Session": SESSION_A}
    with patch("geospark.memory.intelligence._get_embedding", return_value=None):
        codes = [
            client.post("/api/v1/memory/fact", json={"content": f"fact {n}"}, headers=a).status_code
            for n in range(3)
        ]
    assert codes == [200, 200, 409]


def test_context_quota(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("GEOSPARK_SANDBOX_MAX_CONTEXTS", "1")
    a = {"X-GeoSpark-Session": SESSION_A}
    codes = [
        client.post("/api/v1/context/save", json=_ctx(f"geospark://missions/m{n}"), headers=a).status_code
        for n in range(2)
    ]
    assert codes == [200, 409]


def test_bad_session_id_falls_back_to_ip_sandbox(client: TestClient) -> None:
    """A malformed session header can't address someone else's (or the global) space."""
    resp = client.post(
        "/api/v1/context/save",
        json=_ctx("geospark://missions/x"),
        headers={"X-GeoSpark-Session": "../../global"},
    )
    assert resp.status_code == 200
    assert client.get("/api/v1/context/list", headers=admin_headers()).json()["count"] == 0


# --- Input bounds and body size ------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/distance", {"lat_a": 200, "lon_a": 0, "lat_b": 0, "lon_b": 0}),
        ("/api/v1/elevation", {"latitude": 0, "longitude": 999}),
        ("/api/v1/geocode", {"query": "Paris", "limit": 10_000}),
        ("/api/v1/agent/report", {"location": "Paris", "radius_m": 1_000_000}),
        ("/api/v1/ask", {"question": "x" * 5000}),
        ("/api/v1/flows/build", {"goal": "x", "max_turns": 60}),
    ],
)
def test_out_of_range_input_is_rejected(client: TestClient, path: str, body: dict) -> None:
    assert client.post(path, json=body).status_code == 422


def test_oversized_body_is_rejected_with_cors(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/geocode",
        content=b'{"query": "' + b"x" * (2 * 1024 * 1024) + b'"}',
        headers={"Content-Type": "application/json", "Origin": "https://example.org"},
    )
    assert resp.status_code == 413
    assert resp.headers.get("access-control-allow-origin") == "*"


# --- Concurrency cap -------------------------------------------------------------------


def test_llm_slots_cap_concurrency(monkeypatch) -> None:
    from fastapi import HTTPException

    monkeypatch.setenv("GEOSPARK_MAX_LLM_CONCURRENCY", "1")
    security.reset_llm_slots()
    held = security.llm_slot()
    next(held)  # first request holds the only slot
    with pytest.raises(HTTPException) as exc:
        next(security.llm_slot())
    assert exc.value.status_code == 503
    with pytest.raises(StopIteration):
        next(held)  # release
    second = security.llm_slot()
    next(second)  # slot is free again
    security.reset_llm_slots()


# --- Privacy -----------------------------------------------------------------------------


def test_ip_hash_is_stable_and_not_reversible() -> None:
    h = security.hash_ip("203.0.113.7")
    assert h == security.hash_ip("203.0.113.7")
    assert h != security.hash_ip("203.0.113.8")
    assert "203" not in h and len(h) == 16
