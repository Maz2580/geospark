"""Bring your own data: every format, CRS handling (never guessed), repairs, geodesic analysis."""

from __future__ import annotations

import json
import random
import zipfile

import pytest
import shapely
from pyproj import Geod, Transformer
from shapely.geometry import Point, Polygon, box, mapping

pyogrio = pytest.importorskip("pyogrio")

from geospark.io import layers  # noqa: E402
from geospark.io.layers import LayerError, count_within, intersect, load_layer, nearest  # noqa: E402

GEOD = Geod(ellps="WGS84")
MELB = (144.9631, -37.8136)


def write(path, geoms, props, crs="EPSG:4326", driver=None, **kw):
    import numpy as np
    from pyogrio.raw import write as raw_write

    fields = list(props[0]) if props else []
    raw_write(path, np.array([shapely.to_wkb(g) for g in geoms], dtype=object),
              geometry_type=geoms[0].geom_type, field_data=[np.array([p[f] for p in props]) for f in fields],
              fields=fields, crs=crs, driver=driver, **kw)
    return path


def melbourne_suburbs():
    """Two 1 km squares side by side, in WGS84."""
    x, y = MELB
    dx = 1000 / (111_320 * 0.79)
    dy = 1000 / 110_950
    return [box(x, y, x + dx, y + dy), box(x + dx, y, x + 2 * dx, y + dy)]


# --- formats and CRS ----------------------------------------------------------------------------

def test_geojson_round_trip(tmp_path) -> None:
    path = write(tmp_path / "parks.geojson", melbourne_suburbs(), [{"name": "A"}, {"name": "B"}], driver="GeoJSON")
    layer = load_layer(path)
    assert len(layer) == 2 and layer.source_crs == "EPSG:4326"
    assert layer.properties[0]["name"] == "A"
    assert len(layer.sha256) == 64
    assert layer.provenance.dataset_version == f"sha256:{layer.sha256}"


def test_projected_geopackage_is_reprojected_and_reported(tmp_path) -> None:
    to_mga = Transformer.from_crs("EPSG:4326", "EPSG:7855", always_xy=True)  # GDA2020 / MGA zone 55
    from geospark.engine.crs_handler import reproject

    projected = [reproject(g, to_mga) for g in melbourne_suburbs()]
    path = write(tmp_path / "suburbs.gpkg", projected, [{"name": "A"}, {"name": "B"}], crs="EPSG:7855", driver="GPKG")
    layer = load_layer(path)
    assert layer.source_crs == "EPSG:7855"
    minx, miny, _maxx, _maxy = layer.geometries[0].bounds
    assert minx == pytest.approx(MELB[0], abs=1e-4) and miny == pytest.approx(MELB[1], abs=1e-4)  # back in lon/lat
    summary = layer.summary().features[0].properties
    assert summary["total_area_sq_km"] == pytest.approx(2.0, rel=0.02)  # two ~1 km2 squares, geodesic
    assert "reprojected from EPSG:7855" in layer.provenance.method


def test_shapefile_without_prj_is_refused_unless_crs_given(tmp_path) -> None:
    path = write(tmp_path / "noprj.shp", [Point(320000, 5810000)], [{"id": 1}], crs=None, driver="ESRI Shapefile")
    with pytest.raises(LayerError, match="won't guess"):
        load_layer(path)
    layer = load_layer(path, crs="EPSG:28355")  # MGA zone 55 (GDA94)
    lon, lat = layer.geometries[0].x, layer.geometries[0].y
    assert 144 < lon < 145 and -38 < lat < -37


def test_zipped_shapefile(tmp_path) -> None:
    write(tmp_path / "pts.shp", [Point(*MELB)], [{"id": 1}], driver="ESRI Shapefile")
    archive = tmp_path / "pts.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for part in tmp_path.glob("pts.*"):
            if part.suffix != ".zip":
                zf.write(part, part.name)
    assert len(load_layer(archive)) == 1


def test_geoparquet_with_and_without_crs(tmp_path) -> None:
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    def geoparquet(path, crs_entry):
        table = pa.table({"name": ["A"], "geometry": [shapely.to_wkb(Point(*MELB))]})
        geo = {"version": "1.1.0", "primary_column": "geometry",
               "columns": {"geometry": {"encoding": "WKB", "geometry_types": ["Point"], **crs_entry}}}
        pq.write_table(table.replace_schema_metadata({b"geo": json.dumps(geo).encode()}), path)
        return path

    assert load_layer(geoparquet(tmp_path / "a.parquet", {})).source_crs == "OGC:CRS84"  # spec default
    with pytest.raises(LayerError, match="unknown CRS"):
        load_layer(geoparquet(tmp_path / "b.parquet", {"crs": None}))
    plain = tmp_path / "plain.parquet"
    pq.write_table(pa.table({"x": [1]}), plain)
    with pytest.raises(LayerError, match="not GeoParquet"):
        load_layer(plain)


def test_csv_with_lon_lat_is_read_with_a_warning(tmp_path) -> None:
    path = tmp_path / "stops.csv"
    path.write_text("name,latitude,longitude\nFlinders St,-37.8183,144.9671\nMelbourne Central,-37.8100,144.9628\n")
    layer = load_layer(path)
    assert len(layer) == 2 and layer.properties[0] == {"name": "Flinders St"}
    assert any("read 'longitude'/'latitude' as WGS84" in w for w in layer.warnings)


def test_csv_with_projected_numbers_is_refused(tmp_path) -> None:
    path = tmp_path / "mga.csv"
    path.write_text("name,lat,lon\nA,5810000,320000\n")
    with pytest.raises(LayerError, match="not a valid longitude/latitude"):
        load_layer(path)
    xy = tmp_path / "xy.csv"
    xy.write_text("name,x,y\nA,320000,5810000\n")
    with pytest.raises(LayerError, match="could be projected"):
        load_layer(xy)
    assert 144 < load_layer(xy, crs="EPSG:28355").geometries[0].x < 145


def test_invalid_geometry_is_refused_or_repaired(tmp_path) -> None:
    bowtie = Polygon([(144.96, -37.82), (144.98, -37.81), (144.98, -37.82), (144.96, -37.81)])
    path = write(tmp_path / "bad.geojson", [bowtie], [{"id": 1}], driver="GeoJSON")
    with pytest.raises(LayerError, match="Self-intersection"):
        load_layer(path)
    layer = load_layer(path, repair=True)
    assert layer.geometries[0].is_valid and any("repaired" in w for w in layer.warnings)


def test_missing_and_oversized_files(tmp_path, monkeypatch) -> None:
    with pytest.raises(LayerError, match="not found"):
        load_layer(tmp_path / "nope.geojson")
    path = write(tmp_path / "x.geojson", [Point(*MELB)], [{"id": 1}], driver="GeoJSON")
    monkeypatch.setattr(layers, "MAX_FILE_BYTES", 10)
    with pytest.raises(LayerError, match="larger than"):
        load_layer(path)


# --- analysis -----------------------------------------------------------------------------------------

def test_count_within(tmp_path) -> None:
    a, b = melbourne_suburbs()
    inside_a = [a.centroid, Point(a.centroid.x + 0.001, a.centroid.y)]
    pts = load_layer(write(tmp_path / "p.geojson", [*inside_a, b.centroid], [{"i": 0}, {"i": 1}, {"i": 2}], driver="GeoJSON"))
    polys = load_layer(write(tmp_path / "s.geojson", [a, b], [{"name": "A"}, {"name": "B"}], driver="GeoJSON"))
    result = count_within(pts, polys)
    counts = {f.properties["name"]: f.properties["count"] for f in result.features}
    assert counts == {"A": 2, "B": 1}
    assert result.features[0].properties["area_sq_km"] == pytest.approx(1.0, rel=0.02)
    assert {p.source for p in result.provenance} >= {"user-data", "geospark-engine"}


def test_nearest_matches_brute_force_geodesic_at_high_latitude(tmp_path) -> None:
    """At 70°N a degree of longitude is ~38 km, so planar lon/lat 'nearest' is often wrong."""
    rng = random.Random(7)
    targets = [Point(20 + rng.uniform(-2, 2), 70 + rng.uniform(-0.5, 0.5)) for _ in range(200)]
    sources = [Point(20 + rng.uniform(-2, 2), 70 + rng.uniform(-0.5, 0.5)) for _ in range(40)]
    t = load_layer(write(tmp_path / "t.geojson", targets, [{"tid": i} for i in range(200)], driver="GeoJSON"))
    s = load_layer(write(tmp_path / "s.geojson", sources, [{"sid": i} for i in range(40)], driver="GeoJSON"))
    result = nearest(s, t)
    for feature, src in zip(result.features, sources, strict=True):
        brute = min(GEOD.inv(src.x, src.y, tg.x, tg.y)[2] for tg in targets)
        assert feature.properties["nearest_distance_m"] == pytest.approx(brute, abs=0.01)
    assert result.spatial_context.units["nearest_distance_m"] == "metre"


def test_intersect_areas_are_geodesic(tmp_path) -> None:
    a, _ = melbourne_suburbs()
    half = box(a.bounds[0], a.bounds[1], (a.bounds[0] + a.bounds[2]) / 2, a.bounds[3])
    la = load_layer(write(tmp_path / "a.geojson", [a], [{"zone": "residential"}], driver="GeoJSON"))
    lb = load_layer(write(tmp_path / "b.geojson", [half], [{"flood": "1%AEP"}], driver="GeoJSON"))
    piece = intersect(la, lb).features[0].properties
    assert piece["a_zone"] == "residential" and piece["b_flood"] == "1%AEP"
    assert piece["area_sq_m"] == pytest.approx(500_000, rel=0.02)


def test_layer_exports_geojson_for_qgis(tmp_path) -> None:
    layer = load_layer(write(tmp_path / "x.geojson", melbourne_suburbs(), [{"n": 1}, {"n": 2}], driver="GeoJSON"))
    fc = layer.to_result().to_geojson()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 2
    assert fc["geospark"]["provenance"][0]["dataset_version"].startswith("sha256:")
    assert mapping(layer.geometries[0])["type"] == "Polygon"


def test_cli_layer_commands(tmp_path) -> None:
    from click.testing import CliRunner

    from geospark.cli import main

    a, b = melbourne_suburbs()
    pts = write(tmp_path / "p.geojson", [a.centroid, b.centroid], [{"i": 0}, {"i": 1}], driver="GeoJSON")
    polys = write(tmp_path / "s.geojson", [a, b], [{"name": "A"}, {"name": "B"}], driver="GeoJSON")
    runner = CliRunner()
    info = runner.invoke(main, ["layer", "info", str(polys)])
    assert info.exit_code == 0 and "EPSG:4326" in info.output
    out = tmp_path / "counts.geojson"
    counted = runner.invoke(main, ["layer", "count-within", str(pts), str(polys), "--geojson", str(out)])
    assert counted.exit_code == 0 and json.loads(out.read_text())["features"][0]["properties"]["count"] == 1
    assert runner.invoke(main, ["layer", "nearest", str(pts), str(polys)]).exit_code == 0
    noprj = write(tmp_path / "n.shp", [Point(320000, 5810000)], [{"id": 1}], crs=None, driver="ESRI Shapefile")
    refused = runner.invoke(main, ["layer", "info", str(noprj)])
    assert refused.exit_code == 1 and "won't guess" in refused.output
