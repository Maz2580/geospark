"""Nominatim usage policy: spaced requests, caching, identifying User-Agent."""

from __future__ import annotations

import itertools
import threading
import time

import httpx
import pytest

from geospark.tools.geocoding import client


@pytest.fixture
def fake_server(monkeypatch):
    calls: list[httpx.Request] = []
    state = {"status": 200}
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((time.monotonic(), request))
        if state["status"] != 200:
            return httpx.Response(state["status"])
        return httpx.Response(200, json={"features": [{"q": request.url.params.get("q")}]})

    monkeypatch.setattr(httpx, "Client", lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    return calls, state


def test_requests_are_spaced_by_the_minimum_interval(fake_server, monkeypatch) -> None:
    calls, _ = fake_server
    monkeypatch.setenv("GEOSPARK_NOMINATIM_MIN_INTERVAL", "0.2")
    threads = [threading.Thread(target=client.get_json, args=("search", {"q": f"place {i}"})) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    times = sorted(t for t, _ in calls)
    assert len(times) == 4
    assert all(b - a >= 0.19 for a, b in itertools.pairwise(times))


def test_repeat_queries_are_served_from_cache(fake_server) -> None:
    calls, _ = fake_server
    first = client.get_json("search", {"q": "Paris", "format": "geojson"})
    second = client.get_json("search", {"format": "geojson", "q": "Paris"})  # same params, other order
    assert first == second and len(calls) == 1


def test_failures_are_not_cached(fake_server) -> None:
    calls, state = fake_server
    state["status"] = 503
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("search", {"q": "Paris"})
    state["status"] = 200
    assert client.get_json("search", {"q": "Paris"})
    assert len(calls) == 2


def test_user_agent_and_self_hosted_url(fake_server, monkeypatch) -> None:
    calls, _ = fake_server
    monkeypatch.setenv("GEOSPARK_NOMINATIM_URL", "https://nominatim.example.org/")
    client.get_json("search", {"q": "Paris"})
    request = calls[0][1]
    assert str(request.url).startswith("https://nominatim.example.org/search?")
    assert request.headers["User-Agent"].startswith("GeoSpark/")
    assert "github.com/Maz2580/geospark" in request.headers["User-Agent"]
