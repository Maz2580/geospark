"""Small geodesic helpers shared by the agents."""

from __future__ import annotations

from pyproj import Geod

_GEOD = Geod(ellps="WGS84")


def overpass_bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Bounding box reaching ``radius_m`` metres from a point in every direction.

    Returns Overpass order ``(south, west, north, east)`` in degrees. Longitude spans are
    measured along the point's parallel, so the box doesn't shrink east-west away from
    the equator, which is what happens if you divide by a fixed 111,320 m per degree.
    """
    _, north, _ = _GEOD.fwd(lon, lat, 0, radius_m)
    _, south, _ = _GEOD.fwd(lon, lat, 180, radius_m)
    east, _, _ = _GEOD.fwd(lon, lat, 90, radius_m)
    west, _, _ = _GEOD.fwd(lon, lat, 270, radius_m)
    # Near the poles a small radius can wrap past the antimeridian; fall back to all longitudes.
    if not (west < lon < east):
        west, east = -180.0, 180.0
    return (max(south, -90.0), west, min(north, 90.0), east)
