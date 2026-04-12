"""Tests for the audit logging middleware (Phase 8A-2)."""
from __future__ import annotations

import json
import tempfile

import pytest

from geospark.middleware.audit_log import (
    AuditEntry,
    AuditStore,
    _hash_key,
    _should_log,
)

pytest.importorskip(
    "fastapi",
    reason="FastAPI not installed (install with pip install -e '.[api]')",
)

from fastapi.testclient import TestClient

from geospark.api import app

# ======================================================================
# AuditEntry tests
# ======================================================================


class TestAuditEntry:
    """Tests for the AuditEntry model."""

    def test_create_entry(self) -> None:
        entry = AuditEntry(
            method="GET",
            path="/api/v1/geocode",
            query="query=Paris",
            status_code=200,
            duration_ms=42.5,
            client_ip="1.2.3.4",
            api_key_hash="abc12345",
            user_agent="curl/7.68",
            response_size=1024,
        )
        assert entry.method == "GET"
        assert entry.status_code == 200
        assert entry.duration_ms == 42.5
        assert entry.timestamp  # Should be auto-set

    def test_to_dict(self) -> None:
        entry = AuditEntry(
            method="POST", path="/test", query="", status_code=201,
            duration_ms=10, client_ip="x", api_key_hash="", user_agent="", response_size=0,
        )
        d = entry.to_dict()
        assert d["method"] == "POST"
        assert d["status_code"] == 201
        assert "timestamp" in d

    def test_to_json_line(self) -> None:
        entry = AuditEntry(
            method="GET", path="/test", query="", status_code=200,
            duration_ms=5, client_ip="x", api_key_hash="", user_agent="", response_size=0,
        )
        line = entry.to_json_line()
        parsed = json.loads(line)
        assert parsed["method"] == "GET"
        assert "\n" not in line  # Must be a single line


# ======================================================================
# Helper tests
# ======================================================================


class TestShouldLog:
    """Tests for the path filtering logic."""

    def test_api_paths_logged(self) -> None:
        assert _should_log("/api/v1/geocode") is True
        assert _should_log("/api/v1/agent/run") is True

    def test_assets_skipped(self) -> None:
        assert _should_log("/assets/styles.css") is False
        assert _should_log("/assets/app.js") is False

    def test_favicon_skipped(self) -> None:
        assert _should_log("/favicon.ico") is False

    def test_pages_logged(self) -> None:
        # HTML pages are logged (they're real traffic, useful for analytics)
        assert _should_log("/") is True
        assert _should_log("/playground") is True


class TestHashKey:
    """Tests for API key hashing."""

    def test_hash_produces_8_chars(self) -> None:
        h = _hash_key("sk-abc123xyz456")
        assert len(h) == 8

    def test_empty_key_returns_empty(self) -> None:
        assert _hash_key("") == ""

    def test_same_key_same_hash(self) -> None:
        assert _hash_key("test") == _hash_key("test")

    def test_different_keys_different_hash(self) -> None:
        assert _hash_key("key1") != _hash_key("key2")


# ======================================================================
# AuditStore tests
# ======================================================================


class TestAuditStore:
    """Tests for the file-backed audit store."""

    def _make_entry(self, path: str = "/test", status: int = 200) -> AuditEntry:
        return AuditEntry(
            method="GET", path=path, query="", status_code=status,
            duration_ms=10, client_ip="1.2.3.4", api_key_hash="",
            user_agent="test", response_size=100,
        )

    def test_append_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(audit_dir=tmp)
            entry = self._make_entry()
            store.append(entry)

            entries = store.read_today()
            assert len(entries) >= 1
            assert entries[-1]["path"] == "/test"
            store.close()

    def test_multiple_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(audit_dir=tmp)
            for i in range(5):
                store.append(self._make_entry(path=f"/test/{i}"))

            entries = store.read_today(limit=10)
            assert len(entries) == 5
            store.close()

    def test_read_with_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(audit_dir=tmp)
            for i in range(10):
                store.append(self._make_entry(path=f"/test/{i}"))

            entries = store.read_today(limit=3)
            assert len(entries) == 3
            # Should be the LAST 3 entries
            assert entries[-1]["path"] == "/test/9"
            store.close()

    def test_read_nonexistent_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(audit_dir=tmp)
            entries = store.read_date("2020-01-01")
            assert entries == []

    def test_list_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(audit_dir=tmp)
            store.append(self._make_entry())
            dates = store.list_dates()
            assert len(dates) >= 1
            store.close()

    def test_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(audit_dir=tmp)
            store.append(self._make_entry(path="/api/v1/geocode", status=200))
            store.append(self._make_entry(path="/api/v1/geocode", status=200))
            store.append(self._make_entry(path="/api/v1/distance", status=200))
            store.append(self._make_entry(path="/api/v1/ask", status=500))

            stats = store.stats()
            assert stats["total_requests"] == 4
            assert stats["status_codes"]["200"] == 3
            assert stats["status_codes"]["500"] == 1
            assert stats["unique_ips"] >= 1
            assert len(stats["top_paths"]) >= 2
            store.close()

    def test_stats_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(audit_dir=tmp)
            stats = store.stats("2020-01-01")
            assert stats["total_requests"] == 0

    def test_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store1 = AuditStore(audit_dir=tmp)
            store1.append(self._make_entry())
            store1.close()

            # New instance, same directory
            store2 = AuditStore(audit_dir=tmp)
            entries = store2.read_today()
            assert len(entries) >= 1
            store2.close()


# ======================================================================
# Integration tests
# ======================================================================


class TestAuditLogMiddleware:
    """Integration tests for audit logging on the real API."""

    def test_api_request_is_logged(self) -> None:
        """API requests should appear in the audit log."""
        with tempfile.TemporaryDirectory() as tmp:
            # Swap the global store to use our temp dir
            import geospark.middleware.audit_log as alm
            from geospark.middleware.audit_log import AuditStore

            original = alm._audit_store
            alm._audit_store = AuditStore(audit_dir=tmp)
            try:
                client = TestClient(app)
                client.get("/health")  # Should be logged
                entries = alm._audit_store.read_today()
                assert len(entries) >= 1
                assert any(e["path"] == "/health" for e in entries)
            finally:
                alm._audit_store.close()
                alm._audit_store = original

    def test_static_assets_not_logged(self) -> None:
        """Static assets should be skipped in audit log."""
        with tempfile.TemporaryDirectory() as tmp:
            import geospark.middleware.audit_log as alm

            original = alm._audit_store
            alm._audit_store = AuditStore(audit_dir=tmp)
            try:
                client = TestClient(app)
                client.get("/assets/styles.css")
                entries = alm._audit_store.read_today()
                asset_entries = [e for e in entries if "/assets/" in e.get("path", "")]
                assert len(asset_entries) == 0
            finally:
                alm._audit_store.close()
                alm._audit_store = original
