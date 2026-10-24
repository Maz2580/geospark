"""Official coordinate and height transformations, with the method and its accuracy.

Frontier language models know the geodesy (they state the right formula for an ellipsoidal to
AHD height), but not the data it runs on: the national grids. Tested in October 2026, GPT-6.1
declined every height and grid-based conversion ("I cannot access the AUSGeoid2020 grid") and
Claude Opus 5.5 estimated them from memory, 0.2-5.3 m off. PROJ also falls back silently when a
grid is missing: AHD heights become ellipsoidal heights (4.7 m off in Melbourne) and British
National Grid coordinates move about 124 m.

This module uses PROJ's most accurate operation that covers the point, downloads the official
grid the first time it is needed (into ``$GEOSPARK_DATA_DIR/proj``), and refuses PROJ's
"ballpark" fallbacks. Every result says which operation and grid were used and how accurate
the operation is stated to be.

Configuration:
    GEOSPARK_PROJ_NETWORK   "false" to never download grids (results then need installed grids)
    PROJ_USER_WRITABLE_DIRECTORY  where grids are cached (default ``$GEOSPARK_DATA_DIR/proj``)
"""
from __future__ import annotations

import math
import os
import re
import warnings
from dataclasses import dataclass, field
from typing import Any

from geospark.utils import data_dir


class GeodesyError(ValueError):
    """The transformation can't be done to a stated accuracy (no grid, outside coverage, bad CRS)."""


# Height datums: (ellipsoidal 3D CRS of the matching horizontal datum, compound CRS, geoid model, region)
HEIGHT_DATUMS: dict[str, tuple[str, str, str, str]] = {
    "AHD": ("EPSG:7843", "EPSG:9463", "AUSGeoid2020", "Australia (GDA2020)"),
    "ODN": ("EPSG:4937", "EPSG:4258+5701", "OSGM15", "Great Britain (ETRS89)"),
    "NZVD2016": ("EPSG:4959", "EPSG:4167+7839", "NZGeoid2016", "New Zealand (NZGD2000)"),
    "NAVD88": ("EPSG:6319", "EPSG:6318+5703", "GEOID18", "Conterminous US (NAD83(2011))"),
    "EGM2008": ("EPSG:4979", "EPSG:4326+3855", "EGM2008", "Global (WGS 84); not a national datum"),
}
_ALIASES = {"AUSTRALIAN HEIGHT DATUM": "AHD", "ORDNANCE DATUM NEWLYN": "ODN", "NZVD": "NZVD2016",
            "NAVD": "NAVD88", "EGM08": "EGM2008", "ELLIPSOID": "ELLIPSOIDAL", "GNSS": "ELLIPSOIDAL"}


@dataclass
class Transformation:
    """A transformation that was done, and how."""

    coordinates: list[list[float]]
    source_crs: str
    target_crs: str
    method: str
    accuracy_m: float | None  # None: an exact conversion (a map projection on one datum)
    grids: list[str] = field(default_factory=list)
    area_of_use: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"provenance": [provenance(self.method, self.grids)], **self._values()}

    def _values(self) -> dict[str, Any]:
        return {
            "coordinates": self.coordinates, "source_crs": self.source_crs, "target_crs": self.target_crs,
            "method": self.method,
            "accuracy_m": self.accuracy_m,
            "accuracy_note": ("exact conversion (no change of datum)" if self.accuracy_m is None
                              else f"operation stated accurate to {self.accuracy_m} m"),
            "grids": self.grids, "area_of_use": self.area_of_use, "warnings": self.warnings,
        }


def provenance(method: str, grids: list[str]) -> dict[str, Any]:
    """Where a transformation came from: PROJ, the EPSG dataset version, the operation and grids."""
    import pyproj

    from geospark.protocol.provenance import source_provenance

    try:
        epsg = pyproj.database.get_database_metadata("EPSG.VERSION")
    except Exception:
        epsg = None
    version = f"PROJ {pyproj.proj_version_str}" + (f", EPSG {epsg}" if epsg else "")
    detail = method + (f" (grid: {', '.join(grids)})" if grids else "")
    return source_provenance("proj-epsg", method=detail, dataset_version=version).model_dump(mode="json", exclude_none=True)


def _configure_proj() -> None:
    """Cache grids under GeoSpark's data directory and allow PROJ to fetch them (once)."""
    os.environ.setdefault("PROJ_USER_WRITABLE_DIRECTORY", str(data_dir() / "proj"))
    os.makedirs(os.environ["PROJ_USER_WRITABLE_DIRECTORY"], exist_ok=True)
    import pyproj

    enabled = os.getenv("GEOSPARK_PROJ_NETWORK", "true").lower() not in ("0", "false", "no")
    pyproj.network.set_network_enabled(enabled)


def _crs(code: str) -> Any:
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    try:
        return CRS.from_user_input(code)
    except CRSError as e:
        raise GeodesyError(f"Unknown coordinate reference system '{code}': {e}") from None


def _grids(op: Any) -> list[str]:
    return sorted(set(re.findall(r"grids=@?([^\s]+)", op.definition or "")))


def _is_ballpark(op: Any) -> bool:
    return "ballpark" in (op.description or "").lower()


def transform(source_crs: str, target_crs: str, coordinates: list[list[float]],
              epoch: float | None = None) -> Transformation:
    """Transform points with the most accurate operation that covers all of them.

    Coordinates are in each CRS's x/y(/z) order with longitude first for geographic CRSs, eastings
    first for projected ones. ``epoch`` (decimal year) is for time-dependent frames such as ITRF2014.
    """
    from pyproj.transformer import TransformerGroup

    _configure_proj()
    if not coordinates:
        raise GeodesyError("Give at least one coordinate.")
    src, dst = _crs(source_crs), _crs(target_crs)
    with warnings.catch_warnings():  # a missing grid is reported below, in words, not as a library warning
        warnings.simplefilter("ignore", UserWarning)
        group = TransformerGroup(src, dst, always_xy=True)
    candidates = [op for op in group.transformers if not _is_ballpark(op)]
    if not candidates:
        missing = sorted({g.short_name for u in group.unavailable_operations for g in u.grids})
        raise GeodesyError(
            f"No accurate transformation from {src.name} to {dst.name} is available"
            + (f": it needs the grid(s) {', '.join(missing)}, which could not be downloaded." if missing else ".")
            + " GeoSpark won't use PROJ's ballpark approximation.")

    def run(op: Any) -> list[list[float]] | None:
        out = []
        for pt in coordinates:
            args = list(pt) + ([0.0] if len(pt) == 2 and epoch is not None else [])
            res = op.transform(*args, epoch) if epoch is not None else op.transform(*args)
            vals = [float(v) for v in res][: len(pt)]
            if not all(math.isfinite(v) for v in vals):
                return None
            out.append(vals)
        return out

    def key(op: Any) -> float:  # unknown accuracy (an exact conversion) sorts first
        return -1.0 if op.accuracy is None or op.accuracy < 0 else float(op.accuracy)

    for op in sorted(candidates, key=key):
        if op.accuracy is not None and op.accuracy < 0 and _changes_datum(src, dst):
            continue  # a datum change with no stated accuracy is not trustworthy
        out = run(op)
        if out is None:
            continue  # this operation's grid doesn't cover the points
        notes = []
        better = [u for u in group.unavailable_operations if u.accuracy and 0 < u.accuracy < key(op)]
        if better:
            names = sorted({g.short_name for u in better for g in u.grids})
            notes.append(f"A more accurate operation needs grid(s) {', '.join(names)}, which are not available here.")
        return Transformation(
            coordinates=[[round(v, 9) for v in p] for p in out], source_crs=src.name, target_crs=dst.name,
            method=op.description, accuracy_m=None if key(op) < 0 else key(op), grids=_grids(op),
            area_of_use=op.area_of_use.name if op.area_of_use else None, warnings=notes,
        )
    raise GeodesyError(f"The points are outside the area where {src.name} to {dst.name} can be transformed "
                       "accurately (or the grid needed there is unavailable).")


def _changes_datum(src: Any, dst: Any) -> bool:
    a, b = src.geodetic_crs, dst.geodetic_crs
    return not (a and b and a.datum == b.datum)


def _datum(name: str) -> str:
    key = re.sub(r"\s+", " ", name.strip().upper())
    key = _ALIASES.get(key, key)
    if key != "ELLIPSOIDAL" and key not in HEIGHT_DATUMS:
        raise GeodesyError(f"Unknown height reference '{name}'. Use 'ellipsoidal' or one of: {', '.join(HEIGHT_DATUMS)}.")
    return key


def convert_height(latitude: float, longitude: float, height: float, from_datum: str, to_datum: str) -> dict[str, Any]:
    """Convert a height between the ellipsoid (what GNSS measures) and a national height datum.

    The latitude and longitude are in the datum's own horizontal frame (GDA2020 for AHD, ETRS89 for
    ODN, NZGD2000 for NZVD2016, NAD83(2011) for NAVD88, WGS 84 for EGM2008); at the decimetre level
    and below the frames differ by less than a metre horizontally, which changes a geoid height by
    millimetres.
    """
    a, b = _datum(from_datum), _datum(to_datum)
    if a == b:
        raise GeodesyError("The two height references are the same.")
    if "ELLIPSOIDAL" not in (a, b):
        raise GeodesyError("Convert through the ellipsoid: one side must be 'ellipsoidal' (e.g. AHD -> ellipsoidal).")
    national = b if a == "ELLIPSOIDAL" else a
    ellipsoidal, compound, model, region = HEIGHT_DATUMS[national]
    src, dst = (ellipsoidal, compound) if a == "ELLIPSOIDAL" else (compound, ellipsoidal)
    try:
        result = transform(src, dst, [[longitude, latitude, height]])
    except GeodesyError as e:
        if "outside" in str(e):
            raise GeodesyError(f"{national} is the height datum of {region}; latitude {latitude}, longitude "
                               f"{longitude} is outside its {model} model.") from None
        raise
    converted = result.coordinates[0][2]
    separation = (height - converted) if a == "ELLIPSOIDAL" else (converted - height)
    return {
        "height_m": round(converted, 4), "from": a.lower() if a == "ELLIPSOIDAL" else a,
        "to": b.lower() if b == "ELLIPSOIDAL" else b, "geoid_model": model, "region": region,
        "separation_m": round(separation, 4),
        "method": result.method, "accuracy_m": result.accuracy_m, "grids": result.grids,
        "provenance": [provenance(result.method, result.grids)],
        "warnings": result.warnings + ([] if national != "EGM2008" else [
            "EGM2008 is a global model, not a national height datum; it can differ from the local datum by decimetres."]),
    }
