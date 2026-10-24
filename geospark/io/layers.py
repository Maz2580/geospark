"""Bring your own data: load vector files, check their CRS, and analyse them geodesically.

Formats: GeoJSON, GeoPackage, Shapefile (.shp or a .zip), FlatGeobuf, KML, GML, File Geodatabase
(through GDAL/pyogrio), GeoParquet (through pyarrow) and CSV with longitude/latitude columns.

The CRS is **never guessed**:
- a file that declares a CRS is reprojected to WGS84, and the original CRS is reported;
- a file with no CRS (e.g. a Shapefile without .prj) is refused unless you pass ``crs=``;
- GeoParquet without a CRS uses the spec's default (OGC:CRS84), as the spec requires;
- a CSV is read as WGS84 only when its columns are clearly named longitude/latitude, and the
  result says so in a warning.

Every layer carries provenance: the file name, its SHA-256 (so an analysis can be reproduced
against exactly this data), the source CRS and the feature count.

Requires ``pip install geospark-ai[io]``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import shapely
import shapely.ops
import shapely.validation
from pyproj import CRS, Geod, Transformer
from shapely.geometry import Point, mapping
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree
from shapely.validation import make_valid

from geospark.protocol.provenance import Provenance, engine_provenance
from geospark.protocol.schema import SpatialContext, SpatialFeature, SpatialResult

MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_FEATURES = 200_000
_LON_NAMES = ("longitude", "lon", "lng", "long", "x")
_LAT_NAMES = ("latitude", "lat", "y")
_GEOD = Geod(ellps="WGS84")


class LayerError(ValueError):
    """The file can't be used as-is; the message says why and what to do."""


@dataclass
class Layer:
    """A vector layer in WGS84, with what's needed to trust and reproduce an analysis on it."""

    name: str
    geometries: list[BaseGeometry]
    properties: list[dict[str, Any]]
    source_crs: str
    sha256: str
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.geometries)

    @property
    def provenance(self) -> Provenance:
        return Provenance(
            source="user-data",
            name=self.name,
            method=f"Loaded by GeoSpark; reprojected from {self.source_crs} to WGS84 (EPSG:4326)"
            if self.source_crs not in ("EPSG:4326", "OGC:CRS84") else "Loaded by GeoSpark (already WGS84)",
            dataset_version=f"sha256:{self.sha256}",
        )

    def summary(self) -> SpatialResult:
        """Feature count, geometry types, bbox, fields, CRS, and total geodesic area/length."""
        types: dict[str, int] = {}
        area = length = 0.0
        for geom in self.geometries:
            types[geom.geom_type] = types.get(geom.geom_type, 0) + 1
            if geom.geom_type in ("Polygon", "MultiPolygon"):
                area += abs(_GEOD.geometry_area_perimeter(geom)[0])
            elif geom.geom_type in ("LineString", "MultiLineString"):
                length += _GEOD.geometry_length(geom)
        fields = sorted({k for p in self.properties for k in p})
        bounds = shapely.total_bounds(self.geometries) if self.geometries else None
        info = {
            "name": self.name, "features": len(self), "geometry_types": types, "fields": fields,
            "source_crs": self.source_crs, "sha256": self.sha256,
            "total_area_sq_km": round(area / 1e6, 4), "total_length_km": round(length / 1000, 3),
        }
        geometry = mapping(shapely.box(*bounds)) if bounds is not None else {"type": "Point", "coordinates": [0, 0]}
        return _result([SpatialFeature(geometry=geometry, properties=info)], self, f"{len(self)} features in {self.name}")

    def to_result(self) -> SpatialResult:
        """The layer itself as a SpatialResult (GeoJSON-ready)."""
        features = [SpatialFeature(geometry=mapping(g), properties=p) for g, p in zip(self.geometries, self.properties, strict=True)]
        return _result(features, self, f"{len(self)} features from {self.name}")


def _result(features: list[SpatialFeature], layer: Layer, summary: str, *others: Layer) -> SpatialResult:
    result = SpatialResult(features=features, spatial_context=SpatialContext(total_features=len(features), summary=summary))
    for source in (layer, *others):
        result.provenance.append(source.provenance)
        result.warnings.extend(w for w in source.warnings if w not in result.warnings)
    from geospark.protocol.provenance import enrich

    return enrich(result)


# --- loading --------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _common_frame(source: CRS) -> CRS:
    """The geographic CRS a file is converted to before analysis.

    PROJ's default step from GDA94 (and from GDA2020) to WGS 84 is a null transformation, so a GDA94
    file and a GDA2020 file of the same survey marks ended up 1.55 m apart in Melbourne. Australian
    data goes to GDA2020 with the official transformation instead; GDA2020 is then treated as WGS 84
    (they differ by decimetres), as PROJ does for every other datum.
    """
    datum = source.geodetic_crs.datum.name if source.geodetic_crs is not None and source.geodetic_crs.datum else ""
    if "Geocentric Datum of Australia 1994" in datum:
        return CRS.from_epsg(7844)
    return CRS.from_epsg(4326)


def _to_wgs84(geoms: list[BaseGeometry], source: CRS) -> list[BaseGeometry]:
    if source.equals(CRS.from_epsg(4326), ignore_axis_order=True) or source.equals(CRS("OGC:CRS84")):
        return geoms
    from geospark.engine.crs_handler import reproject

    transformer = Transformer.from_crs(source, _common_frame(source), always_xy=True)
    return [reproject(g, transformer) for g in geoms]


def _crs_name(crs: CRS) -> str:
    authority = crs.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else crs.name


def load_layer(path: str | Path, layer: str | None = None, crs: str | None = None, repair: bool = False) -> Layer:
    """Load a vector file as a WGS84 ``Layer``.

    Args:
        path: the file (GeoJSON, GeoPackage, Shapefile/.zip, GeoParquet, CSV, FlatGeobuf, KML, GML, GDB).
        layer: the layer name inside a multi-layer file (e.g. a GeoPackage).
        crs: the file's CRS when it doesn't declare one (e.g. "EPSG:28355"). Never assumed.
        repair: fix invalid geometries (with a warning) instead of refusing the file.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise LayerError(f"File not found: {p}")
    if p.is_file() and p.stat().st_size > MAX_FILE_BYTES:
        raise LayerError(f"{p.name} is larger than {MAX_FILE_BYTES // 2**20} MB; clip or filter it first.")
    suffix = p.suffix.lower()
    if suffix in (".parquet", ".geoparquet"):
        geoms, props, source_crs, warnings = _read_geoparquet(p, crs)
    elif suffix in (".csv", ".tsv"):
        geoms, props, source_crs, warnings = _read_csv(p, crs)
    else:
        geoms, props, source_crs, warnings = _read_gdal(p, layer, crs)

    if len(geoms) > MAX_FEATURES:
        raise LayerError(f"{p.name} has {len(geoms)} features; the limit is {MAX_FEATURES}.")
    wgs84 = _to_wgs84(geoms, source_crs)
    invalid = [i for i, g in enumerate(wgs84) if g is not None and not g.is_valid]
    if invalid:
        if not repair:
            reason = shapely.validation.explain_validity(wgs84[invalid[0]])
            raise LayerError(
                f"{len(invalid)} invalid geometr{'y' if len(invalid) == 1 else 'ies'} in {p.name} (first, feature "
                f"{invalid[0]}: {reason}). Results on invalid shapes would be wrong; pass repair=True "
                "(CLI: --repair) to fix them with make_valid."
            )
        for i in invalid:
            wgs84[i] = make_valid(wgs84[i])
        warnings.append(f"{len(invalid)} invalid geometr{'y was' if len(invalid) == 1 else 'ies were'} repaired with make_valid.")
    keep = [i for i, g in enumerate(wgs84) if g is not None and not g.is_empty]
    if len(keep) < len(wgs84):
        warnings.append(f"{len(wgs84) - len(keep)} feature(s) without geometry were skipped.")
    return Layer(
        name=p.name, geometries=[wgs84[i] for i in keep], properties=[props[i] for i in keep],
        source_crs=_crs_name(source_crs), sha256=_sha256(p) if p.is_file() else "directory", warnings=warnings,
    )


def _declared_or_given(declared: CRS | None, given: str | None, filename: str) -> CRS:
    if given:
        return CRS.from_user_input(given)
    if declared is None:
        raise LayerError(
            f"{filename} doesn't say which coordinate reference system it uses (for a Shapefile, the .prj "
            "is missing). GeoSpark won't guess: pass crs= (CLI: --crs), e.g. 'EPSG:28355' for MGA zone 55."
        )
    return declared


def _read_gdal(p: Path, layer: str | None, crs: str | None) -> tuple[list[Any], list[dict], CRS, list[str]]:
    try:
        from pyogrio.raw import read
    except ImportError as e:
        raise LayerError("Reading this format needs GDAL: pip install 'geospark-ai[io]'") from e
    target = f"/vsizip/{p}" if p.suffix.lower() == ".zip" else str(p)
    try:
        meta, _fids, wkb, columns = read(target, layer=layer)
    except Exception as e:
        raise LayerError(f"Could not read {p.name}: {e}") from e
    declared = CRS.from_user_input(meta["crs"]) if meta.get("crs") else None
    source = _declared_or_given(declared, crs, p.name)
    geoms = [shapely.from_wkb(g) if g is not None else None for g in wkb]
    fields = list(meta["fields"])
    props = [{f: _plain(columns[j][i]) for j, f in enumerate(fields)} for i in range(len(geoms))]
    return geoms, props, source, []


def _read_geoparquet(p: Path, crs: str | None) -> tuple[list[Any], list[dict], CRS, list[str]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        raise LayerError("Reading GeoParquet needs pyarrow: pip install 'geospark-ai[io]'") from e
    table = pq.read_table(p)
    meta = json.loads((table.schema.metadata or {}).get(b"geo", b"{}") or b"{}")
    column = meta.get("primary_column")
    if not column:
        raise LayerError(f"{p.name} is Parquet but not GeoParquet (no 'geo' metadata).")
    spec = meta.get("columns", {}).get(column, {})
    if spec.get("encoding", "WKB").upper() != "WKB":
        raise LayerError(f"{p.name} uses {spec.get('encoding')} geometry encoding; only WKB is supported.")
    if crs:
        source = CRS.from_user_input(crs)
    elif "crs" in spec and spec["crs"] is None:
        raise LayerError(f"{p.name} declares an unknown CRS (crs: null). Pass crs= to say which one it is.")
    else:  # GeoParquet spec: absent means OGC:CRS84
        source = CRS.from_user_input(spec["crs"]) if spec.get("crs") else CRS("OGC:CRS84")
    data = table.to_pylist()
    geoms = [shapely.from_wkb(row.pop(column)) if row.get(column) is not None else None for row in data]
    return geoms, [{k: _plain(v) for k, v in row.items()} for row in data], source, []


def _read_csv(p: Path, crs: str | None) -> tuple[list[Any], list[dict], CRS, list[str]]:
    with p.open(newline="", encoding="utf-8-sig") as fh:
        dialect = "excel-tab" if p.suffix.lower() == ".tsv" else "excel"
        rows = list(csv.DictReader(fh, dialect=dialect))
    if not rows:
        raise LayerError(f"{p.name} has no rows.")
    columns = {c.lower().strip(): c for c in rows[0]}
    lon_col = next((columns[n] for n in _LON_NAMES if n in columns), None)
    lat_col = next((columns[n] for n in _LAT_NAMES if n in columns), None)
    if not lon_col or not lat_col:
        raise LayerError(f"{p.name}: no longitude/latitude columns found (looked for {_LON_NAMES} and {_LAT_NAMES}).")
    warnings: list[str] = []
    if crs:
        source = CRS.from_user_input(crs)
    elif lon_col.lower() in ("x",) or lat_col.lower() in ("y",):
        raise LayerError(f"{p.name} has x/y columns, which could be projected metres. Pass crs= to say which CRS.")
    else:
        source = CRS.from_epsg(4326)
        warnings.append(f"{p.name}: no CRS in a CSV; read '{lon_col}'/'{lat_col}' as WGS84 longitude/latitude "
                        "(pass crs= if they are something else).")
    geoms: list[Any] = []
    for n, row in enumerate(rows, start=2):
        try:
            x, y = float(row[lon_col]), float(row[lat_col])
        except (TypeError, ValueError):
            geoms.append(None)
            continue
        if not crs and not (-180 <= x <= 180 and -90 <= y <= 90):
            raise LayerError(f"{p.name} line {n}: ({x}, {y}) is not a valid longitude/latitude. "
                             "If the file is projected, pass crs=.")
        geoms.append(Point(x, y))
    props = [{k: v for k, v in row.items() if k not in (lon_col, lat_col)} for row in rows]
    return geoms, props, source, warnings


def _plain(value: Any) -> Any:
    if hasattr(value, "item"):  # numpy scalar
        try:
            return value.item()
        except Exception:
            return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


# --- analysis (geodesic) ----------------------------------------------------------------------------


def count_within(points: Layer, polygons: Layer, label: str = "count") -> SpatialResult:
    """For each polygon, how many points fall inside it (point-in-polygon, exact)."""
    tree = STRtree(points.geometries)
    features = []
    for geom, props in zip(polygons.geometries, polygons.properties, strict=True):
        hits = tree.query(geom, predicate="contains")
        area = abs(_GEOD.geometry_area_perimeter(geom)[0])
        features.append(SpatialFeature(geometry=mapping(geom), properties={
            **props, label: len(hits),
            "area_sq_km": round(area / 1e6, 4),
            f"{label}_per_sq_km": round(len(hits) / (area / 1e6), 3) if area else None,
        }))
    result = _result(features, polygons, f"Points of {points.name} counted in {len(features)} polygons of {polygons.name}", points)
    result.provenance.append(engine_provenance("contains"))
    return result


def nearest(sources: Layer, targets: Layer) -> SpatialResult:
    """For each source feature, the nearest target and the geodesic distance to it (metres).

    The planar nearest target (in lon/lat) at distance d bounds the search: anything
    geodesically closer lies within d in latitude and d / cos(latitude) in longitude. All
    targets in that box are compared by geodesic distance, so the answer is right at any latitude.
    """
    if not targets.geometries:
        raise LayerError(f"{targets.name} has no features to search.")
    tree = STRtree(targets.geometries)
    features = []
    for geom, props in zip(sources.geometries, sources.properties, strict=True):
        first = int(tree.query_nearest(geom)[0])
        d = geom.distance(targets.geometries[first])
        lat = abs(geom.representative_point().y)
        dx = d / max(math.cos(math.radians(min(lat + d, 89.9))), 1e-6)
        minx, miny, maxx, maxy = geom.bounds
        pool = {first, *(int(i) for i in tree.query(shapely.box(minx - dx, miny - d, maxx + dx, maxy + d)))}
        best, best_d = first, float("inf")
        for i in pool:
            a, b = shapely.ops.nearest_points(geom, targets.geometries[i])
            dist = _GEOD.inv(a.x, a.y, b.x, b.y)[2]
            if dist < best_d:
                best, best_d = i, dist
        features.append(SpatialFeature(geometry=mapping(geom), properties={
            **props, "nearest_index": best, "nearest_distance_m": round(best_d, 2),
            **{f"nearest_{k}": v for k, v in targets.properties[best].items() if isinstance(v, (str, int, float))},
        }))
    result = _result(features, sources, f"Nearest {targets.name} feature for each of {len(features)} in {sources.name}", targets)
    result.provenance.append(engine_provenance("distance"))
    return result


def intersect(a: Layer, b: Layer) -> SpatialResult:
    """Pieces where features of ``a`` and ``b`` overlap, with both sides' attributes and geodesic area."""
    tree = STRtree(b.geometries)
    features = []
    for geom, props in zip(a.geometries, a.properties, strict=True):
        for j in tree.query(geom, predicate="intersects"):
            piece = geom.intersection(b.geometries[int(j)])
            if piece.is_empty:
                continue
            measures: dict[str, Any] = {}
            if piece.geom_type in ("Polygon", "MultiPolygon", "GeometryCollection"):
                measures["area_sq_m"] = round(abs(_GEOD.geometry_area_perimeter(piece)[0]), 2)
            elif piece.geom_type in ("LineString", "MultiLineString"):
                measures["length_m"] = round(_GEOD.geometry_length(piece), 2)
            features.append(SpatialFeature(geometry=mapping(piece), properties={
                **{f"a_{k}": v for k, v in props.items()},
                **{f"b_{k}": v for k, v in b.properties[int(j)].items()},
                **measures,
            }))
    result = _result(features, a, f"{len(features)} overlap piece(s) between {a.name} and {b.name}", b)
    result.provenance.append(engine_provenance("intersection"))
    return result
