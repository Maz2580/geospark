"""Provenance, units and quality: what every GeoSpark answer says about itself.

An answer a GIS analyst can trust says *where it came from* (source, licence, attribution,
when it was retrieved), *how it was computed* (the method), *what its numbers mean* (units)
and *how good it is* (quality flags and warnings). Tools tag their results with a source id;
``enrich`` turns those ids into full provenance records, infers units from property names and
adds quality information, in one place for every tool and operation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from geospark.protocol.schema import SpatialResult


class Provenance(BaseModel):
    """Where one part of an answer came from, and on what terms it can be reused."""

    source: str = Field(..., description="Stable source id, e.g. 'openstreetmap-nominatim'")
    name: str = Field(..., description="Human-readable source name")
    url: str | None = None
    licence: str | None = Field(None, description="Licence of the data, e.g. 'ODbL-1.0'")
    attribution: str | None = Field(None, description="Attribution text to show when publishing")
    retrieved_at: datetime | None = Field(
        None, description="When the data was fetched (UTC); None if computed"
    )
    method: str | None = Field(None, description="How the value was computed or obtained")
    dataset_version: str | None = None


_OSM = "© OpenStreetMap contributors"

SOURCES: dict[str, dict[str, Any]] = {
    "openstreetmap-nominatim": {
        "name": "OpenStreetMap Nominatim",
        "url": "https://nominatim.openstreetmap.org",
        "licence": "ODbL-1.0",
        "attribution": _OSM,
        "method": "Nominatim geocoding of OpenStreetMap data",
    },
    "openstreetmap-overpass": {
        "name": "OpenStreetMap Overpass API",
        "url": "https://overpass-api.de",
        "licence": "ODbL-1.0",
        "attribution": _OSM,
        "method": "Overpass query of OpenStreetMap features",
    },
    "copernicus-dem": {
        "name": "Copernicus DEM GLO-30",
        "url": "https://registry.opendata.aws/copernicus-dem/",
        "licence": "Copernicus DEM licence (free, with attribution)",
        "attribution": "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and "
        "Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved",
        "method": "Height read from the 30 m GLO-30 cloud-optimised GeoTIFF tile",
        "dataset_version": "GLO-30 (COG, AWS open data)",
    },
    "open-elevation-api": {
        "name": "Open Elevation",
        "url": "https://open-elevation.com",
        "licence": "Public domain (SRTM)",
        "attribution": "Open Elevation, SRTM data (NASA/USGS)",
        "method": "Open Elevation lookup (SRTM-derived)",
    },
    "osrm-public-demo": {
        "name": "OSRM public demo server",
        "url": "https://router.project-osrm.org",
        "licence": "ODbL-1.0 (road data)",
        "attribution": f"Routing by OSRM, map data {_OSM}",
        "method": "OSRM shortest-time route on the OpenStreetMap road network",
    },
    "element84-earth-search": {
        "name": "Element 84 Earth Search (STAC)",
        "url": "https://earth-search.aws.element84.com/v1",
        "licence": "Per collection (Sentinel-2: Copernicus Sentinel data, free and open)",
        "attribution": "Contains modified Copernicus Sentinel data",
        "method": "STAC item search",
    },
    "sentinel-2-l2a": {
        "name": "Sentinel-2 Level-2A",
        "url": "https://sentinels.copernicus.eu",
        "licence": "Copernicus Sentinel data terms (free and open)",
        "attribution": "Contains modified Copernicus Sentinel data",
    },
    "open-meteo": {
        "name": "Open-Meteo",
        "url": "https://open-meteo.com",
        "licence": "CC-BY-4.0",
        "attribution": "Weather data by Open-Meteo.com",
        "method": "Open-Meteo forecast API (model blend)",
    },
    "openaq": {
        "name": "OpenAQ",
        "url": "https://openaq.org",
        "licence": "Per station (see each station's licenses)",
        "attribution": "Air quality data via OpenAQ",
        "method": "OpenAQ v3 latest measurements of nearby stations",
    },
    "nasa-firms": {
        "name": "NASA FIRMS",
        "url": "https://firms.modaps.eosdis.nasa.gov",
        "licence": "NASA open data (no restrictions; attribution requested)",
        "attribution": "NASA LANCE FIRMS (MODIS/VIIRS active fire detections)",
        "method": "FIRMS area API, near-real-time detections",
    },
    "valhalla": {
        "name": "Valhalla", "url": "https://valhalla1.openstreetmap.de",
        "licence": "ODbL-1.0 (road network data)",
        "attribution": "Routing by Valhalla; map data © OpenStreetMap contributors",
        "method": "Valhalla routing over the OpenStreetMap network",
    },
    "overture-maps": {
        "name": "Overture Maps", "url": "https://overturemaps.org",
        "licence": "Per theme: CDLA-Permissive-2.0 (places), ODbL-1.0 (buildings, transportation, divisions)",
        "attribution": "© Overture Maps Foundation, overturemaps.org; includes data from OpenStreetMap "
                       "contributors (ODbL) and other sources. See https://docs.overturemaps.org/attribution/",
        "method": "DuckDB spatial query of Overture GeoParquet",
    },
    "geospark-engine": {
        "name": "GeoSpark spatial engine",
        "url": "https://github.com/Maz2580/geospark",
        "licence": "Apache-2.0",
        "attribution": None,
    },
}

# How each engine operation is computed: the 'method' of a computed answer
ENGINE_METHODS: dict[str, str] = {
    "distance": "Geodesic distance on the WGS84 ellipsoid (pyproj.Geod.inv, Karney's algorithm); "
    "for lines and polygons, between the nearest points found in lon/lat",
    "area": "Geodesic area and perimeter on the WGS84 ellipsoid (pyproj.Geod.geometry_area_perimeter)",
    "length": "Geodesic length on the WGS84 ellipsoid (pyproj.Geod.geometry_length)",
    "buffer": "Shape-preserving buffer in a local azimuthal equidistant projection (PROJ + GEOS); "
    "area is geodesic",
    "topology": "Planar predicate on lon/lat coordinates (Shapely/GEOS); edges are straight in lon/lat",
    "overlay": "Planar overlay on lon/lat coordinates (Shapely/GEOS)",
    "centroid": "Planar centroid of the lon/lat coordinates (Shapely/GEOS)",
    "convex_hull": "Planar convex hull of the lon/lat coordinates (Shapely/GEOS)",
}
_OPERATION_METHOD = {
    "distance": "distance",
    "area": "area",
    "length": "length",
    "buffer": "buffer",
    "contains": "topology",
    "intersects": "topology",
    "within": "topology",
    "touches": "topology",
    "crosses": "topology",
    "overlaps": "topology",
    "disjoint": "topology",
    "union": "overlay",
    "intersection": "overlay",
    "difference": "overlay",
    "centroid": "centroid",
    "convex_hull": "convex_hull",
}

# Vertical accuracy (90% linear error) of each elevation dataset, in metres
VERTICAL_ACCURACY_LE90_M = {"copernicus-dem": 4.0, "open-elevation-api": 16.0}

# Property-name suffix -> unit (longest suffix first)
_UNIT_SUFFIXES = [
    ("_sq_km", "square kilometre"),
    ("_sq_m", "square metre"),
    ("_kmh", "kilometre per hour"),
    ("_km", "kilometre"),
    ("_mm", "millimetre"),
    ("_m", "metre"),
    ("_pct", "percent"),
    ("_deg", "degree"),
    ("_c", "degree Celsius"),
    ("_s", "second"),
    ("_ms", "millisecond"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def source_provenance(source: str, **overrides: Any) -> Provenance:
    """Provenance for a catalogued source (unknown ids get a minimal record)."""
    info = dict(SOURCES.get(source, {"name": source}))
    info.update({k: v for k, v in overrides.items() if v is not None})
    if source != "geospark-engine":
        info.setdefault("retrieved_at", _now())
    return Provenance(source=source, **info)


def engine_provenance(operation: str) -> Provenance:
    """Provenance for an answer computed by the engine itself."""
    import pyproj
    import shapely

    from geospark import __version__

    method = ENGINE_METHODS.get(
        _OPERATION_METHOD.get(operation, ""), f"GeoSpark '{operation}' operation"
    )
    return source_provenance(
        "geospark-engine",
        method=method,
        dataset_version=f"geospark {__version__}; pyproj {pyproj.__version__} "
        f"(PROJ {pyproj.proj_version_str}); shapely {shapely.__version__} "
        f"(GEOS {shapely.geos_version_string})",
    )


def infer_units(properties: dict[str, Any]) -> dict[str, str]:
    """Units for numeric properties, read from their names ('distance_m' -> 'metre')."""
    units: dict[str, str] = {}
    for key, value in properties.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        for suffix, unit in _UNIT_SUFFIXES:
            if key.endswith(suffix):
                units[key] = unit
                break
    return units


def _extent_deg(geometry: dict[str, Any] | None) -> float:
    if not geometry:
        return 0.0
    try:
        from shapely.geometry import shape

        minx, miny, maxx, maxy = shape(geometry).bounds
        return float(max(maxx - minx, maxy - miny))
    except Exception:
        return 0.0


def _km_apart(a: Any, b: Any) -> float:
    """Geodesic distance in km between two features' representative points."""
    try:
        from pyproj import Geod
        from shapely.geometry import shape

        pa = shape(a.geometry).representative_point()
        pb = shape(b.geometry).representative_point()
        return float(Geod(ellps="WGS84").inv(pa.x, pa.y, pb.x, pb.y)[2]) / 1000
    except Exception:
        return 0.0


def enrich(
    result: SpatialResult, operation: str | None = None, inputs: list[dict[str, Any]] | None = None
) -> SpatialResult:
    """Add provenance, units, quality and warnings to a SpatialResult (in place; returned)."""
    seen = {p.source for p in result.provenance}
    for source in result.sources:
        if source in SOURCES and source not in seen and source != "geospark-engine":
            result.provenance.append(source_provenance(source))
            seen.add(source)
    if operation in _OPERATION_METHOD and "geospark-engine" not in seen:
        result.provenance.append(engine_provenance(operation))

    for feature in result.features:
        result.spatial_context.units.update(infer_units(feature.properties))

    # --- quality flags and warnings, by kind of answer ---
    if operation in ("geocode",) and result.features:
        importances = [float(f.properties.get("importance") or 0) for f in result.features]
        result.quality["match_importance"] = round(importances[0], 3)
        result.quality["candidates"] = len(result.features)
        rivals = [
            f for f, importance in zip(result.features[1:], importances[1:], strict=True)
            if importances[0] - importance < 0.05 and _km_apart(result.features[0], f) > 25
        ]
        if rivals:
            names = [result.features[0].properties.get("display_name", "?")]
            names += [f.properties.get("display_name", "?") for f in rivals[:2]]
            result.quality["ambiguous"] = True
            result.warnings.append(
                "Ambiguous place name: " + "; ".join(f"'{n}'" for n in names)
                + (" and others" if len(rivals) > 2 else "")
                + " are almost equally likely and far apart. Add a region or country to be sure."
            )

    if operation == "elevation" and result.features:
        dem = next((s for s in result.sources if s in VERTICAL_ACCURACY_LE90_M), None)
        if dem:
            result.quality["vertical_accuracy_le90_m"] = VERTICAL_ACCURACY_LE90_M[dem]
        datum = result.features[0].properties.get("vertical_datum")
        if datum:
            result.quality["vertical_datum"] = datum

    if operation == "satellite_view" and result.features:
        covers = [
            float(c) for f in result.features
            if isinstance(c := f.properties.get("cloud_cover"), (int, float))
        ]
        if covers:
            result.quality["cloud_cover_pct"] = {"min": min(covers), "max": max(covers)}
            if min(covers) > 50:
                result.warnings.append(
                    f"Every scene found is more than 50% cloud-covered (least cloudy: {min(covers):.0f}%). "
                    "Widen the date range or filter on cloud cover before analysing the imagery."
                )

    planar = _OPERATION_METHOD.get(operation or "") in (
        "topology",
        "overlay",
        "centroid",
        "convex_hull",
    )
    if planar and max((_extent_deg(g) for g in inputs or []), default=0.0) > 5:
        result.warnings.append(
            "Large geometry (over 5° across): this predicate is computed on lon/lat coordinates, "
            "where edges are straight lines, not geodesics. Results near long edges may differ "
            "from a geodesic interpretation."
        )
    return result
