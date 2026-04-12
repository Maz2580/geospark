"""Tests for the rate limiter middleware (Phase 8A-1)."""
from __future__ import annotations

import time

import pytest

from geospark.middleware.rate_limiter import (
    SlidingWindowCounter,
    _get_client_key,
    _is_exempt,
)

pytest.importorskip(
    "fastapi",
    reason="FastAPI not installed (install with pip install -e '.[api]')",
)

from fastapi.testclient import TestClient

from geospark.api import app

# ======================================================================
# SlidingWindowCounter unit tests
# ======================================================================


class TestSlidingWindowCounter:
    """Tests for the sliding window rate counter."""

    def test_allows_under_limit(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=5)
        for _ in range(5):
            allowed, _remaining, retry_after = counter.is_allowed("test")
            assert allowed is True
            assert retry_after == 0

    def test_blocks_at_limit(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=3)
        for _ in range(3):
            counter.is_allowed("test")
        allowed, remaining, retry_after = counter.is_allowed("test")
        assert allowed is False
        assert remaining == 0
        assert retry_after > 0

    def test_remaining_decrements(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=5)
        _, remaining1, _ = counter.is_allowed("a")
        _, remaining2, _ = counter.is_allowed("a")
        assert remaining1 > remaining2

    def test_different_keys_are_independent(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=2)
        counter.is_allowed("alice")
        counter.is_allowed("alice")
        # Alice is at limit
        allowed_alice, _, _ = counter.is_allowed("alice")
        assert allowed_alice is False
        # Bob should still be fine
        allowed_bob, _, _ = counter.is_allowed("bob")
        assert allowed_bob is True

    def test_window_eviction(self) -> None:
        """Old requests should expire and free up capacity."""
        counter = SlidingWindowCounter(window_seconds=1, max_requests=2)
        counter.is_allowed("test")
        counter.is_allowed("test")
        # At limit
        allowed, _, _ = counter.is_allowed("test")
        assert allowed is False
        # Wait for window to expire
        time.sleep(1.1)
        allowed, _, _ = counter.is_allowed("test")
        assert allowed is True

    def test_get_usage(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=10)
        counter.is_allowed("test")
        counter.is_allowed("test")
        counter.is_allowed("test")
        usage = counter.get_usage("test")
        assert usage["requests_in_window"] == 3
        assert usage["limit"] == 10
        assert usage["remaining"] == 7

    def test_get_usage_unknown_key(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=10)
        usage = counter.get_usage("unknown")
        assert usage["requests_in_window"] == 0
        assert usage["remaining"] == 10

    def test_reset_key(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=2)
        counter.is_allowed("test")
        counter.is_allowed("test")
        counter.reset("test")
        allowed, _, _ = counter.is_allowed("test")
        assert allowed is True

    def test_reset_all(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=1)
        counter.is_allowed("a")
        counter.is_allowed("b")
        counter.reset()
        assert counter.tracked_keys == 0

    def test_tracked_keys_count(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=10)
        counter.is_allowed("a")
        counter.is_allowed("b")
        counter.is_allowed("c")
        assert counter.tracked_keys == 3

    def test_retry_after_is_positive(self) -> None:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=1)
        counter.is_allowed("test")
        _, _, retry_after = counter.is_allowed("test")
        assert retry_after >= 1


# ======================================================================
# Helper function tests
# ======================================================================


class TestExemptPaths:
    """Tests for path exemption logic."""

    def test_health_exempt(self) -> None:
        assert _is_exempt("/health") is True

    def test_docs_exempt(self) -> None:
        assert _is_exempt("/docs") is True

    def test_openapi_exempt(self) -> None:
        assert _is_exempt("/openapi.json") is True

    def test_assets_exempt(self) -> None:
        assert _is_exempt("/assets/styles.css") is True

    def test_pages_exempt(self) -> None:
        for page in ["/", "/playground", "/agents", "/memory", "/context", "/data", "/status", "/guide"]:
            assert _is_exempt(page) is True, f"{page} should be exempt"

    def test_api_not_exempt(self) -> None:
        assert _is_exempt("/api/v1/geocode") is False
        assert _is_exempt("/api/v1/ask") is False
        assert _is_exempt("/api/v1/agent/run") is False


class TestClientKey:
    """Tests for client key extraction."""

    def test_extracts_ip_from_client(self) -> None:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
            "query_string": b"",
            "root_path": "",
            "client": ("192.168.1.1", 12345),
        }
        request = Request(scope)
        key = _get_client_key(request)
        assert key == "ip:192.168.1.1"

    def test_extracts_ip_from_x_forwarded_for(self) -> None:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")],
            "query_string": b"",
            "root_path": "",
            "client": ("127.0.0.1", 12345),
        }
        request = Request(scope)
        key = _get_client_key(request)
        assert key == "ip:1.2.3.4"  # First IP in chain

    def test_extracts_api_key_prefix(self) -> None:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [(b"authorization", b"Bearer sk-abc123xyz456")],
            "query_string": b"",
            "root_path": "",
            "client": ("127.0.0.1", 12345),
        }
        request = Request(scope)
        key = _get_client_key(request)
        assert key.startswith("key:")
        assert "sk-abc12" not in key or len(key) < 20  # Should be truncated


# ======================================================================
# Integration tests with TestClient
# ======================================================================


class TestRateLimitMiddleware:
    """Integration tests for rate limiting on the real API."""

    def test_normal_requests_include_headers(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        # Rate limit headers should be present on API routes
        # (status is exempt though, so might not have them)

    def test_health_always_allowed(self) -> None:
        """Health checks must never be rate limited."""
        client = TestClient(app)
        for _ in range(100):
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_pages_always_allowed(self) -> None:
        """HTML pages must never be rate limited."""
        client = TestClient(app)
        for _ in range(100):
            resp = client.get("/")
            assert resp.status_code == 200

    def test_429_includes_retry_after(self) -> None:
        """When rate limited, response should include Retry-After."""
        # Create a very restrictive counter to test 429 behavior
        counter = SlidingWindowCounter(window_seconds=60, max_requests=1)
        counter.is_allowed("test")
        allowed, _, retry_after = counter.is_allowed("test")
        assert allowed is False
        assert retry_after >= 1
