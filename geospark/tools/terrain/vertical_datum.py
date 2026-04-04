"""
Vertical Datum Awareness for Elevation Data.

Provides datum inference, metadata wrapping, and warnings for elevation
values from common sources. Addresses the fundamental challenge that
elevation sources often omit or blur vertical datum assumptions.

Key insight: In Colorado, the difference between NAVD88 (orthometric)
and WGS84 (ellipsoidal) heights can be ~17-18 meters. For coastal areas,
the difference between MSL and ellipsoidal can exceed 30 meters. Mixing
datums without awareness produces garbage-in-garbage-out results.

Supported datum inference:
    - SRTM → EGM96 geoid (orthometric approximation)
    - Copernicus DEM → EGM2008 geoid
    - 3DEP/USGS → NAVD88 (North America)
    - ASTER GDEM → EGM96 geoid
    - Open Elevation API → SRTM (EGM96)
    - LiDAR (generic) → typically NAVD88 but varies
    - Unknown → explicitly flagged as unknown

Usage:
    from geospark.tools.terrain.vertical_datum import DatumInfo, infer_datum

    info = infer_datum("open-elevation-api")
    print(info.datum)          # "EGM96"
    print(info.datum_type)     # "geoid"
    print(info.warning)        # None (known source)

    info = infer_datum("my-custom-dem")
    print(info.datum)          # "unknown"
    print(info.confidence)     # "none"
    print(info.warning)        # "Vertical datum could not be determined..."
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DatumInfo(BaseModel):
    """Vertical datum metadata for an elevation value."""

    datum: str = "unknown"
    datum_type: str = "unknown"  # "geoid", "ellipsoidal", "tidal", "unknown"
    ellipsoid: str = "WGS84"
    geoid_model: str | None = None  # e.g. "EGM96", "EGM2008"
    source: str = "unknown"
    confidence: str = "none"  # "high", "medium", "low", "none"
    height_type: str = "unknown"  # "orthometric", "ellipsoidal", "unknown"
    approximate_geoid_separation_m: float | None = None
    warning: str | None = None
    note: str = ""


# Known elevation source → datum mapping
# Each entry documents the vertical reference system and confidence
_SOURCE_DATUMS: dict[str, dict[str, Any]] = {
    # Public APIs
    "open-elevation-api": {
        "datum": "EGM96",
        "datum_type": "geoid",
        "geoid_model": "EGM96",
        "height_type": "orthometric",
        "confidence": "medium",
        "note": (
            "Open Elevation API uses SRTM data. SRTM heights are referenced to "
            "the EGM96 geoid, providing approximate orthometric heights. "
            "Accuracy: ~16m vertical RMSE globally."
        ),
    },
    # Satellite DEMs
    "srtm": {
        "datum": "EGM96",
        "datum_type": "geoid",
        "geoid_model": "EGM96",
        "height_type": "orthometric",
        "confidence": "high",
        "note": (
            "SRTM (Shuttle Radar Topography Mission) heights are referenced to "
            "the EGM96 geoid. Resolution: 30m (1 arc-second) or 90m (3 arc-second). "
            "Vertical accuracy: ~6m absolute, ~10m relative (90% confidence)."
        ),
    },
    "copernicus-dem": {
        "datum": "EGM2008",
        "datum_type": "geoid",
        "geoid_model": "EGM2008",
        "height_type": "orthometric",
        "confidence": "high",
        "note": (
            "Copernicus DEM (GLO-30/GLO-90) heights are referenced to the EGM2008 "
            "geoid. Derived from TanDEM-X. Resolution: 30m or 90m. "
            "Vertical accuracy: <4m absolute (90% confidence)."
        ),
    },
    "aster-gdem": {
        "datum": "EGM96",
        "datum_type": "geoid",
        "geoid_model": "EGM96",
        "height_type": "orthometric",
        "confidence": "high",
        "note": (
            "ASTER GDEM v3 heights are referenced to the EGM96 geoid. "
            "Resolution: 30m. Vertical accuracy: ~17m at 95% confidence."
        ),
    },
    # National DEMs
    "3dep": {
        "datum": "NAVD88",
        "datum_type": "tidal",
        "geoid_model": "GEOID18",
        "height_type": "orthometric",
        "confidence": "high",
        "note": (
            "USGS 3DEP (3D Elevation Program) uses NAVD88 vertical datum with "
            "GEOID18 model. NAVD88-to-WGS84 separation varies: ~-8m (Florida) "
            "to ~-36m (Alaska). In Colorado: ~-17m. Resolution: 1m to 10m."
        ),
    },
    "lidar": {
        "datum": "varies",
        "datum_type": "varies",
        "height_type": "varies",
        "confidence": "low",
        "note": (
            "LiDAR elevation datum depends on the survey specification. "
            "US surveys typically use NAVD88. International surveys vary. "
            "Check the dataset metadata for the specific vertical datum."
        ),
        "warning": (
            "LiDAR vertical datum varies by survey. Verify the datum from "
            "the dataset metadata before mixing with other elevation sources."
        ),
    },
    # Ellipsoidal
    "gps": {
        "datum": "WGS84",
        "datum_type": "ellipsoidal",
        "height_type": "ellipsoidal",
        "confidence": "high",
        "note": (
            "Raw GPS heights are ellipsoidal (WGS84). To convert to orthometric "
            "height, subtract the geoid separation (N): h_ortho = h_ellip - N. "
            "Geoid separation varies from -106m to +85m globally."
        ),
    },
}


def infer_datum(
    source: str,
    auxiliary_metadata: dict[str, Any] | None = None,
) -> DatumInfo:
    """Infer vertical datum from elevation source name and optional metadata.

    Args:
        source: Elevation data source identifier (e.g., "open-elevation-api",
            "srtm", "3dep", "copernicus-dem").
        auxiliary_metadata: Optional metadata dict that may contain datum hints
            (e.g., ``{"vertical_crs": "EPSG:5703"}``, ``{"datum": "NAVD88"}``).

    Returns:
        DatumInfo with inferred datum, confidence, and any warnings.
    """
    # Normalize source name
    source_key = source.lower().strip().replace(" ", "-").replace("_", "-")

    # Check auxiliary metadata first
    if auxiliary_metadata:
        explicit = _check_auxiliary_metadata(auxiliary_metadata)
        if explicit:
            explicit.source = source
            return explicit

    # Look up known source
    known = _SOURCE_DATUMS.get(source_key)
    if known:
        return DatumInfo(source=source, **known)

    # Try partial matching
    for key, info in _SOURCE_DATUMS.items():
        if key in source_key or source_key in key:
            return DatumInfo(source=source, **info)

    # Unknown source
    return DatumInfo(
        source=source,
        datum="unknown",
        confidence="none",
        warning=(
            f"Vertical datum could not be determined for source '{source}'. "
            "Elevation values may be orthometric (geoid-referenced) or "
            "ellipsoidal (WGS84). The difference can be tens of meters "
            "depending on location. Do not mix elevation values from "
            "different sources without verifying their vertical datums."
        ),
    )


def _check_auxiliary_metadata(meta: dict[str, Any]) -> DatumInfo | None:
    """Extract datum info from auxiliary metadata if present."""
    # Check for explicit vertical CRS
    vcrs = meta.get("vertical_crs", meta.get("vertical_datum", meta.get("datum")))
    if vcrs is None:
        return None

    vcrs_str = str(vcrs).upper()

    # Map common vertical CRS identifiers
    vcrs_map: dict[str, dict[str, str]] = {
        "NAVD88": {"datum": "NAVD88", "datum_type": "tidal", "height_type": "orthometric"},
        "EPSG:5703": {"datum": "NAVD88", "datum_type": "tidal", "height_type": "orthometric"},
        "EGM96": {"datum": "EGM96", "datum_type": "geoid", "height_type": "orthometric"},
        "EGM2008": {"datum": "EGM2008", "datum_type": "geoid", "height_type": "orthometric"},
        "WGS84": {"datum": "WGS84", "datum_type": "ellipsoidal", "height_type": "ellipsoidal"},
        "EPSG:4979": {"datum": "WGS84", "datum_type": "ellipsoidal", "height_type": "ellipsoidal"},
        "AHD": {"datum": "AHD71", "datum_type": "tidal", "height_type": "orthometric"},
        "EPSG:5711": {"datum": "AHD71", "datum_type": "tidal", "height_type": "orthometric"},
        "MSL": {"datum": "MSL", "datum_type": "tidal", "height_type": "orthometric"},
    }

    for key, info in vcrs_map.items():
        if key in vcrs_str:
            return DatumInfo(
                confidence="high",
                note=f"Vertical datum explicitly specified as {key} in metadata.",
                **info,
            )

    return None


def format_elevation_warning(
    source_a: str,
    source_b: str,
    location_description: str = "",
) -> str:
    """Generate a warning when comparing elevations from different sources.

    Args:
        source_a: First elevation source.
        source_b: Second elevation source.
        location_description: Optional location context for the warning.

    Returns:
        Warning string, or empty string if sources are compatible.
    """
    datum_a = infer_datum(source_a)
    datum_b = infer_datum(source_b)

    if datum_a.datum == datum_b.datum and datum_a.datum != "unknown":
        return ""  # Same datum, safe to compare

    location = f" at {location_description}" if location_description else ""
    return (
        f"WARNING: Comparing elevations from '{source_a}' ({datum_a.datum}) and "
        f"'{source_b}' ({datum_b.datum}){location}. These use different vertical "
        f"datums. The difference can be tens of meters depending on location. "
        f"Convert to a common datum before comparing."
    )
