"""Point clouds (LAS, LAZ, COPC) and rasters (GeoTIFF, COG) for ``layer check``, read with terrio.

terrio (https://github.com/opengeos/terrio) reads these formats in pure Rust, without GDAL or PDAL,
from local files or URLs (a remote COPC or COG is read in place, only the parts needed). It is an
optional dependency: ``pip install "geospark-ai[pointcloud]"``.

GeoSpark uses terrio only to read. Datum and height conversions still go through
``geospark.geodesy``: like PROJ, terrio keeps a height unchanged when a geoid grid is missing
(tested: AHD came back equal to the ellipsoidal height in Melbourne, 4.7 m off, with no warning),
and GeoSpark refuses that rather than return it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyproj import CRS

POINT_SUFFIXES = (".las", ".laz")
RASTER_SUFFIXES = (".tif", ".tiff")
SAMPLE_POINTS = 20_000  # points read for a one-file check
MAX_MARKS = 500  # survey marks looked up in a comparison
GROUND_RADIUS_M = 1.0  # ground points within this distance of a mark give its surface height
_LIDAR_GROUND = 2  # ASPRS classification code


class SurfaceError(ValueError):
    pass


def kind(path: str | Path) -> str | None:
    """'pointcloud', 'raster' or None (a vector file), from the name."""
    name = str(path).lower().split("?")[0]
    if name.endswith(POINT_SUFFIXES):
        return "pointcloud"
    if name.endswith(RASTER_SUFFIXES):
        return "raster"
    return None


def is_remote(path: str | Path) -> bool:
    return str(path).startswith(("http://", "https://", "s3://", "gs://", "az://"))


def available() -> bool:
    try:
        import terrio  # noqa: F401
    except ImportError:
        return False
    return True


def _terrio() -> Any:
    try:
        import terrio
    except ImportError:
        raise SurfaceError('Reading point clouds and rasters needs terrio: pip install "geospark-ai[pointcloud]"') from None
    return terrio


def _unit_factor(crs: CRS | None, axis: int) -> float:
    """Metres per unit of an axis (a US survey foot is 1200/3937 m)."""
    if crs is None or len(crs.axis_info) <= axis:
        return 1.0
    return float(crs.axis_info[axis].unit_conversion_factor or 1.0)


@dataclass
class Surface:
    name: str
    kind: str  # "pointcloud" or "raster"
    horizontal: CRS | None
    vertical: CRS | None
    crs_declared: bool
    count: int  # points, or cells
    xy: list[tuple[float, float]]  # a sample, in the horizontal CRS
    z_m: list[float | None]  # heights of the sample in metres (None for a raster: values aren't read here)
    ground: bool = False  # a point cloud with ground-classified points
    warnings: list[str] = field(default_factory=list)
    _source: Any = None
    _path: str = ""

    @property
    def crs(self) -> CRS | None:
        """The compound CRS when a vertical one is declared, else the horizontal one."""
        if self.horizontal is not None and self.vertical is not None:
            return CRS.from_user_input(f"{_code(self.horizontal)}+{_code(self.vertical)}") \
                if _code(self.horizontal) and _code(self.vertical) else self.horizontal
        return self.horizontal

    @property
    def z_factor(self) -> float:
        """Metres per height unit: the vertical CRS's unit, else the horizontal one's for a point cloud."""
        if self.vertical is not None:
            return _unit_factor(self.vertical, 0)
        return _unit_factor(self.horizontal, 0) if self.kind == "pointcloud" and self.horizontal is not None \
            and self.horizontal.is_projected else 1.0

    def heights_at(self, xy: list[tuple[float, float]]) -> list[float | None]:
        """Surface height in metres at each point (in the horizontal CRS); None where there is none."""
        if not xy:
            return []
        return self._points_at(xy) if self.kind == "pointcloud" else self._cells_at(xy)

    def _cells_at(self, xy: list[tuple[float, float]]) -> list[float | None]:
        r = self._source
        x0, dx, rx, y0, ry, dy = r.transform
        out: list[float | None] = []
        for x, y in xy:
            if rx or ry:  # rotated rasters are rare; refuse rather than read the wrong cell
                raise SurfaceError("Rotated rasters aren't supported.")
            col, row = int((x - x0) // dx), int((y - y0) // dy)
            if not (0 <= col < r.width and 0 <= row < r.height):
                out.append(None)
                continue
            v = float(r.read(1, window=(col, row, 1, 1)).ravel()[0])
            out.append(None if not math.isfinite(v) or (r.nodata is not None and v == r.nodata) else v * self.z_factor)
        return out

    def _points_at(self, xy: list[tuple[float, float]]) -> list[float | None]:
        import numpy as np

        terrio = _terrio()
        radius = GROUND_RADIUS_M / _unit_factor(self.horizontal, 0)
        classes = (_LIDAR_GROUND,) if self.ground else None
        xs, ys = [p[0] for p in xy], [p[1] for p in xy]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) * _unit_factor(self.horizontal, 0)
        # One read around all the marks when they are close together, else one small read per mark
        windows = [(min(xs), min(ys), max(xs), max(ys))] if span <= 2_000 else [(x, y, x, y) for x, y in xy]
        out: list[float | None] = [None] * len(xy)
        for w in windows:
            pad = 3 * radius
            pc = terrio.read_points(self._path, bounds=(w[0] - pad, w[1] - pad, w[2] + pad, w[3] + pad), classes=classes)
            a = pc.to_numpy()
            if not len(a):
                continue
            order = np.argsort(a["x"])
            px, py, pz = a["x"][order], a["y"][order], a["z"][order]
            for i, (x, y) in enumerate(xy):
                if out[i] is not None or not (w[0] <= x <= w[2] and w[1] <= y <= w[3]):
                    continue
                for r in (radius, 3 * radius):
                    lo, hi = np.searchsorted(px, x - r), np.searchsorted(px, x + r)
                    near = (px[lo:hi] - x) ** 2 + (py[lo:hi] - y) ** 2 <= r * r
                    if near.any():
                        out[i] = float(np.median(pz[lo:hi][near])) * self.z_factor
                        break
        return out


def _code(crs: CRS) -> str | None:
    auth = crs.to_authority()
    return f"{auth[0]}:{auth[1]}" if auth else None


def _vertical_from_wkt(wkt: str) -> CRS | None:
    try:
        crs = CRS.from_wkt(wkt)
    except Exception:
        return None
    if crs.is_compound:
        return next((c for c in crs.sub_crs_list if c.is_vertical), None)
    return None


def open_surface(path: str | Path, crs: str | None = None) -> Surface:
    """Open a point cloud or raster and read a sample of it.

    Args:
        path: a local file or a URL.
        crs: the horizontal (or compound) CRS when the file doesn't declare one.
    """
    terrio = _terrio()
    where = str(path) if is_remote(path) else str(Path(path).expanduser())
    if not is_remote(path) and not Path(where).exists():
        raise SurfaceError(f"File not found: {where}")
    what = kind(path)
    name = where.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    given = CRS.from_user_input(crs) if crs else None
    try:
        if what == "pointcloud":
            return _open_points(terrio, where, name, given)
        if what == "raster":
            return _open_raster(terrio, where, name, given)
    except terrio.TerrioError as e:
        raise SurfaceError(f"{name} could not be read: {e}") from None
    raise SurfaceError(f"{name} is not a point cloud or raster GeoSpark reads (LAS, LAZ, COPC, GeoTIFF).")


def _split(given: CRS | None) -> tuple[CRS | None, CRS | None]:
    if given is None:
        return None, None
    if given.is_compound:
        subs = given.sub_crs_list
        return next((c for c in subs if not c.is_vertical), None), next((c for c in subs if c.is_vertical), None)
    return given, None


def _open_points(terrio: Any, where: str, name: str, given: CRS | None) -> Surface:
    f = terrio.open_points(where)
    info = f.info() if callable(f.info) else f.info
    declared = info.get("crs") or {}
    horizontal = vertical = None
    if declared.get("epsg"):
        horizontal = CRS.from_epsg(int(declared["epsg"]))
    elif declared.get("wkt"):
        horizontal = CRS.from_wkt(declared["wkt"])
    if info.get("vertical_epsg"):
        vertical = CRS.from_epsg(int(info["vertical_epsg"]))
    crs_declared = horizontal is not None
    if given is not None:
        g_h, g_v = _split(given)
        horizontal, vertical = g_h or horizontal, g_v or vertical
    pc = f.read(max_points=SAMPLE_POINTS)
    a = pc.to_numpy()
    ground = "classification" in (a.dtype.names or ()) and bool((a["classification"] == _LIDAR_GROUND).any())
    s = Surface(name, "pointcloud", horizontal, vertical, crs_declared, int(info.get("point_count") or len(a)),
                [(float(x), float(y)) for x, y in zip(a["x"], a["y"], strict=True)], [], ground, _source=f, _path=where)
    s.z_m = [float(z) * s.z_factor for z in a["z"]]
    return s


def _open_raster(terrio: Any, where: str, name: str, given: CRS | None) -> Surface:
    r = terrio.open_raster(where, lazy=True)
    horizontal = CRS.from_user_input(r.crs) if r.crs else None
    vertical = _vertical_from_wkt(r.crs_wkt) if getattr(r, "crs_wkt", None) else None
    if horizontal is not None and horizontal.is_compound:
        horizontal = next((c for c in horizontal.sub_crs_list if not c.is_vertical), horizontal)
    crs_declared = horizontal is not None
    if given is not None:
        g_h, g_v = _split(given)
        horizontal, vertical = g_h or horizontal, g_v or vertical
    x0, dx, _, y0, _, dy = r.transform
    n = 10  # a grid of cell centres across the raster, for the extent and zone checks
    xy = [(x0 + (i + 0.5) * r.width / n * dx, y0 + (j + 0.5) * r.height / n * dy) for i in range(n) for j in range(n)]
    warnings = [] if r.count == 1 else [f"{name} has {r.count} bands; heights are read from band 1."]
    return Surface(name, "raster", horizontal, vertical, crs_declared, int(r.width) * int(r.height), xy,
                   [None] * len(xy), warnings=warnings, _source=r, _path=where)
