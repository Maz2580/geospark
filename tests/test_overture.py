"""Overture Maps client: release and file selection, geodesic measurements, caps and caching.

The DuckDB/S3 layer is faked with rows of known geometry, so distances, areas and lengths can
be checked exactly. One opt-in test (``-m network``) queries the real Overture data.
"""

from __future__ import annotations

import pytest
import shapely
from pyproj import Geod
from shapely.geometry import LineString, Point, Polygon

from geospark.tools.overture import client as ov

GEOD = Geod(ellps="WGS84")
FED_SQ = (-37.8180, 144.9691)  # lat, lon


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOSPARK_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GEOSPARK_OVERTURE_RELEASE", raising=False)
    ov._release_cache = None
    ov._results.clear()
    yield
    ov._release_cache = None
    ov._results.clear()


def offset(lat: float, lon: float, azimuth: float, metres: float) -> tuple[float, float]:
    x, y, _ = GEOD.fwd(lon, lat, azimuth, metres)
    return x, y


# --- releases and file selection --------------------------------------------------------------

ROOT = {"links": [
    {"rel": "child", "href": "https://stac.overturemaps.org/2026-09-23.1/catalog.json"},
    {"rel": "child", "href": "https://stac.overturemaps.org/2026-10-21.0/catalog.json"},
    {"rel": "root", "href": "https://stac.overturemaps.org/catalog.json"},
]}


def test_latest_release_and_pin(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(ov, "_http_json", lambda url: calls.append(url) or ROOT)
    assert ov.latest_release() == "2026-10-21.0"
    assert ov.latest_release() == "2026-10-21.0" and len(calls) == 1  # cached
    monkeypatch.setenv("GEOSPARK_OVERTURE_RELEASE", "2026-09-23.1")
    assert ov.latest_release() == "2026-09-23.1"


def test_only_files_covering_the_area_are_read(monkeypatch, tmp_path) -> None:
    items = {
        "a.json": {"bbox": [140, -40, 150, -30], "assets": {"aws": {"href": "s3://x/a.parquet"}}},  # Melbourne
        "b.json": {"bbox": [0, 40, 10, 50], "assets": {"aws": {"href": "s3://x/b.parquet"}}},       # Paris
    }
    collection = {"links": [{"rel": "item", "href": name} for name in items]}
    fetched = []

    def fake(url):
        fetched.append(url)
        return collection if url.endswith("collection.json") else items[url]

    monkeypatch.setattr(ov, "_http_json", fake)
    assert ov._files_for("R", "places", "place", (144.9, -37.9, 145.0, -37.8)) == ["s3://x/a.parquet"]
    assert ov._files_for("R", "places", "place", (2.2, 48.8, 2.4, 48.9)) == ["s3://x/b.parquet"]
    assert len(fetched) == 3  # the index is fetched once, then read from disk
    assert (tmp_path / "overture" / "R" / "places-place.json").exists()


# --- measurements -------------------------------------------------------------------------------

def _row(geom, **props):
    return {**props, "geometry_wkb": shapely.to_wkb(geom), "licenses": ["CDLA-Permissive-2.0"]}


def test_places_distances_are_geodesic_sorted_and_clipped_to_the_circle() -> None:
    lat, lon = FED_SQ
    near = Point(*offset(lat, lon, 90, 120))
    mid = Point(*offset(lat, lon, 200, 260))
    corner = Point(*offset(lat, lon, 45, 380))  # inside the square bbox, outside the 300 m circle
    rows = [_row(mid, id="m", name="Mid"), _row(corner, id="c", name="Corner"), _row(near, id="n", name="Near")]
    result = ov._result("places", "R1", rows, lat, lon, 300, files_read=1)
    assert [f.properties["name"] for f in result.features] == ["Near", "Mid"]
    assert result.features[0].properties["distance_m"] == pytest.approx(120, abs=0.2)
    assert result.spatial_context.units["distance_m"] == "metre"
    provenance = result.provenance[0]
    assert provenance.source == "overture-maps" and provenance.dataset_version == "R1"
    assert provenance.licence == "CDLA-Permissive-2.0" and "Overture" in provenance.attribution


def test_building_footprint_area_and_road_length_are_geodesic() -> None:
    lat, lon = FED_SQ
    sw = offset(lat, lon, 225, 40)
    se = (offset(sw[1], sw[0], 90, 30)[0], sw[1])
    ne = (se[0], offset(sw[1], sw[0], 0, 20)[1])
    nw = (sw[0], ne[1])
    footprint = Polygon([sw, se, ne, nw])
    road = LineString([offset(lat, lon, 0, 10), offset(lat, lon, 0, 110)])
    buildings = ov._result("buildings", "R", [_row(footprint, id="b", height_m=12.0)], lat, lon, 150, 1)
    roads = ov._result("transportation", "R", [_row(road, id="r", **{"class": "footway"})], lat, lon, 150, 1)
    assert buildings.features[0].properties["footprint_area_sq_m"] == pytest.approx(600, rel=0.01)
    assert buildings.spatial_context.units["footprint_area_sq_m"] == "square metre"
    assert roads.features[0].properties["length_m"] == pytest.approx(100, abs=0.5)
    assert roads.features[0].properties["distance_m"] == pytest.approx(10, abs=0.5)


def test_divisions_are_broadest_first() -> None:
    lat, lon = FED_SQ
    box = Point(lon, lat).buffer(0.01)
    rows = [_row(box, id="l", name="Melbourne", subtype="locality", admin_level=None),
            _row(box, id="c", name="Australia", subtype="country", admin_level=1),
            _row(box, id="r", name="Victoria", subtype="region", admin_level=2)]
    names = [f.properties["name"] for f in ov._result("divisions", "R", rows, lat, lon, 1, 1).features]
    assert names == ["Australia", "Victoria", "Melbourne"]


# --- the query path (DuckDB faked) ----------------------------------------------------------------

class FakeCursor:
    def __init__(self, rows):
        self.description = [(k,) for k in rows[0]] if rows else [("id",)]
        self._rows = [tuple(r.values()) for r in rows]

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return FakeCursor(self.rows)

    def close(self):
        pass


@pytest.fixture
def fake_overture(monkeypatch):
    lat, lon = FED_SQ
    rows = [_row(Point(*offset(lat, lon, 90, 50)), id="p1", name="NGV Cafe", category="cafe")]
    connection = FakeConnection(rows)
    monkeypatch.setattr(ov, "latest_release", lambda: "2026-10-21.0")
    monkeypatch.setattr(ov, "_files_for", lambda *a: ["s3://overture/part-1.parquet"])
    monkeypatch.setattr(ov, "_connection", lambda: connection)
    return connection


def test_query_reads_only_selected_files_with_category_filter(fake_overture) -> None:
    result = ov.query("places", *FED_SQ, radius_m=300, category="cafe")
    sql, params = fake_overture.calls[0]
    assert params[0] == ["s3://overture/part-1.parquet"] and params[1:] == ["cafe", "cafe"]
    assert "basic_category ILIKE ?" in sql and "LIMIT 500" in sql
    assert result.features[0].properties["name"] == "NGV Cafe"


def test_repeat_queries_come_from_the_cache(fake_overture) -> None:
    ov.query("places", *FED_SQ, radius_m=300)
    again = ov.query("places", *FED_SQ, radius_m=300)
    assert len(fake_overture.calls) == 1 and again.features


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"theme": "parks"}, "Unknown Overture theme"),
    ({"radius_m": 5000}, "radius_m"),
    ({"lat": 95}, "Latitude"),
])
def test_bad_arguments_are_refused(fake_overture, kwargs, message) -> None:
    args = {"theme": "places", "lat": FED_SQ[0], "lon": FED_SQ[1], "radius_m": 300, **kwargs}
    with pytest.raises(ValueError, match=message):
        ov.query(**args)


def test_duckdb_failure_is_an_overture_error(monkeypatch) -> None:
    monkeypatch.setattr(ov, "latest_release", lambda: "R")
    monkeypatch.setattr(ov, "_files_for", lambda *a: ["f"])

    class Broken:
        def execute(self, *a):
            raise RuntimeError("S3 timeout")

    monkeypatch.setattr(ov, "_connection", lambda: Broken())
    with pytest.raises(ov.OvertureError, match="S3 timeout"):
        ov.query("places", *FED_SQ)


# --- REST ---------------------------------------------------------------------------------------------

def test_rest_endpoint(fake_overture, monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from geospark.api import app

    monkeypatch.setenv("GEOSPARK_RATE_LIMIT_ENABLED", "false")
    client = TestClient(app)
    body = client.post("/api/v1/overture/places?format=geojson",
                       json={"lat": FED_SQ[0], "lon": FED_SQ[1], "radius_m": 300}).json()
    assert body["type"] == "FeatureCollection" and body["features"][0]["properties"]["name"] == "NGV Cafe"
    assert client.post("/api/v1/overture/parks", json={"lat": 0, "lon": 0}).status_code == 400
    assert client.post("/api/v1/overture/places", json={"lat": 0, "lon": 0, "radius_m": 9999}).status_code == 422


# --- live (opt-in) ---------------------------------------------------------------------------------------

@pytest.mark.network
def test_live_overture_divisions_contain_the_eiffel_tower() -> None:
    pytest.importorskip("duckdb")
    names = [f.properties.get("name") for f in ov.query("divisions", 48.8584, 2.2945).features]
    assert "France" in names and "Paris 7e Arrondissement" in names


def test_duckdb_resource_caps(monkeypatch) -> None:
    """On a shared server DuckDB must not take every core or most of the RAM."""
    pytest.importorskip("duckdb")
    monkeypatch.setenv("GEOSPARK_DUCKDB_THREADS", "2")
    monkeypatch.setenv("GEOSPARK_DUCKDB_MEMORY", "256MB")
    executed = []

    class Recorder:
        def execute(self, sql, *a):
            executed.append(sql)
            if sql.startswith("LOAD"):
                return None
            return None

    import duckdb

    monkeypatch.setattr(duckdb, "connect", lambda: Recorder())
    ov._connection()
    assert "SET threads = 2" in executed and "SET memory_limit = '256MB'" in executed


def test_only_one_duckdb_query_at_a_time(fake_overture, monkeypatch) -> None:
    """Two 512 MB DuckDB queries at once could exceed a 1 GB container: they queue instead."""
    import threading
    import time

    active, peak = [0], [0]
    real = ov._query

    def tracked(*args, **kwargs):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        time.sleep(0.2)
        try:
            return real(*args, **kwargs)
        finally:
            active[0] -= 1

    monkeypatch.setattr(ov, "_query", tracked)
    threads = [threading.Thread(target=ov.query, args=("places", -37.818 + i * 0.01, 144.969)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak[0] == 1
