"""Reproducible runs: fingerprints, recording (incl. threads), replay verdicts and the CLI."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from click.testing import CliRunner

from geospark.runs import (
    compare,
    fingerprint,
    in_context,
    record,
    record_run,
    replay,
    run_and_record,
)

BUFFER = {"operation": "buffer", "geometry": {"type": "Point", "coordinates": [2.2945, 48.8584]}, "radius_m": 100}


def test_fingerprints_ignore_volatile_fields_and_float_noise() -> None:
    a = {"distance_m": 3172.014423717831, "execution_time_ms": 3.1, "retrieved_at": "2026-10-22T01:00:00Z"}
    b = {"distance_m": 3172.0144237178312, "execution_time_ms": 9.9, "retrieved_at": "2026-10-23T05:00:00Z"}
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint({**a, "distance_m": 3172.5})


def test_nothing_is_recorded_outside_a_run() -> None:
    record("data", "x", {}, {})  # no active run: must be a harmless no-op


def test_engine_and_data_steps_are_recorded_including_threads() -> None:
    with record_run("demo") as run:
        from geospark import Engine
        from geospark.protocol import SpatialQuery

        Engine().execute(SpatialQuery(**BUFFER))
        with ThreadPoolExecutor(max_workers=2) as pool:  # like SpatialReport's parallel lookups
            pool.submit(in_context(record), "data", "weather", {"lat": 1}, {"t": 20}, "open-meteo").result()
            pool.submit(in_context(record), "data", "overpass", "[out:json];", {"elements": []}).result()

        async def inner() -> None:
            record("data", "async-source", {}, {"ok": True})

        from geospark.utils.aio import run_sync

        async def caller() -> None:
            run_sync(inner())  # runs in a worker thread with its own loop

        asyncio.run(caller())
    names = [s["name"] for s in run.steps]
    assert names[0] == "buffer" and set(names[1:]) == {"weather", "overpass", "async-source"}
    assert [s["n"] for s in run.steps] == [1, 2, 3, 4]


def test_pure_computation_reproduces(tmp_path) -> None:
    _, run = run_and_record("query", query=BUFFER)
    path = run.save(tmp_path / "buffer.json")
    report = replay(path)
    assert report["verdict"] == "reproduced" and report["steps"] == [1, 1]


def _manifest(steps, result="r1", env=None):
    return {"geospark_run": 1, "command": "x", "arguments": {}, "environment": env or {"geospark": "0.8.0"},
            "result": {"fingerprint": result, "summary": None}, "steps": steps}


def _step(n, kind, name, request, response, source=None):
    return {"n": n, "kind": kind, "name": name, "source": source, "request": request, "response": response,
            "request_preview": f"<{name}>"}


def test_verdict_data_changed_names_the_source() -> None:
    old = _manifest([_step(1, "data", "nominatim/search", "q1", "A", "openstreetmap-nominatim"),
                     _step(2, "compute", "geocode", "g1", "R")], result="r1")
    new = _manifest([_step(1, "data", "nominatim/search", "q1", "B", "openstreetmap-nominatim"),
                     _step(2, "compute", "geocode", "g1", "R2")], result="r2")
    report = compare(old, new)
    assert report["verdict"] == "data changed"
    assert "openstreetmap-nominatim" in report["explanation"] and report["data_steps_changed"] == [1]


def test_verdict_code_changed() -> None:
    old = _manifest([_step(1, "compute", "buffer", "q", "A")], result="r1", env={"shapely": "2.0.0"})
    new = _manifest([_step(1, "compute", "buffer", "q", "B")], result="r2", env={"shapely": "2.2.0"})
    report = compare(old, new)
    assert report["verdict"] == "code changed" and report["environment_changes"] == {"shapely": ("2.0.0", "2.2.0")}


def test_verdict_different_when_steps_go_missing() -> None:
    old = _manifest([_step(1, "data", "overpass", "q", "A")], result="r1")
    new = _manifest([], result="r2")
    report = compare(old, new)
    assert report["verdict"] == "different" and report["steps_missing"] == [1]


def test_replay_detects_changed_upstream_data(tmp_path) -> None:
    """Record a geocode, let 'OpenStreetMap' change, replay: verdict says the data changed."""
    query = {"operation": "geocode", "metadata": {"query": "Federation Square"}}

    def nominatim(lon):
        return {"features": [{"geometry": {"type": "Point", "coordinates": [lon, -37.8177]},
                              "properties": {"display_name": "Federation Square", "importance": 0.4}}]}

    with patch("geospark.tools.geocoding.client.get_json", side_effect=lambda path, params: _rec(path, params, nominatim(144.9691))):
        _, run = run_and_record("query", query=query, tools=["geocoder"])
    path = run.save(tmp_path / "geocode.json")
    with patch("geospark.tools.geocoding.client.get_json", side_effect=lambda path, params: _rec(path, params, nominatim(144.9700))):
        report = replay(path)
    assert report["verdict"] == "data changed" and "openstreetmap-nominatim" in report["explanation"]


def _rec(path, params, data):
    record("data", f"nominatim/{path}", {"params": params}, data, "openstreetmap-nominatim")
    return data


def test_cli_record_and_replay(tmp_path) -> None:
    from geospark.cli import main
    from geospark.protocol.schema import SpatialFeature, SpatialResult

    iso = SpatialResult(features=[SpatialFeature(geometry={"type": "Point", "coordinates": [0, 0]},
                                                 properties={"minutes": 10.0, "area_sq_km": 1.5})])
    out = tmp_path / "iso.json"
    runner = CliRunner()
    with patch("geospark.tools.routing.valhalla.isochrone", return_value=iso):
        recorded = runner.invoke(main, ["record", "isochrone", "--minutes", "10", "--out", str(out), "--",
                                        "-37.818", "144.969"])
        assert recorded.exit_code == 0, recorded.output
        assert json.loads(out.read_text())["arguments"] == {"lat": -37.818, "lon": 144.969, "minutes": [10], "mode": "walk"}
        replayed = runner.invoke(main, ["replay", str(out)])
    assert replayed.exit_code == 0 and "REPRODUCED" in replayed.output
