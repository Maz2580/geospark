"""Reproducible runs: record what an analysis did, then replay it and explain any difference.

    from geospark.runs import record_run, replay

    with record_run("report", location="Federation Square, Melbourne", radius_m=500) as run:
        report = SpatialReport().analyze("Federation Square, Melbourne", radius_m=500)
        run.finish(report)
    run.save("fedsq-run.json")

    replay("fedsq-run.json")   # re-runs it and reports: reproduced / data changed / code changed

A run record (manifest) lists:
- the environment: GeoSpark, Python, pyproj/PROJ, Shapely/GEOS versions;
- every **data** step (a request to Nominatim, Overpass, Overture, Valhalla, a data channel)
  with a fingerprint of the request and of the response;
- every **compute** step (an engine operation) with fingerprints of its input and output;
- a fingerprint of the final result.

Fingerprints are SHA-256 over canonical JSON with volatile fields (timings, retrieval times)
removed, so the same data and code give the same fingerprints. When a replay differs, the first
differing step says *why*: a data source returned something different, or the computation
(i.e. the code or a library version) changed.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import platform
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_VOLATILE = {"execution_time_ms", "retrieved_at", "timestamp", "duration_s", "time"}
_active: contextvars.ContextVar[Run | None] = contextvars.ContextVar("geospark_run", default=None)


def _canonical(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items()) if k not in _VOLATILE}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, float):
        return round(value, 9)  # ignore float noise below a nanometre/nanosecond
    if isinstance(value, (bytes, bytearray)):
        return hashlib.sha256(value).hexdigest()
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def fingerprint(value: Any) -> str:
    """SHA-256 of a value's canonical JSON (volatile fields dropped), first 16 hex chars."""
    blob = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def environment() -> dict[str, str]:
    import pyproj
    import shapely

    from geospark import __version__

    return {
        "geospark": __version__,
        "python": platform.python_version(),
        "pyproj": pyproj.__version__,
        "proj": pyproj.proj_version_str,
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
    }


@dataclass
class Run:
    """A run being recorded (or loaded from a manifest)."""

    command: str
    arguments: dict[str, Any]
    environment: dict[str, str] = field(default_factory=environment)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    steps: list[dict[str, Any]] = field(default_factory=list)
    result_fingerprint: str | None = None
    result_summary: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, kind: str, name: str, request: Any, response: Any, source: str | None = None) -> None:
        step = {
            "kind": kind, "name": name, "source": source,
            "request": fingerprint(request), "response": fingerprint(response),
            "request_preview": _preview(request),
        }
        with self._lock:  # parallel lookups (thread pools) record at the same time
            step["n"] = len(self.steps) + 1
            self.steps.append(step)

    def finish(self, result: Any) -> None:
        self.result_fingerprint = fingerprint(result)
        summary = getattr(result, "summary", None) or getattr(getattr(result, "spatial_context", None), "summary", None)
        self.result_summary = summary if isinstance(summary, str) else None

    def to_manifest(self) -> dict[str, Any]:
        return {
            "geospark_run": 1,
            "command": self.command, "arguments": self.arguments,
            "environment": self.environment, "started_at": self.started_at,
            "result": {"fingerprint": self.result_fingerprint, "summary": self.result_summary},
            "steps": self.steps,
        }

    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.write_text(json.dumps(self.to_manifest(), indent=2, ensure_ascii=False))
        return out


def _preview(value: Any) -> str:
    text = json.dumps(_canonical(value), ensure_ascii=False)
    return text if len(text) <= 160 else text[:157] + "..."


@contextlib.contextmanager
def record_run(command: str, **arguments: Any) -> Iterator[Run]:
    """Record every data and compute step made inside the block (this thread and the
    threads it starts through GeoSpark's helpers)."""
    run = Run(command=command, arguments=arguments)
    token = _active.set(run)
    try:
        yield run
    finally:
        _active.reset(token)


def record(kind: str, name: str, request: Any, response: Any, source: str | None = None) -> None:
    """Called by data sources and the engine; does nothing unless a run is being recorded."""
    run = _active.get()
    if run is not None:
        run.add(kind, name, request, response, source)


def in_context(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a function so it runs in the caller's context (for thread pools)."""
    ctx = contextvars.copy_context()
    return lambda *a, **k: ctx.run(fn, *a, **k)


# --- replay -------------------------------------------------------------------------------------

def _runner(command: str) -> Callable[..., Any]:
    if command == "report":
        from geospark.agents import SpatialReport

        return lambda location, radius_m=1000: SpatialReport().analyze(location, radius_m=radius_m)
    if command == "agent":
        from geospark.agents import GeoAgent

        return lambda goal: GeoAgent().run(goal)
    if command == "site-select":
        from geospark.agents import SiteSelector

        return lambda **kw: SiteSelector().find(**kw)
    if command == "query":
        from geospark import Engine
        from geospark.protocol import SpatialQuery

        return lambda query, tools=(): Engine(tools=list(tools)).execute(SpatialQuery(**query))
    if command == "isochrone":
        from geospark.tools.routing import valhalla

        return lambda lat, lon, minutes, mode="walk": valhalla.isochrone(lat, lon, minutes, mode)
    if command == "overture":
        from geospark.tools.overture.client import query

        return lambda theme, lat, lon, **kw: query(theme, lat, lon, **kw)
    raise ValueError(f"Don't know how to replay '{command}'")


def run_and_record(command: str, **arguments: Any) -> tuple[Any, Run]:
    """Run a replayable command with recording on; returns (result, run)."""
    with record_run(command, **arguments) as run:
        result = _runner(command)(**arguments)
        run.finish(result)
    return result, run


def replay(manifest_path: str | Path) -> dict[str, Any]:
    """Re-run a recorded analysis and compare it with the record, step by step."""
    original = json.loads(Path(manifest_path).read_text())
    if original.get("geospark_run") != 1:
        raise ValueError(f"{manifest_path} is not a GeoSpark run record")
    started = time.time()
    _, run = run_and_record(original["command"], **original["arguments"])
    return compare(original, run.to_manifest(), seconds=round(time.time() - started, 1))


def compare(original: dict[str, Any], new: dict[str, Any], seconds: float | None = None) -> dict[str, Any]:
    """Explain how two run records differ: reproduced, data changed, or code changed."""
    env_changes = {
        k: (original["environment"].get(k), new["environment"].get(k))
        for k in set(original["environment"]) | set(new["environment"])
        if original["environment"].get(k) != new["environment"].get(k)
    }
    reproduced = original["result"]["fingerprint"] == new["result"]["fingerprint"]

    # Pair steps by (kind, name, request fingerprint) in order of appearance
    def keyed(steps: list[dict[str, Any]]) -> dict[tuple, list[dict[str, Any]]]:
        index: dict[tuple, list[dict[str, Any]]] = {}
        for s in steps:
            index.setdefault((s["kind"], s["name"], s["request"]), []).append(s)
        return index

    old_index, new_index = keyed(original["steps"]), keyed(new["steps"])
    changed_data, changed_compute, missing, added = [], [], [], []
    for key, old_steps in old_index.items():
        new_steps = new_index.get(key, [])
        for i, step in enumerate(old_steps):
            if i >= len(new_steps):
                missing.append(step)
            elif new_steps[i]["response"] != step["response"]:
                (changed_data if step["kind"] == "data" else changed_compute).append(step)
    for key, new_steps in new_index.items():
        added.extend(new_steps[len(old_index.get(key, [])):])

    if reproduced:
        verdict = "reproduced"
        explanation = "Same result as recorded."
    elif changed_data:
        first = changed_data[0]
        verdict = "data changed"
        explanation = (f"{first.get('source') or first['name']} returned different data for the same request "
                       f"(step {first['n']}: {first['request_preview']}).")
    elif changed_compute or env_changes:
        verdict = "code changed"
        explanation = ("The same inputs were computed differently"
                       + (f"; versions changed: {env_changes}" if env_changes else "") + ".")
    else:
        verdict = "different"
        explanation = "The run took different steps (e.g. an upstream service was unavailable)."
    return {
        "verdict": verdict, "explanation": explanation,
        "result_fingerprints": [original["result"]["fingerprint"], new["result"]["fingerprint"]],
        "environment_changes": env_changes,
        "data_steps_changed": [s["n"] for s in changed_data],
        "compute_steps_changed": [s["n"] for s in changed_compute],
        "steps_missing": [s["n"] for s in missing], "steps_added": len(added),
        "steps": [len(original["steps"]), len(new["steps"])],
        "replay_seconds": seconds,
    }
