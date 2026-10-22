"""Overture Maps, queried in place with DuckDB: no API key, no download of the dataset.

Overture publishes global open map data as GeoParquet on public S3. Each release has a STAC
catalogue whose items give every file's bounding box; GeoSpark uses that index (fetched once per
release and cached) to read **only the files that cover the query area**, then lets DuckDB
prune row groups by the per-row ``bbox`` column.

Themes:
    places          points of interest with a category and confidence
    buildings       footprints with height and floors; footprint area computed geodesically
    transportation  road and path segments; length computed geodesically
    divisions       the administrative areas that contain a point (country, region, locality, ...)

Configuration:
    GEOSPARK_DUCKDB_THREADS     CPU threads per query (default 4)
    GEOSPARK_DUCKDB_MEMORY      memory cap per query (default 512MB)
    GEOSPARK_OVERTURE_CONCURRENCY  DuckDB queries at once (default 1; memory cap x this must fit)
    GEOSPARK_OVERTURE_RELEASE   pin a release (e.g. "2026-10-21.0"); default: the latest
    GEOSPARK_OVERTURE_STAC      STAC root (default https://stac.overturemaps.org/catalog.json)

Requires ``pip install geospark-ai[overture]`` (duckdb).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from geospark.protocol.provenance import source_provenance
from geospark.protocol.schema import SpatialContext, SpatialFeature, SpatialResult
from geospark.utils import USER_AGENT, data_dir
from geospark.utils.geo import overpass_bbox

STAC_ROOT = "https://stac.overturemaps.org/catalog.json"
ATTRIBUTION = (
    "© Overture Maps Foundation, overturemaps.org; includes data from OpenStreetMap contributors "
    "(ODbL) and other sources. See https://docs.overturemaps.org/attribution/"
)
MAX_RADIUS_M = 2000
_THEMES: dict[str, tuple[str, int]] = {  # theme -> (type, max rows)
    "places": ("place", 500),
    "buildings": ("building", 2000),
    "transportation": ("segment", 2000),
    "divisions": ("division_area", 20),
}
_RELEASE_TTL_S = 6 * 3600

_RESULT_TTL_S = 24 * 3600

_lock = threading.Lock()
# One DuckDB query at a time per process: each may use up to GEOSPARK_DUCKDB_MEMORY, and two at
# once could exceed a small container's memory limit. Queries are S3-bound, so queuing costs little.
_query_gate = threading.BoundedSemaphore(max(1, int(os.getenv("GEOSPARK_OVERTURE_CONCURRENCY", "1"))))
_QUEUE_WAIT_S = 60
_release_cache: tuple[float, str] | None = None
_results: OrderedDict[tuple, tuple[float, SpatialResult]] = OrderedDict()


class OvertureError(RuntimeError):
    """Overture data could not be queried (network, release index, DuckDB)."""


def _http_json(url: str) -> Any:
    with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def latest_release() -> str:
    """The release to query: GEOSPARK_OVERTURE_RELEASE, or the newest in the STAC catalogue."""
    global _release_cache
    pinned = os.getenv("GEOSPARK_OVERTURE_RELEASE")
    if pinned:
        return pinned
    with _lock:
        if _release_cache and time.time() - _release_cache[0] < _RELEASE_TTL_S:
            return _release_cache[1]
    root = _http_json(os.getenv("GEOSPARK_OVERTURE_STAC", STAC_ROOT))
    releases = sorted(
        link["href"].rstrip("/").split("/")[-2]
        for link in root.get("links", [])
        if link.get("rel") == "child" and link.get("href", "").endswith("/catalog.json")
    )
    if not releases:
        raise OvertureError("No Overture releases found in the STAC catalogue")
    with _lock:
        _release_cache = (time.time(), releases[-1])
    return releases[-1]


def _file_index(release: str, theme: str, typ: str) -> list[dict[str, Any]]:
    """[{bbox, url}] for every Parquet file of a theme/type; cached on disk per release."""
    cache = data_dir() / "overture" / release / f"{theme}-{typ}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    stac_base = os.getenv("GEOSPARK_OVERTURE_STAC", STAC_ROOT).rsplit("/", 1)[0]
    collection = _http_json(f"{stac_base}/{release}/{theme}/{typ}/collection.json")
    item_urls = [link["href"] for link in collection.get("links", []) if link.get("rel") == "item"]

    def item(url: str) -> dict[str, Any]:
        data = _http_json(url)
        return {"bbox": data["bbox"], "url": data["assets"]["aws"]["href"]}

    with ThreadPoolExecutor(max_workers=16) as pool:
        index = list(pool.map(item, item_urls))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(index))
    return index


def _files_for(release: str, theme: str, typ: str, bbox: tuple[float, float, float, float]) -> list[str]:
    west, south, east, north = bbox
    return [
        f["url"] for f in _file_index(release, theme, typ)
        if f["bbox"][0] <= east and f["bbox"][2] >= west and f["bbox"][1] <= north and f["bbox"][3] >= south
    ]


def _connection() -> Any:
    try:
        import duckdb
    except ImportError as e:
        raise OvertureError("Overture queries need DuckDB: pip install 'geospark-ai[overture]'") from e
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    # DuckDB would otherwise use every core and most of the RAM it can see; on a shared host
    # that starves other services. Small caps are plenty for bbox-filtered reads.
    con.execute(f"SET threads = {int(os.getenv('GEOSPARK_DUCKDB_THREADS', '4'))}")
    con.execute(f"SET memory_limit = '{os.getenv('GEOSPARK_DUCKDB_MEMORY', '512MB')}'")
    ext_dir = os.getenv("GEOSPARK_DUCKDB_EXTENSIONS")
    if ext_dir:
        con.execute(f"SET extension_directory='{ext_dir}'")
    for ext in ("httpfs", "spatial"):
        try:
            con.execute(f"LOAD {ext}")
        except Exception:
            con.execute(f"INSTALL {ext}")
            con.execute(f"LOAD {ext}")
    return con


_SELECT = {
    "places": """id, names."primary" AS name, basic_category AS category, taxonomy."primary" AS taxonomy,
                 round(confidence, 3) AS confidence, addresses[1].freeform AS address,
                 addresses[1].locality AS locality, websites[1] AS website""",
    "buildings": """id, names."primary" AS name, class, subtype, height AS height_m, num_floors""",
    "transportation": """id, names."primary" AS name, class, subtype""",
    "divisions": """id, names."primary" AS name, subtype, class, admin_level, country, region""",
}


def query(
    theme: str,
    lat: float,
    lon: float,
    radius_m: float = 500,
    category: str | None = None,
    limit: int | None = None,
) -> SpatialResult:
    """Overture features of one theme around a point (``divisions``: the areas containing it).

    Distances from the point are geodesic; results come nearest first. Raises ``ValueError``
    for bad arguments and ``OvertureError`` when the data can't be reached.
    """
    if theme not in _THEMES:
        raise ValueError(f"Unknown Overture theme '{theme}'. Choose from: {sorted(_THEMES)}")
    from geospark.runs import record

    request = {"theme": theme, "lat": lat, "lon": lon, "radius_m": radius_m, "category": category, "limit": limit}
    result = _query_cached(theme, lat, lon, radius_m, category, limit)
    record("data", f"overture/{theme}", request, result.features, "overture-maps")
    return result


def _query_cached(
    theme: str, lat: float, lon: float, radius_m: float, category: str | None, limit: int | None,
) -> SpatialResult:
    key = (theme, round(lat, 5), round(lon, 5), radius_m, (category or "").lower(), limit)
    with _lock:
        hit = _results.get(key)
        if hit and time.time() - hit[0] < _RESULT_TTL_S:
            _results.move_to_end(key)
            return hit[1].model_copy(deep=True)
    if not _query_gate.acquire(timeout=_QUEUE_WAIT_S):
        raise OvertureError("Overture queries are busy; please retry shortly.")
    try:
        result = _query(theme, lat, lon, radius_m, category, limit)
    finally:
        _query_gate.release()
    with _lock:
        _results[key] = (time.time(), result.model_copy(deep=True))
        while len(_results) > 256:
            _results.popitem(last=False)
    return result


def _query(
    theme: str, lat: float, lon: float, radius_m: float, category: str | None, limit: int | None,
) -> SpatialResult:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude must be in [-90, 90] and longitude in [-180, 180]")
    if not 0 < radius_m <= MAX_RADIUS_M:
        raise ValueError(f"radius_m must be between 0 and {MAX_RADIUS_M} m (Overture queries are capped)")
    typ, max_rows = _THEMES[theme]
    limit = min(limit or max_rows, max_rows)

    release = latest_release()
    if theme == "divisions":
        south, west, north, east = lat, lon, lat, lon
    else:
        south, west, north, east = overpass_bbox(lat, lon, radius_m)
    try:
        files = _files_for(release, theme, typ, (west, south, east, north))
    except httpx.HTTPError as e:
        raise OvertureError(f"Overture release index unavailable ({type(e).__name__})") from e
    if not files:
        return _result(theme, release, [], lat, lon, radius_m, files_read=0)

    where = [f"bbox.xmin <= {east} AND bbox.xmax >= {west} AND bbox.ymin <= {north} AND bbox.ymax >= {south}"]
    params: list[Any] = []
    # DuckDB only filters; every measurement (distance, area, length, containment) is computed
    # by GeoSpark's own geodesic engine afterwards, so all answers share one documented method.
    geometry_sql = "ST_AsWKB(geometry)"
    if theme == "divisions":
        # Exact containment in SQL (only the matching areas are transferred, simplified), land
        # areas only (each division also has a territorial-waters variant)
        where.append(f"is_land AND ST_Contains(geometry, ST_Point({lon}, {lat}))")
        geometry_sql = "ST_AsWKB(ST_SimplifyPreserveTopology(geometry, 0.001))"
        # No ORDER BY here: DuckDB 2.0.0 hits an internal error ordering this theme by
        # admin_level under a bbox filter. Sorted in Python instead.
        order = None
        limit = 50  # candidates by bbox; containment is checked exactly below
    else:
        # planar ordering in degrees, good enough to pick the nearest candidates locally
        order: str | None = f"ST_Distance(ST_Centroid(geometry), ST_Point({lon}, {lat}))"
    if theme == "places" and category:
        where.append("(basic_category ILIKE ? OR list_contains(taxonomy.hierarchy, lower(?)))")
        params += [category, category]

    sql = f"""
        SELECT {_SELECT[theme]}, {geometry_sql} AS geometry_wkb,
               list_distinct([s.license FOR s IN sources]) AS licenses
        FROM read_parquet(?, hive_partitioning = 1)
        WHERE {" AND ".join(where)}
        {f"ORDER BY {order}" if order else ""}
        LIMIT {int(limit)}
    """
    try:
        con = _connection()
        cursor = con.execute(sql, [files, *params])
        columns = [d[0] for d in cursor.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        con.close()
    except OvertureError:
        raise
    except Exception as e:
        raise OvertureError(f"Overture query failed ({type(e).__name__}: {str(e)[:200]})") from e
    return _result(theme, release, rows, lat, lon, radius_m, files_read=len(files))


def _result(
    theme: str, release: str, rows: list[dict[str, Any]], lat: float, lon: float, radius_m: float,
    files_read: int,
) -> SpatialResult:
    import shapely
    import shapely.ops
    from pyproj import Geod
    from shapely.geometry import Point, mapping

    geod = Geod(ellps="WGS84")
    here = Point(lon, lat)
    features: list[SpatialFeature] = []
    licenses: set[str] = set()
    for row in rows:
        geom = shapely.from_wkb(bytes(row.pop("geometry_wkb")))
        row_licenses = row.pop("licenses") or []
        properties = {k: v for k, v in row.items() if v is not None}
        if theme == "divisions":
            pass  # containment already checked exactly in SQL
        else:
            nearest = shapely.ops.nearest_points(geom, here)[0]
            distance = geod.inv(lon, lat, nearest.x, nearest.y)[2]
            if distance > radius_m * 1.0001:
                continue  # the bbox is square; keep the circle
            properties["distance_m"] = round(distance, 1)
            if theme == "buildings":
                properties["footprint_area_sq_m"] = round(abs(geod.geometry_area_perimeter(geom)[0]), 1)
            elif theme == "transportation":
                properties["length_m"] = round(geod.geometry_length(geom), 1)
        licenses.update(row_licenses)
        features.append(SpatialFeature(geometry=mapping(geom), properties=properties, id=properties.get("id")))
    if theme == "divisions":  # broadest first: country, region, county, locality, ...
        features.sort(key=lambda f: (f.properties.get("admin_level") is None, f.properties.get("admin_level") or 0))
    else:
        features.sort(key=lambda f: f.properties["distance_m"])

    result = SpatialResult(
        features=features,
        spatial_context=SpatialContext(
            total_features=len(features),
            summary=(f"{len(features)} Overture {theme} feature(s) "
                     + ("containing the point" if theme == "divisions" else f"within {radius_m:.0f} m")
                     + f" (release {release})"),
        ),
        sources=["overture-maps"],
    )
    result.provenance.append(source_provenance(
        "overture-maps",
        licence=", ".join(sorted(licenses)) or None,
        dataset_version=release,
        method=f"DuckDB spatial query of Overture GeoParquet ({files_read} file(s) read, selected via the "
               "release's STAC index); distances geodesic on WGS84",
    ))
    from geospark.protocol.provenance import enrich

    enrich(result, f"overture_{theme}")
    if len(features) >= _THEMES[theme][1]:
        result.warnings.append(f"Result capped at {_THEMES[theme][1]} features; use a smaller radius.")
    return result
