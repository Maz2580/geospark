"""Tests for the usage tracking middleware (Phase 8A-3)."""
from __future__ import annotations

import tempfile

import pytest

from geospark.middleware.usage_tracker import UsageTracker

pytest.importorskip(
    "fastapi",
    reason="FastAPI not installed (install with pip install -e '.[api]')",
)

from fastapi.testclient import TestClient

from geospark.api import app

# ======================================================================
# UsageTracker unit tests
# ======================================================================


class TestUsageTracker:
    """Tests for the in-memory usage counter."""

    def test_record_increments_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            tracker.record("/api/v1/geocode", "", 200)
            tracker.record("/api/v1/geocode", "", 200)
            assert tracker._total_requests == 2

    def test_record_tracks_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            tracker.record("/api/v1/geocode", "", 200)
            tracker.record("/api/v1/geocode", "", 200)
            tracker.record("/api/v1/distance", "", 200)
            assert tracker._endpoint_counts["/api/v1/geocode"] == 2
            assert tracker._endpoint_counts["/api/v1/distance"] == 1

    def test_record_tracks_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            tracker.record("/api/v1/geocode", "abc12345", 200)
            tracker.record("/api/v1/geocode", "abc12345", 200)
            tracker.record("/api/v1/geocode", "xyz67890", 200)
            assert tracker._key_counts["abc12345"] == 2
            assert tracker._key_counts["xyz67890"] == 1

    def test_record_tracks_status_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            tracker.record("/test", "", 200)
            tracker.record("/test", "", 200)
            tracker.record("/test", "", 404)
            tracker.record("/test", "", 500)
            assert tracker._status_counts[200] == 2
            assert tracker._status_counts[404] == 1
            assert tracker._status_counts[500] == 1

    def test_record_updates_last_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            tracker.record("/test", "mykey", 200)
            assert "mykey" in tracker._key_last_active
            assert tracker._key_last_active["mykey"]  # Non-empty timestamp

    def test_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            for _ in range(10):
                tracker.record("/api/v1/geocode", "key1", 200)
            for _ in range(5):
                tracker.record("/api/v1/distance", "", 200)
            tracker.record("/api/v1/ask", "", 500)

            summary = tracker.summary()
            assert summary["total_requests"] == 16
            assert summary["unique_keys"] == 1
            assert summary["unique_endpoints"] == 3
            assert len(summary["top_endpoints"]) == 3
            # Geocode should be first (most hits)
            assert summary["top_endpoints"][0]["path"] == "/api/v1/geocode"

    def test_key_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            tracker.record("/api/v1/geocode", "abc", 200)
            tracker.record("/api/v1/distance", "abc", 200)
            tracker.record("/api/v1/geocode", "abc", 200)

            usage = tracker.key_usage("abc")
            assert usage["total_requests"] == 3
            assert usage["endpoints"]["/api/v1/geocode"] == 2
            assert usage["endpoints"]["/api/v1/distance"] == 1

    def test_key_usage_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            usage = tracker.key_usage("nonexistent")
            assert usage["total_requests"] == 0

    def test_all_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            tracker.record("/test", "key_a", 200)
            tracker.record("/test", "key_a", 200)
            tracker.record("/test", "key_b", 200)

            keys = tracker.all_keys()
            assert len(keys) == 2
            # key_a should be first (more requests)
            assert keys[0]["key"] == "key_a"
            assert keys[0]["total_requests"] == 2

    def test_persist_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker1 = UsageTracker(storage_dir=tmp)
            tracker1.record("/api/v1/geocode", "key1", 200)
            tracker1.record("/api/v1/distance", "", 200)
            tracker1.persist()

            # New instance, same directory
            tracker2 = UsageTracker(storage_dir=tmp)
            assert tracker2._total_requests == 2
            assert tracker2._endpoint_counts["/api/v1/geocode"] == 1
            assert tracker2._key_counts["key1"] == 1

    def test_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = UsageTracker(storage_dir=tmp)
            tracker.record("/test", "key", 200)
            tracker.reset()
            assert tracker._total_requests == 0
            assert len(tracker._endpoint_counts) == 0
            assert len(tracker._key_counts) == 0


# ======================================================================
# Integration tests
# ======================================================================


class TestUsageTrackingMiddleware:
    """Integration tests for usage tracking on the real API."""

    def test_requests_are_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import geospark.middleware.usage_tracker as utm

            original = utm._usage_tracker
            utm._usage_tracker = UsageTracker(storage_dir=tmp)
            try:
                client = TestClient(app)
                client.get("/health")
                client.get("/health")
                client.get("/api/v1/status")

                summary = utm._usage_tracker.summary()
                assert summary["total_requests"] >= 3
            finally:
                utm._usage_tracker = original

    def test_static_assets_not_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import geospark.middleware.usage_tracker as utm

            original = utm._usage_tracker
            utm._usage_tracker = UsageTracker(storage_dir=tmp)
            try:
                client = TestClient(app)
                client.get("/assets/styles.css")

                summary = utm._usage_tracker.summary()
                asset_paths = [
                    e["path"]
                    for e in summary.get("top_endpoints", [])
                    if "/assets/" in e["path"]
                ]
                assert len(asset_paths) == 0
            finally:
                utm._usage_tracker = original

    def test_usage_endpoint_returns_data(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/admin/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_requests" in data
        assert "top_endpoints" in data
