"""Isochrones and travel-time matrices from Valhalla, the open-source routing engine.

"Where can I get to in 15 minutes on foot?" is answered by Valhalla over the OpenStreetMap
road and path network. Areas are validated (and repaired if needed) and measured geodesically.

Which server:
    GEOSPARK_VALHALLA_URL   your own Valhalla (recommended, and required for public deployments).
                            When unset, GeoSpark uses the public FOSSGIS instance
                            (valhalla1.openstreetmap.de), meant for development and light use:
                            requests are spaced at least 1 s apart and cached, and a production
                            deployment (GEOSPARK_ENV=production) refuses to fall back to it.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import httpx

from geospark.protocol.provenance import source_provenance
from geospark.protocol.schema import SpatialContext, SpatialFeature, SpatialResult
from geospark.utils import USER_AGENT

PUBLIC_URL = "https://valhalla1.openstreetmap.de"
MODES = {"walk": "pedestrian", "bike": "bicycle", "drive": "auto"}
MAX_MINUTES = 60
MAX_CONTOURS = 4
MAX_MATRIX = 5  # origins x destinations

_lock = threading.Lock()
_last_request = 0.0
_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_CACHE_TTL_S = 24 * 3600


class RoutingUnavailableError(RuntimeError):
    """No usable Valhalla server (not configured, or it failed)."""


def _server() -> tuple[str, bool]:
    """(base URL, is_public_demo)."""
    configured = os.getenv("GEOSPARK_VALHALLA_URL", "").rstrip("/")
    if configured:
        return configured, False
    if os.getenv("GEOSPARK_ENV", "").lower() == "production":
        raise RoutingUnavailableError(
            "Isochrones and travel-time matrices need a Valhalla server on this deployment "
            "(set GEOSPARK_VALHALLA_URL). The public FOSSGIS instance is for development and light "
            "use, so a production service doesn't fall back to it."
        )
    return PUBLIC_URL, True


def _call(action: str, payload: dict[str, Any]) -> Any:
    global _last_request
    base, public = _server()
    body = json.dumps(payload, sort_keys=True)
    key = f"{base}/{action}?{body}"
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL_S:
            _cache.move_to_end(key)
            return hit[1]
        if public:  # be gentle with a volunteer-run service
            wait = _last_request + 1.0 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        try:
            with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
                response = client.post(f"{base}/{action}", content=body,
                                       headers={"Content-Type": "application/json"})
                if response.status_code == 400:
                    detail = response.json().get("error", response.text) if response.content else "bad request"
                    raise ValueError(f"Valhalla could not compute this: {detail}")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as e:
            raise RoutingUnavailableError(f"Valhalla server unavailable ({type(e).__name__})") from e
        finally:
            _last_request = time.monotonic()
        _cache[key] = (time.time(), data)
        while len(_cache) > 256:
            _cache.popitem(last=False)
        return data


def _provenance(method: str) -> Any:
    base, public = _server()
    return source_provenance(
        "valhalla",
        url=base,
        name="Valhalla (FOSSGIS public instance)" if public else "Valhalla",
        method=method,
    )


def _mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}")
    return MODES[mode]


def _check_point(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude must be in [-90, 90] and longitude in [-180, 180]")


def isochrone(lat: float, lon: float, minutes: list[int], mode: str = "walk") -> SpatialResult:
    """Areas reachable from a point within each number of minutes (largest first)."""
    from pyproj import Geod
    from shapely.geometry import mapping, shape
    from shapely.validation import make_valid

    _check_point(lat, lon)
    costing = _mode(mode)
    contours = sorted({int(m) for m in minutes})
    if not contours or len(contours) > MAX_CONTOURS or contours[0] < 1 or contours[-1] > MAX_MINUTES:
        raise ValueError(f"Give 1-{MAX_CONTOURS} contour times between 1 and {MAX_MINUTES} minutes")

    data = _call("isochrone", {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": costing,
        "contours": [{"time": m} for m in contours],
        "polygons": True,
        "denoise": 0.3,
    })
    geod = Geod(ellps="WGS84")
    result = SpatialResult(sources=["valhalla"])
    for feature in data.get("features", []):
        geom = shape(feature["geometry"])
        if not geom.is_valid:
            geom = make_valid(geom)
            result.warnings.append("A reachable-area polygon was repaired (self-intersection) before measuring.")
        area_km2 = abs(geod.geometry_area_perimeter(geom)[0]) / 1e6
        result.features.append(SpatialFeature(
            geometry=mapping(geom),
            properties={"minutes": float(feature.get("properties", {}).get("contour", 0)), "mode": mode,
                        "area_sq_km": round(area_km2, 3)},
        ))
    result.features.sort(key=lambda f: -f.properties["minutes"])
    result.spatial_context = SpatialContext(
        total_features=len(result.features), units={"minutes": "minute", "area_sq_km": "square kilometre"},
        summary=f"Reachable by {mode} within " + ", ".join(f"{m} min" for m in contours),
    )
    result.provenance.append(_provenance(
        f"Valhalla isochrone ({costing} costing) over the OpenStreetMap network; areas geodesic on WGS84"))
    result.warnings.append("Travel times assume typical speeds; real traffic, waiting at crossings and "
                           "closures are not modelled.")
    return result


def travel_time_matrix(
    origins: list[tuple[float, float]], destinations: list[tuple[float, float]], mode: str = "walk",
) -> SpatialResult:
    """Travel time (minutes) and network distance (metres) from each origin to each destination.

    Points are (lat, lon). One feature per origin-destination pair (a LineString between them,
    for mapping; the travel itself follows the network).
    """
    costing = _mode(mode)
    if not origins or not destinations or len(origins) > MAX_MATRIX or len(destinations) > MAX_MATRIX:
        raise ValueError(f"Give 1-{MAX_MATRIX} origins and 1-{MAX_MATRIX} destinations")
    for lat, lon in [*origins, *destinations]:
        _check_point(lat, lon)

    data = _call("sources_to_targets", {
        "sources": [{"lat": a, "lon": b} for a, b in origins],
        "targets": [{"lat": a, "lon": b} for a, b in destinations],
        "costing": costing,
        "units": "kilometers",
    })
    result = SpatialResult(sources=["valhalla"])
    unreachable = 0
    for row in data.get("sources_to_targets", []):
        for cell in row:
            i, j = cell.get("from_index"), cell.get("to_index")
            seconds, km = cell.get("time"), cell.get("distance")
            if seconds is None:
                unreachable += 1
            (olat, olon), (dlat, dlon) = origins[i], destinations[j]
            result.features.append(SpatialFeature(
                geometry={"type": "LineString", "coordinates": [[olon, olat], [dlon, dlat]]},
                properties={"origin": i, "destination": j, "mode": mode,
                            "minutes": None if seconds is None else round(seconds / 60, 1),
                            "network_distance_m": None if km is None else round(km * 1000, 1)},
            ))
    if unreachable:
        result.warnings.append(f"{unreachable} origin-destination pair(s) are not connected by the {mode} network.")
    result.spatial_context = SpatialContext(
        total_features=len(result.features), units={"minutes": "minute", "network_distance_m": "metre"},
        summary=f"{len(origins)}x{len(destinations)} {mode} travel-time matrix",
    )
    result.provenance.append(_provenance(f"Valhalla sources_to_targets ({costing} costing) over OpenStreetMap"))
    return result


def reset() -> None:
    """Clear cache and rate-limit clock (tests)."""
    global _last_request
    with _lock:
        _cache.clear()
        _last_request = 0.0
