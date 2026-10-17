"""
Copernicus DEM GLO-30 point heights.

Reads single cells from the public Copernicus GLO-30 cloud-optimised GeoTIFFs
on AWS (no key, no rate limit). Each 1 x 1 degree tile is about 30 m per cell,
so sharp relief such as summits comes out close to its true height. The Open
Elevation API, used before, read Wollumbin (about 1,156 m) as 959 m; GLO-30
reads 1,069 m at the same point and Kosciuszko as 2,226 m (official 2,228 m).

GLO-30 is a surface model: heights include trees and buildings. Heights are
orthometric, referenced to the EGM2008 geoid.

Licence: free for any use, including commercial, with this notice when the
data is distributed or shown (Copernicus WorldDEM-30 licence, Article 6):
see ``ATTRIBUTION``.

Usage:
    from geospark.tools.terrain.copernicus import read_height
    height = read_height(-36.4558, 148.2635)   # 2225.9
"""

from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from typing import Any

BUCKET_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
SOURCE_ID = "copernicus-dem"
SOURCE_NAME = "Copernicus DEM GLO-30"
ATTRIBUTION = (
    "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and "
    "Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights "
    "reserved. The organisations in charge of the Copernicus programme by law or by delegation "
    "do not incur any liability for any use of the Copernicus WorldDEM-30."
)

# Repeated lookups (the same summit, a map's corners) are answered from memory
_CACHE_SIZE = 4096
_cache: OrderedDict[tuple[float, float], float | None] = OrderedDict()
_cache_lock = threading.Lock()

# GDAL reads only the bytes it needs and keeps tile headers between calls
_GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "VSI_CACHE": "TRUE",
    "GDAL_HTTP_TIMEOUT": "15",
    "GDAL_HTTP_MAX_RETRY": "2",
}


class NoLandTileError(Exception):
    """No GLO-30 tile covers the point: open sea, or a tile left out of the public release."""


def available() -> bool:
    """True if rasterio is installed, which reading the tiles needs."""
    try:
        import rasterio  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        return False
    return True


def tile_url(lat: float, lon: float) -> str:
    """URL of the GLO-30 tile containing a point (tiles are named by their south-west corner)."""
    south, west = math.floor(lat), math.floor(lon)
    ns = f"N{south:02d}" if south >= 0 else f"S{-south:02d}"
    ew = f"E{west:03d}" if west >= 0 else f"W{-west:03d}"
    name = f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"
    return f"{BUCKET_URL}/{name}/{name}.tif"


def read_height(lat: float, lon: float) -> float:
    """Surface height in metres at a point.

    Raises:
        NoLandTileError: no tile covers the point (usually open sea).
        RuntimeError: the tile could not be read.
    """
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude must be -90..90 and longitude -180..180")
    key = (round(lat, 5), round(lon, 5))
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            cached = _cache[key]
            if cached is None:
                raise NoLandTileError(f"No Copernicus GLO-30 tile at ({lat}, {lon})")
            return cached

    height = _read_uncached(lat, lon)
    _remember(key, height)
    if height is None:
        raise NoLandTileError(f"No Copernicus GLO-30 tile at ({lat}, {lon})")
    return height


def _remember(key: tuple[float, float], height: float | None) -> None:
    with _cache_lock:
        _cache[key] = height
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)


# Open tiles are kept for reuse: reopening one costs several round trips to
# fetch its header, while a further point in an open tile needs one small
# range read. Rasterio datasets are not thread-safe, so each has a lock.
_OPEN_TILES = 16
_tiles: OrderedDict[str, tuple[Any, threading.Lock]] = OrderedDict()
_tiles_lock = threading.Lock()


def _open_tile(url: str) -> tuple[Any, threading.Lock]:
    import rasterio  # type: ignore[import-untyped]

    with _tiles_lock:
        if url in _tiles:
            _tiles.move_to_end(url)
            return _tiles[url]
    dataset = rasterio.open("/vsicurl/" + url)
    with _tiles_lock:
        if url in _tiles:  # opened meanwhile by another thread
            dataset.close()
            return _tiles[url]
        _tiles[url] = (dataset, threading.Lock())
        while len(_tiles) > _OPEN_TILES:
            old, _ = _tiles.popitem(last=False)[1]
            old.close()
        return _tiles[url]


def _read_uncached(lat: float, lon: float) -> float | None:
    from rasterio.errors import RasterioIOError  # type: ignore[import-untyped]

    for env_name, env_value in _GDAL_ENV.items():
        os.environ.setdefault(env_name, env_value)
    try:
        dataset, lock = _open_tile(tile_url(lat, lon))
        with lock:
            value = float(next(dataset.sample([(lon, lat)]))[0])
            nodata = dataset.nodata
    except RasterioIOError as exc:
        if "404" in str(exc) or "does not exist" in str(exc):
            return None
        raise RuntimeError(f"Copernicus DEM tile could not be read: {exc}") from exc
    if nodata is not None and value == nodata:
        return None
    return float(round(value, 1))
