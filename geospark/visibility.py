"""Terrain horizon and line of sight on the Copernicus GLO-30 DEM.

A ray from the observer is sampled across the DEM (bilinear between cells) and, at each distance d,
the terrain is lowered by the Earth's curvature less refraction, d^2 (1 - k) / 2R, with the standard
refraction coefficient k = 0.13 (a k-factor of about 1.15). The horizon in a direction is the highest
elevation angle any sample reaches; a line of sight is clear when the straight path between two
points stays above every sample, and for radio links the first Fresnel zone is reported too.

Limits, stated with every result: GLO-30 is a ~30 m surface model, so it includes forest canopy and
large buildings only coarsely, and nothing narrower than a cell; heights are above the EGM2008 geoid;
the sea, where there is no tile, is taken as 0 m. Checked against PVGIS horizon profiles: see
``docs/benchmarks/2026-10/sun_horizon.md``.

The approach (rays across a DEM with curvature and refraction) follows geo-sleuth's terrain.py
(https://github.com/Oldcircle/geo-sleuth, MIT); this implementation is GeoSpark's own.
"""
from __future__ import annotations

import math
import os
from typing import Any

import numpy as np
from pyproj import Geod

from geospark.tools.terrain import copernicus

EARTH_RADIUS_M = 6_371_008.8
REFRACTION_K = 0.13
MAX_HORIZON_M = 50_000
MAX_LINK_M = 150_000
_GEOD = Geod(ellps="WGS84")
_NEAR_STEP_M = 30.0  # about one GLO-30 cell
_NEAR_LIMIT_M = 5_000.0  # beyond this, samples are spaced 0.6% of the distance apart
_FAR_FACTOR = 4  # and read from ~120 m overviews


class VisibilityError(ValueError):
    pass


def _check(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise VisibilityError("Latitude must be -90..90 and longitude -180..180.")
    if abs(lat) > 84:
        raise VisibilityError("The DEM and this method are not used beyond 84° latitude.")


class _Dem:
    """Bilinear heights from the GLO-30 tiles, reading one window per tile per request."""

    def __init__(self) -> None:
        self.sea_samples = 0

    def heights(self, lon: np.ndarray, lat: np.ndarray, factor: int = 1) -> np.ndarray:
        """Heights at the points; factor > 1 reads the DEM that many times coarser (its overviews)."""
        out = np.zeros(lon.shape, dtype=float)
        keys = np.floor(lat).astype(int) * 1000 + np.floor(lon).astype(int)
        for key in np.unique(keys):
            sel = keys == key
            south, west = math.floor(lat[sel][0]), math.floor(lon[sel][0])
            got = _tile_window(south, west, lon[sel], lat[sel], factor)
            if got is None:
                self.sea_samples += int(sel.sum())
                continue
            out[sel] = got
        return out


def _tile_window(south: int, west: int, lon: np.ndarray, lat: np.ndarray, factor: int = 1) -> np.ndarray | None:
    """Heights at the points from the GLO-30 tile at (south, west); None where there is no tile.

    With factor > 1 the window is read at 1/factor resolution, which GDAL serves from the tile's
    overviews: far fewer bytes for distant terrain, where samples are far apart anyway.
    """
    from rasterio.enums import Resampling  # type: ignore[import-untyped]
    from rasterio.errors import RasterioIOError  # type: ignore[import-untyped]
    from rasterio.windows import Window  # type: ignore[import-untyped]

    for name, value in copernicus._GDAL_ENV.items():
        os.environ.setdefault(name, value)
    try:
        dataset, lock = copernicus._open_tile(copernicus.tile_url(south + 0.5, west + 0.5))
    except RasterioIOError as exc:
        if "404" in str(exc) or "does not exist" in str(exc):
            return None
        raise VisibilityError(f"Copernicus DEM tile could not be read: {exc}") from exc
    x0, dx, _, y0, _, dy = dataset.transform.to_gdal()
    # Fractional cell coordinates of each point, cell centres at integer + 0.5
    cx = (lon - x0) / dx - 0.5
    cy = (lat - y0) / dy - 0.5
    c0, c1 = max(int(np.floor(cx.min())), 0), min(int(np.floor(cx.max())) + 2, dataset.width)
    r0, r1 = max(int(np.floor(cy.min())), 0), min(int(np.floor(cy.max())) + 2, dataset.height)
    if factor > 1:
        # Snap the window to whole coarse cells, read it decimated, and sample in coarse cells
        c0, r0 = c0 - c0 % factor, r0 - r0 % factor
        c1 = min(c1 + (-c1) % factor, dataset.width)
        r1 = min(r1 + (-r1) % factor, dataset.height)
        shape = (max((r1 - r0) // factor, 1), max((c1 - c0) // factor, 1))
        with lock:
            block = dataset.read(1, window=Window(c0, r0, c1 - c0, r1 - r0), out_shape=shape,
                                 resampling=Resampling.average).astype(float)
        cx = ((lon - x0) / dx - c0) / ((c1 - c0) / shape[1]) - 0.5
        cy = ((lat - y0) / dy - r0) / ((r1 - r0) / shape[0]) - 0.5
        c0 = r0 = 0
    else:
        with lock:
            block = dataset.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(float)
    nodata = dataset.nodata
    if nodata is not None:
        block[block == nodata] = 0.0
    fx, fy = np.clip(cx - c0, 0, block.shape[1] - 1.000001), np.clip(cy - r0, 0, block.shape[0] - 1.000001)
    ix, iy = np.floor(fx).astype(int), np.floor(fy).astype(int)
    ix1, iy1 = np.minimum(ix + 1, block.shape[1] - 1), np.minimum(iy + 1, block.shape[0] - 1)
    tx, ty = fx - ix, fy - iy
    top = block[iy, ix] * (1 - tx) + block[iy, ix1] * tx
    bottom = block[iy1, ix] * (1 - tx) + block[iy1, ix1] * tx
    return np.asarray(top * (1 - ty) + bottom * ty, dtype=float)


def _distances(max_m: float) -> np.ndarray:
    near = np.arange(_NEAR_STEP_M, min(max_m, _NEAR_LIMIT_M) + 1e-9, _NEAR_STEP_M)
    if max_m <= _NEAR_LIMIT_M:
        return near
    n = math.ceil(math.log(max_m / _NEAR_LIMIT_M) / math.log(1.006))
    far = _NEAR_LIMIT_M * 1.006 ** np.arange(1, n + 1)
    return np.concatenate([near, far[far <= max_m], [max_m]])


def _drop(d: np.ndarray) -> np.ndarray:
    """How far the terrain falls below the observer's tangent plane at distance d, after refraction."""
    return np.asarray(d * d * (1 - REFRACTION_K) / (2 * EARTH_RADIUS_M), dtype=float)


def _provenance() -> dict[str, Any]:
    return {"source": copernicus.SOURCE_NAME, "licence": "Copernicus WorldDEM-30 licence",
            "attribution": copernicus.ATTRIBUTION,
            "method": f"rays across the DEM, bilinear, curvature with refraction k={REFRACTION_K}"}


def _caveats(dem: _Dem, ground_given: bool) -> list[str]:
    out = ["Copernicus GLO-30 is a ~30 m surface model: forest canopy and large buildings are included coarsely, "
           "anything narrower than a cell is not; heights are above the EGM2008 geoid.",
           f"Refraction uses the standard coefficient k = {REFRACTION_K}; actual refraction varies with the "
           "weather, most near the horizon."]
    if not ground_given:
        out.append("The observer stands on the DEM surface, which on a roof or in a forest is the roof or canopy; "
                   "pass ground_elevation_m to give the true ground height.")
    if dem.sea_samples:
        out.append("Some samples fall where there is no DEM tile (open sea) and are taken as 0 m.")
    return out


def horizon(latitude: float, longitude: float, observer_height_m: float = 1.5, max_distance_m: float = 20_000,
            step_deg: float = 1.0, ground_elevation_m: float | None = None) -> dict[str, Any]:
    """The terrain horizon around a point: for each azimuth, the elevation angle of the skyline.

    Args:
        observer_height_m: eye or sensor height above the ground.
        max_distance_m: how far to look (up to 50 km).
        step_deg: azimuth spacing (0.5-10°).
        ground_elevation_m: the ground height at the point, when known better than the DEM.
    """
    _check(latitude, longitude)
    if not 0 <= observer_height_m <= 500:
        raise VisibilityError("observer_height_m must be 0-500 m.")
    if not 500 <= max_distance_m <= MAX_HORIZON_M:
        raise VisibilityError(f"max_distance_m must be 500-{MAX_HORIZON_M} m.")
    if not 0.5 <= step_deg <= 10 or abs(360 / step_deg - round(360 / step_deg)) > 1e-9:
        raise VisibilityError("step_deg must be 0.5-10 and divide 360 (e.g. 1, 2, 5).")
    dem = _Dem()
    ground = float(ground_elevation_m) if ground_elevation_m is not None else \
        float(dem.heights(np.array([longitude]), np.array([latitude]))[0])
    eye = ground + observer_height_m
    azimuths = np.arange(0, 360, step_deg)
    dist = _distances(max_distance_m)
    az_grid, d_grid = np.meshgrid(azimuths, dist, indexing="ij")
    lon, lat, _ = _GEOD.fwd(np.full(az_grid.size, longitude), np.full(az_grid.size, latitude),
                            az_grid.ravel(), d_grid.ravel())
    lon, lat = np.asarray(lon), np.asarray(lat)
    near = d_grid.ravel() <= _NEAR_LIMIT_M
    h = np.empty(lon.shape)
    h[near] = dem.heights(lon[near], lat[near])
    if (~near).any():  # distant terrain from the DEM's overviews, about 120 m cells
        h[~near] = dem.heights(lon[~near], lat[~near], factor=_FAR_FACTOR)
    h = h.reshape(az_grid.shape)
    angle = np.degrees(np.arctan2(h - _drop(d_grid) - eye, d_grid))
    best = angle.argmax(axis=1)
    rows = np.arange(len(azimuths))
    elev = angle[rows, best]
    return {
        "latitude": latitude, "longitude": longitude, "ground_elevation_m": round(ground, 2),
        "observer_height_m": observer_height_m, "max_distance_m": max_distance_m,
        "azimuths_deg": [float(a) for a in azimuths],
        "horizon_elevation_deg": [round(float(e), 3) for e in elev],
        "obstruction_distance_m": [round(float(dist[i])) for i in best],
        "obstruction_height_m": [round(float(h[r, i]), 1) for r, i in zip(rows, best, strict=True)],
        "highest": {"azimuth_deg": float(azimuths[int(elev.argmax())]), "elevation_deg": round(float(elev.max()), 3)},
        "method": _provenance()["method"], "provenance": [_provenance()],
        "warnings": _caveats(dem, ground_elevation_m is not None),
    }


def line_of_sight(lat_a: float, lon_a: float, lat_b: float, lon_b: float, height_a_m: float = 1.5,
                  height_b_m: float = 1.5, frequency_mhz: float | None = None) -> dict[str, Any]:
    """Whether two points see each other over the terrain, the minimum clearance and where it is.

    Heights are above the DEM surface at each end. With frequency_mhz, the first Fresnel zone
    clearance of a radio link is reported as well (60% clear is the usual design rule).
    """
    _check(lat_a, lon_a)
    _check(lat_b, lon_b)
    for name, value in (("height_a_m", height_a_m), ("height_b_m", height_b_m)):
        if not 0 <= value <= 1000:
            raise VisibilityError(f"{name} must be 0-1000 m.")
    if frequency_mhz is not None and not 1 <= frequency_mhz <= 300_000:
        raise VisibilityError("frequency_mhz must be 1-300,000.")
    azimuth, _back, total = _GEOD.inv(lon_a, lat_a, lon_b, lat_b)
    if total < 60:
        raise VisibilityError("The points are less than 60 m apart: closer than the DEM can resolve.")
    if total > MAX_LINK_M:
        raise VisibilityError(f"The points are {total / 1000:.0f} km apart; the limit is {MAX_LINK_M // 1000} km.")
    dem = _Dem()
    ends = dem.heights(np.array([lon_a, lon_b]), np.array([lat_a, lat_b]))
    eye_a, eye_b = float(ends[0]) + height_a_m, float(ends[1]) + height_b_m
    d = np.arange(_NEAR_STEP_M, total - _NEAR_STEP_M / 2, _NEAR_STEP_M)
    lon, lat, _ = _GEOD.fwd(np.full(d.size, lon_a), np.full(d.size, lat_a), np.full(d.size, azimuth), d)
    terrain = dem.heights(np.asarray(lon), np.asarray(lat))
    # The Earth bulges up between the ends by d1 d2 (1 - k) / 2R
    bulge = d * (total - d) * (1 - REFRACTION_K) / (2 * EARTH_RADIUS_M)
    ray = eye_a + (eye_b - eye_a) * d / total
    clearance = ray - (terrain + bulge)
    i = int(clearance.argmin())
    out: dict[str, Any] = {
        "visible": bool(clearance.min() > 0), "distance_m": round(total, 1),
        "bearing_deg": round(azimuth % 360, 3),
        "ground_elevation_a_m": round(float(ends[0]), 2), "ground_elevation_b_m": round(float(ends[1]), 2),
        "min_clearance_m": round(float(clearance[i]), 2),
        "min_clearance_at": {"distance_from_a_m": round(float(d[i])), "latitude": round(float(lat[i]), 6),
                             "longitude": round(float(lon[i]), 6), "terrain_m": round(float(terrain[i]), 1)},
    }
    if frequency_mhz is not None:
        wavelength = 299_792_458 / (frequency_mhz * 1e6)
        f1 = np.sqrt(wavelength * d * (total - d) / total)
        ratio = clearance / f1
        j = int(ratio.argmin())
        out["fresnel"] = {"frequency_mhz": frequency_mhz, "min_clearance_fraction_of_f1": round(float(ratio[j]), 3),
                          "at_distance_from_a_m": round(float(d[j])), "f1_radius_there_m": round(float(f1[j]), 2),
                          "sixty_percent_clear": bool(ratio.min() >= 0.6)}
    out.update(method=_provenance()["method"], provenance=[_provenance()],
               warnings=_caveats(dem, True)[:2] + (["Some samples fall where there is no DEM tile (open sea) and "
                                                     "are taken as 0 m."] if dem.sea_samples else [])
               + ["Heights at the ends are above the DEM surface, which may be a roof or forest canopy."])
    return out
