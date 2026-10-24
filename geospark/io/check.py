"""Check a dataset's coordinate reference before using it, and diagnose why two layers disagree.

The errors that hurt most in spatial data are silent: a layer that is GDA94 but labelled GDA2020 sits
about 1.5 m from where it should, a layer in the wrong MGA zone lands in another state, heights mix
the ellipsoid (GNSS) with AHD. Nothing fails; the numbers are just wrong. This module looks for the
evidence in the coordinates themselves and says what it found, how sure it is, and what it can't tell.

    check_layer(path)                 one file: CRS declared? numbers consistent with it? height reference?
    compare_layers(path_a, path_b)    two files: the systematic offset between them, and its likely cause

Point clouds (LAS, LAZ, COPC) and rasters (GeoTIFF, COG), local or by URL, are read with terrio
(``geospark.io.surface``, optional). Compared with survey marks, a surface's heights are looked up at
each mark, so LiDAR delivered in ellipsoidal heights, or in feet, is named.

Every finding has a ``code``, a ``severity`` ("problem", "caveat" or "info"), a plain message and the
numbers behind it. A cause is only named when the measured offset matches it (for example the official
GDA94 to GDA2020 shift at that place, within 0.25 m); otherwise the offset is reported unexplained.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pyproj import CRS, Geod, Transformer

from geospark.io import layers, surface

_GEOD = Geod(ellps="GRS80")
_AUSTRALIA = (112.0, -44.5, 154.5, -9.0)  # lon/lat box of mainland Australia and Tasmania
_HEIGHT_FIELD = re.compile(r"(^|_)(h|z|height|hgt|elev|elevation|alt|altitude|rl|ahd|ellipsoidal?_?h(eight)?)($|_)", re.I)
_MAX_PAIR_M = 2000.0
_FOOT = 0.3048
_US_SURVEY_FOOT = 1200 / 3937


@dataclass
class Finding:
    code: str
    severity: str  # "problem", "caveat" or "info"
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Raw:
    name: str
    xy: list[tuple[float, float]]  # one representative coordinate per feature, in the file's own CRS
    z: list[float | None]
    props: list[dict[str, Any]]
    crs: CRS  # the declared CRS, or the one assumed (a CSV's WGS 84) or given
    crs_declared: bool
    warnings: list[str]
    surface: surface.Surface | None = None  # a point cloud or raster


# --- reading -----------------------------------------------------------------------------------


def _representative(geom: Any) -> tuple[tuple[float, float], float | None] | None:
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Point":
        return (geom.x, geom.y), (geom.z if geom.has_z else None)
    p = geom.representative_point() if geom.geom_type not in ("LineString", "MultiLineString") else geom.interpolate(0.5, normalized=True)
    return (p.x, p.y), None


def _read_surface(path: str | Path, crs: str | None) -> tuple[_Raw | None, list[Finding]]:
    try:
        s = surface.open_surface(path, crs)
    except surface.SurfaceError as e:
        return None, [Finding("unreadable", "problem", str(e))]
    if s.crs is None:
        what = "point cloud" if s.kind == "pointcloud" else "raster"
        return None, [Finding("crs_missing", "problem",
                              f"The {what} {s.name} doesn't say which coordinate reference system it is in; pass crs= "
                              "(e.g. EPSG:7855, or EPSG:7855+5711 with AHD heights).")]
    return _Raw(s.name, s.xy, list(s.z_m), [{} for _ in s.xy], s.crs, s.crs_declared, list(s.warnings), s), []


def _read_raw(path: str | Path, layer: str | None, crs: str | None) -> tuple[_Raw | None, list[Finding]]:
    if surface.kind(path):
        return _read_surface(path, crs)
    p = Path(path).expanduser()
    findings: list[Finding] = []
    suffix = p.suffix.lower()
    try:
        if suffix in (".parquet", ".geoparquet"):
            geoms, props, source, warns = layers._read_geoparquet(p, crs)
            declared = crs is None
        elif suffix in (".csv", ".tsv"):
            geoms, props, source, warns = layers._read_csv(p, crs)
            declared = crs is not None
        else:
            geoms, props, source, warns = layers._read_gdal(p, layer, crs)
            declared = crs is None
    except layers.LayerError as e:
        if "doesn't say which coordinate reference system" in str(e) or "x/y columns" in str(e):
            findings.append(Finding("crs_missing", "problem", str(e)))
        else:
            findings.append(Finding("unreadable", "problem", str(e)))
        return None, findings
    pts, zs, kept = [], [], []
    for g, pr in zip(geoms, props, strict=True):
        rep = _representative(g)
        if rep is None:
            continue
        pts.append(rep[0])
        zs.append(rep[1])
        kept.append(pr)
    return _Raw(p.name, pts, zs, kept, source, declared, list(warns)), findings


def _to_lonlat(crs: CRS, xy: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if crs.is_geographic:
        to = Transformer.from_crs(crs, crs.geodetic_crs or crs, always_xy=True)
    else:
        to = Transformer.from_crs(crs, crs.geodetic_crs or CRS.from_epsg(4326), always_xy=True)
    out = []
    for x, y in xy:
        lon, lat = to.transform(x, y)
        if math.isfinite(lon) and math.isfinite(lat):
            out.append((lon, lat))
    return out


def _centre(lonlats: list[tuple[float, float]]) -> tuple[float, float]:
    return statistics.median(p[0] for p in lonlats), statistics.median(p[1] for p in lonlats)


def _datum_name(crs: CRS) -> str:
    g = crs.geodetic_crs
    return (g.datum.name if g is not None and g.datum is not None else crs.name) or "unknown"


def _in_box(lonlats: list[tuple[float, float]], box: tuple[float, float, float, float]) -> float:
    if not lonlats:
        return 0.0
    w, s, e, n = box
    return sum(1 for lon, lat in lonlats if w <= lon <= e and s <= lat <= n) / len(lonlats)


# --- one file ----------------------------------------------------------------------------------


def check_layer(path: str | Path, layer: str | None = None, crs: str | None = None) -> dict[str, Any]:
    """What a file says about its coordinates, and whether its numbers agree with that."""
    raw, findings = _read_raw(path, layer, crs)
    report: dict[str, Any] = {"file": raw.name if raw else Path(str(path)).name, "findings": findings}
    if raw is None:
        return _finish(report)
    report.update(features=len(raw.xy), crs=raw.crs.name, crs_declared=raw.crs_declared, datum=_datum_name(raw.crs))
    if raw.surface:
        s = raw.surface
        report.update(kind=s.kind, features=s.count, sampled=len(s.xy),
                      vertical_crs=s.vertical.name if s.vertical is not None else None)
    if not raw.xy:
        findings.append(Finding("empty", "problem", "The file has no geometries."))
        return _finish(report)

    xs, ys = [p[0] for p in raw.xy], [p[1] for p in raw.xy]
    report["extent_in_file_units"] = [min(xs), min(ys), max(xs), max(ys)]
    if not raw.crs_declared and Path(path).suffix.lower() in (".csv", ".tsv"):
        findings.append(Finding("crs_assumed", "caveat",
                                "A CSV can't declare a CRS: its longitude/latitude columns were read as WGS 84. If the "
                                "data came from an Australian agency it is probably GDA94 or GDA2020; pass crs= to say so."))
    if raw.crs.is_geographic:
        if all(abs(x) > 180 or abs(y) > 90 for x, y in raw.xy) and statistics.median(abs(x) for x in xs) > 1000:
            findings.append(Finding("projected_values_in_geographic_crs", "problem",
                                    f"The file says {raw.crs.name} (degrees), but its coordinates are in the thousands: they "
                                    "are probably projected metres (e.g. an MGA or UTM zone).",
                                    {"median_x": statistics.median(xs), "median_y": statistics.median(ys)}))
            return _finish(report)
        swapped = [1 for x, y in raw.xy if abs(x) <= 90 < abs(y) <= 180]
        if len(swapped) > 0.9 * len(raw.xy):
            findings.append(Finding("lat_lon_swapped", "problem",
                                    "The values look like [latitude, longitude], not [longitude, latitude].",
                                    {"share": round(len(swapped) / len(raw.xy), 3)}))
            return _finish(report)
    elif all(abs(x) <= 180 and abs(y) <= 90 for x, y in raw.xy):
        findings.append(Finding("degree_values_in_projected_crs", "problem",
                                f"The file says {raw.crs.name} (metres), but every coordinate is within ±180/±90: they "
                                "are probably longitude/latitude in degrees.",
                                {"median_x": statistics.median(xs), "median_y": statistics.median(ys)}))
        return _finish(report)

    lonlats = _to_lonlat(raw.crs, raw.xy)
    report["extent_lonlat"] = [min(p[0] for p in lonlats), min(p[1] for p in lonlats),
                               max(p[0] for p in lonlats), max(p[1] for p in lonlats)] if lonlats else None
    # A compound CRS (horizontal + vertical) has no area of use of its own: use the horizontal part's
    horizontal = next((c for c in raw.crs.sub_crs_list if not c.is_vertical), raw.crs) if raw.crs.is_compound else raw.crs
    area = horizontal.area_of_use
    if area and lonlats:
        margin = 0.5
        outside = [1 for lon, lat in lonlats
                   if not (area.west - margin <= lon <= area.east + margin and area.south - margin <= lat <= area.north + margin)]
        if outside:
            findings.append(Finding("outside_area_of_use", "problem" if len(outside) > 0.5 * len(lonlats) else "caveat",
                                    f"{len(outside)} of {len(lonlats)} features are outside where {raw.crs.name} applies "
                                    f"({area.name}). The CRS label may be wrong (for example the wrong MGA zone).",
                                    {"outside": len(outside), "of": len(lonlats)}))

    datum = _datum_name(raw.crs)
    in_aus = _in_box(lonlats, _AUSTRALIA)
    if in_aus > 0.5 and re.search(r"WGS ?84|World Geodetic", datum, re.I):
        findings.append(Finding("australian_data_in_wgs84", "caveat",
                                "The data is in Australia but labelled WGS 84. GDA2020 and WGS 84 differ by a few "
                                "decimetres and GDA94 by about 1.5-1.8 m, and many tools treat them as the same. If it "
                                "came from an Australian source, check which datum it really is before combining layers."))
    elif in_aus > 0.5 and "1994" in datum:
        findings.append(Finding("gda94", "info",
                                "The data is in GDA94, which GDA2020 superseded. GeoSpark converts it with the official "
                                "transformation; tools that treat the two as the same put it about 1.5-1.8 m off."))

    if raw.surface:
        _surface_height_findings(raw.surface, findings)
    else:
        _height_findings(raw, findings)
    report["warnings"] = raw.warnings
    return _finish(report)


def _height_fields(raw: _Raw) -> list[str]:
    names = list(raw.props[0].keys()) if raw.props else []
    return [n for n in names if _HEIGHT_FIELD.search(n)]


def _height_findings(raw: _Raw, findings: list[Finding]) -> None:
    fields = _height_fields(raw)
    has_z = any(z is not None for z in raw.z)
    vertical = bool(raw.crs and raw.crs.is_compound)
    if not fields and not has_z:
        return
    named = []
    for name in fields:
        low = name.lower()
        ref = "AHD" if ("ahd" in low or low in ("rl",) or low.endswith("_rl")) else \
              "ellipsoidal" if ("ellip" in low or "gnss" in low) else None
        named.append((name, ref))
    unstated = [f"field '{n}'" for n, ref in named if ref is None] + (["the geometry Z values"] if has_z and not vertical else [])
    if unstated:
        findings.append(Finding("height_reference_unstated", "caveat",
                                f"The heights ({', '.join(unstated)}) don't say whether they are ellipsoidal (GNSS) or above a "
                                "height datum such as AHD. In Melbourne the two differ by about 4.7 m; in Perth by 32 m.",
                                {"fields": unstated}))
    stated = [f"{n} ({ref})" for n, ref in named if ref]
    if stated:
        findings.append(Finding("height_reference_from_name", "info",
                                f"Height reference taken from the field name: {', '.join(stated)}. A name is a hint, not a "
                                "guarantee.", {"fields": stated}))


def _surface_height_findings(s: surface.Surface, findings: list[Finding]) -> None:
    what = "point heights" if s.kind == "pointcloud" else "raster values"
    if s.vertical is None:
        findings.append(Finding("height_reference_unstated", "caveat",
                                f"The {what} of {s.name} have no vertical CRS: nothing says whether they are ellipsoidal "
                                "(GNSS) or above a height datum such as AHD. In Melbourne the two differ by about 4.7 m; in "
                                "Perth by 32 m. Compare with survey marks (--against) to find out.",
                                {"fields": [f"the {what}"]}))
    else:
        findings.append(Finding("vertical_crs", "info", f"Heights are declared as {s.vertical.name}.",
                                {"vertical_crs": s.vertical.name}))
    factor = s.z_factor
    if abs(factor - 1.0) > 1e-9:
        unit = (s.vertical or s.horizontal).axis_info[0].unit_name  # type: ignore[union-attr]  # factor != 1 needs one
        findings.append(Finding("height_units", "info",
                                f"Heights are in {unit} ({factor:.10g} m each); GeoSpark converts them to metres when "
                                "comparing." + ("" if s.vertical is not None else " With no vertical CRS, the height unit "
                                "is taken to be the horizontal one."), {"metres_per_unit": factor}))
    if s.kind == "pointcloud" and not s.ground:
        findings.append(Finding("no_ground_class", "info",
                                "No points are classified as ground (class 2) in the sample read, so a comparison with "
                                "survey marks uses all points near each mark (trees and roofs included)."))


def _finish(report: dict[str, Any]) -> dict[str, Any]:
    findings: list[Finding] = report["findings"]
    report["findings"] = [asdict(f) for f in findings]
    problems = [f for f in findings if f.severity == "problem"]
    caveats = [f for f in findings if f.severity == "caveat"]
    report["verdict"] = ("problem" if problems else "check the caveats" if caveats else "no issues found")
    return report


# --- two files ---------------------------------------------------------------------------------


def _local_offset(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """(east, north) metres from a to b."""
    az, _baz, dist = _GEOD.inv(a[0], a[1], b[0], b[1])
    return dist * math.sin(math.radians(az)), dist * math.cos(math.radians(az))


def _pairs(a: _Raw, b: _Raw, a_ll: list[tuple[float, float]], b_ll: list[tuple[float, float]],
           id_field: str | None) -> tuple[list[tuple[int, int]], str]:
    if id_field:
        index = {str(p.get(id_field)): j for j, p in enumerate(b.props) if p.get(id_field) is not None}
        return [(i, index[str(p.get(id_field))]) for i, p in enumerate(a.props) if str(p.get(id_field)) in index], f"field '{id_field}'"
    common = set(a.props[0]) & set(b.props[0]) if a.props and b.props else set()
    for candidate in ("id", "ID", "fid", "mark", "mark_id", "name", "site", "station"):
        if candidate in common:
            index = {str(p.get(candidate)): j for j, p in enumerate(b.props) if p.get(candidate) not in (None, "")}
            pairs = [(i, index[str(p.get(candidate))]) for i, p in enumerate(a.props) if str(p.get(candidate)) in index]
            if len(pairs) >= max(1, 0.5 * min(len(a.props), len(b.props))):
                return pairs, f"shared field '{candidate}'"
    pairs = []
    for i, pa in enumerate(a_ll):
        best = min(range(len(b_ll)), key=lambda j: _GEOD.inv(pa[0], pa[1], b_ll[j][0], b_ll[j][1])[2], default=None)
        if best is not None and _GEOD.inv(pa[0], pa[1], b_ll[best][0], b_ll[best][1])[2] <= _MAX_PAIR_M:
            pairs.append((i, best))
    return pairs, f"nearest feature within {int(_MAX_PAIR_M)} m"


def _wgs84(raw: _Raw) -> list[tuple[float, float]]:
    """Each feature's position in the frame GeoSpark analyses in (GDA2020 for Australian datums,
    otherwise WGS 84), using the official transformation for the datum the file declares."""
    to = Transformer.from_crs(raw.crs, layers._common_frame(raw.crs), always_xy=True)
    return [to.transform(x, y) for x, y in raw.xy]


def _reinterpretations(raw: _Raw) -> list[tuple[str, CRS, float, bool]]:
    """Ways a projected file's numbers are commonly mislabelled: another zone, feet, swapped axes."""
    out: list[tuple[str, CRS, float, bool]] = []
    epsg = raw.crs.to_epsg() if raw.crs else None
    families = [(28348, 28358, "GDA94 / MGA zone {}"), (7848, 7858, "GDA2020 / MGA zone {}"),
                (32701, 32760, "WGS 84 / UTM zone {}S"), (32601, 32660, "WGS 84 / UTM zone {}N")]
    for lo, hi, _label in families:
        if epsg and lo <= epsg <= hi:
            for code in range(max(lo, epsg - 2), min(hi, epsg + 2) + 1):
                if code != epsg:
                    out.append((f"zone: the numbers fit {CRS.from_epsg(code).name}", CRS.from_epsg(code), 1.0, False))
    if raw.crs and raw.crs.is_projected:
        out.append(("units: the numbers are in international feet, not metres", raw.crs, _FOOT, False))
        out.append(("units: the numbers are in US survey feet, not metres", raw.crs, _US_SURVEY_FOOT, False))
    if raw.crs:
        out.append(("axes: x and y are swapped", raw.crs, 1.0, True))
    return out


def compare_layers(path_a: str | Path, path_b: str | Path, crs_a: str | None = None, crs_b: str | None = None,
                   id_field: str | None = None) -> dict[str, Any]:
    """Measure the systematic offset between two layers of the same features, and diagnose it.

    Layer A is the reference. Features are paired by a shared id field (or ``id_field``), otherwise by
    nearest neighbour within 2 km. Both are first converted to WGS 84 with their declared CRS, as any
    tool would, so an offset that remains means a label or a unit is wrong.
    """
    ra, fa = _read_raw(path_a, None, crs_a)
    rb, fb = _read_raw(path_b, None, crs_b)
    findings: list[Finding] = fa + fb
    report: dict[str, Any] = {"reference": ra.name if ra else Path(str(path_a)).name,
                              "compared": rb.name if rb else Path(str(path_b)).name, "findings": findings}
    if ra is None or rb is None or not ra.xy or not rb.xy:
        findings.append(Finding("not_compared", "problem", "Both files need readable geometries and a CRS to be compared."))
        return _finish(report)
    report.update(crs_reference=ra.crs.name, crs_compared=rb.crs.name)
    if ra.surface or rb.surface:
        _surface_compare(ra, rb, report, findings)
        return _finish(report)
    a_ll, b_ll = _wgs84(ra), _wgs84(rb)
    ca, cb = _centre(a_ll), _centre(b_ll)
    apart = _GEOD.inv(ca[0], ca[1], cb[0], cb[1])[2]

    if apart > 5_000:  # far apart: a zone, unit or axis error moves a whole layer
        for label, crs, scale, swap in _reinterpretations(rb):
            xy = [((y, x) if swap else (x, y)) for x, y in rb.xy]
            xy = [(x * scale, y * scale) for x, y in xy]
            try:
                to = Transformer.from_crs(crs, layers._common_frame(crs), always_xy=True)
                alt = [to.transform(x, y) for x, y in xy]
            except Exception:
                continue
            alt = [p for p in alt if math.isfinite(p[0]) and math.isfinite(p[1])]
            if alt and _GEOD.inv(ca[0], ca[1], *_centre(alt))[2] < 200:
                findings.append(Finding("layer_mislabelled", "problem",
                                        f"{rb.name} lies {apart / 1000:.0f} km from {ra.name}. Read differently it lines up: "
                                        f"{label}.", {"distance_apart_m": round(apart), "fix": label}))
                return _finish(report)
        findings.append(Finding("layers_far_apart", "problem",
                                f"The layers are {apart / 1000:.1f} km apart and no common mislabelling (another zone, feet, "
                                "swapped axes) lines them up. They may not cover the same features.",
                                {"distance_apart_m": round(apart)}))
        return _finish(report)

    pairs, how = _pairs(ra, rb, a_ll, b_ll, id_field)
    report["paired_by"] = how
    report["pairs"] = len(pairs)
    if len(pairs) < 3:
        findings.append(Finding("too_few_pairs", "problem",
                                f"Only {len(pairs)} feature(s) could be paired ({how}); at least 3 are needed to measure an "
                                "offset. Pass id_field= if the files share an identifier."))
        return _finish(report)
    offsets = [_local_offset(a_ll[i], b_ll[j]) for i, j in pairs]
    de, dn = statistics.median(o[0] for o in offsets), statistics.median(o[1] for o in offsets)
    size = math.hypot(de, dn)
    spread = statistics.median(math.hypot(o[0] - de, o[1] - dn) for o in offsets)
    bearing = (math.degrees(math.atan2(de, dn)) + 360) % 360
    report["offset"] = {"east_m": round(de, 3), "north_m": round(dn, 3), "size_m": round(size, 3),
                        "bearing_deg": round(bearing, 1), "spread_m": round(spread, 3)}

    if how.startswith("nearest") and len(a_ll) > 1:
        spacing = statistics.median(
            min(_GEOD.inv(a_ll[i][0], a_ll[i][1], a_ll[k][0], a_ll[k][1])[2] for k in range(len(a_ll)) if k != i)
            for i in range(min(len(a_ll), 200)))
        report["typical_spacing_m"] = round(spacing, 3)
        if spacing < 3 * size:
            findings.append(Finding("pairing_uncertain", "caveat",
                                    f"Features are about {spacing:.2f} m apart, not much more than the {size:.2f} m offset, "
                                    "so nearest-neighbour pairs may match the wrong features. Pass id_field= with a shared "
                                    "identifier for a reliable comparison.", {"typical_spacing_m": round(spacing, 3)}))
    if size < max(0.05, 2 * spread):
        findings.append(Finding("consistent", "info",
                                f"No systematic offset: {size:.3f} m (scatter between features {spread:.3f} m).",
                                {"offset_m": round(size, 3)}))
    else:
        cause = _diagnose(ca, de, dn, ra, rb)
        if cause:
            findings.append(cause)
        else:
            findings.append(Finding("unexplained_offset", "caveat",
                                    f"{rb.name} sits {size:.2f} m from {ra.name} towards {bearing:.0f}° (scatter "
                                    f"{spread:.2f} m). That doesn't match the GDA94/GDA2020 shift or plate motion here; it "
                                    "may be a survey difference, a local transformation or digitising.",
                                    {"offset_m": round(size, 3), "bearing_deg": round(bearing, 1)}))
    _height_compare(ra, rb, pairs, ca, findings)
    return _finish(report)


def _diagnose(centre: tuple[float, float], de: float, dn: float, ra: _Raw, rb: _Raw) -> Finding | None:
    from geospark import geodesy

    lon, lat = centre
    if not (_AUSTRALIA[0] <= lon <= _AUSTRALIA[2] and _AUSTRALIA[1] <= lat <= _AUSTRALIA[3]):
        return None
    shifted = geodesy.transform("EPSG:4283", "EPSG:7844", [[lon, lat]]).coordinates[0]
    se, sn = _local_offset((lon, lat), (shifted[0], shifted[1]))  # where a GDA94 position moves in GDA2020
    # B - A = +shift: B's numbers are "a datum ahead" of A's (GDA2020 values where A has GDA94 values);
    # B - A = -shift: B is behind. Which layer carries the wrong label depends on what both are labelled.
    for sign in (1, -1):
        if math.hypot(de - sign * se, dn - sign * sn) < 0.25:
            ahead, behind = (rb, ra) if sign > 0 else (ra, rb)
            label_a, label_b = _datum_name(ra.crs), _datum_name(rb.crs)
            if "1994" in label_a and "1994" in label_b:
                wrong, holds, labelled = ahead, "GDA2020", "GDA94"
            elif "2020" in label_a and "2020" in label_b:
                wrong, holds, labelled = behind, "GDA94", "GDA2020"
            else:
                wrong, holds, labelled = None, None, None
            size = math.hypot(de, dn)
            if wrong is None:
                return Finding("gda94_gda2020_mixed", "problem",
                               f"{rb.name} sits {size:.2f} m from {ra.name}, matching the official GDA94 to GDA2020 shift "
                               f"here ({math.hypot(se, sn):.2f} m) although their labels already differ in datum: one of them "
                               "carries the wrong datum label.", {"expected_shift_m": round(math.hypot(se, sn), 3)})
            other = rb.name if wrong is ra else ra.name
            return Finding("gda94_gda2020_mixed", "problem",
                           f"{rb.name} sits {size:.2f} m from {ra.name}, matching the official GDA94 to GDA2020 shift here "
                           f"({math.hypot(se, sn):.2f} m). Both are labelled {labelled}, but {wrong.name} holds {holds} "
                           f"coordinates: relabel it as {holds} so it is converted (or {other} is the one mislabelled, "
                           "if you know it to be wrong).",
                           {"expected_shift_m": round(math.hypot(se, sn), 3), "mislabelled_layer": wrong.name,
                            "holds": holds, "labelled": labelled})
    years = []
    for epoch in (2026.0,):
        moved = geodesy.transform("EPSG:7912", "EPSG:7843", [[lon, lat, 0.0]], epoch=epoch).coordinates[0]
        ve, vn = _local_offset((moved[0], moved[1]), (lon, lat))  # ITRF position ahead of GDA2020, per (epoch - 2020)
        per_year = (ve / (epoch - 2020), vn / (epoch - 2020))
        k = (de * per_year[0] + dn * per_year[1]) / (per_year[0] ** 2 + per_year[1] ** 2)
        if k > 1 and math.hypot(de - k * per_year[0], dn - k * per_year[1]) < 0.1:
            years.append(k)
    if years:
        return Finding("epoch_difference", "problem",
                       f"The offset matches Australia's plate motion over about {years[0]:.1f} years: one layer is probably "
                       "in a global frame (ITRF/WGS 84) at a recent date and the other in GDA2020 (fixed at 2020).",
                       {"years": round(years[0], 1)})
    return None


def _height_compare(ra: _Raw, rb: _Raw, pairs: list[tuple[int, int]], centre: tuple[float, float],
                    findings: list[Finding]) -> None:
    ha, hb = _mark_heights(ra), _mark_heights(rb)
    if not ha or not hb:
        return
    diffs = [b - a for i, j in pairs if (a := ha[i]) is not None and (b := hb[j]) is not None]
    if len(diffs) < 3:
        return
    _height_verdict(diffs, centre, ra, rb, findings)


def _geoid_separation(centre: tuple[float, float]) -> tuple[float, str, str] | None:
    """(separation in metres, height datum, geoid model) of the national datum at a place."""
    from geospark import geodesy

    for datum in ("AHD", "ODN", "NZVD2016", "NAVD88"):
        try:
            r = geodesy.convert_height(centre[1], centre[0], 100.0, "ellipsoidal", datum)
        except geodesy.GeodesyError:
            continue
        return r["separation_m"], datum, r.get("geoid_model", "geoid")
    return None


def _height_verdict(diffs: list[float], centre: tuple[float, float], ra: _Raw, rb: _Raw, findings: list[Finding],
                    say_consistent: bool = False) -> None:
    """Name the cause of a height difference B - A when it matches one."""
    dz = statistics.median(diffs)
    spread = statistics.median(abs(d - dz) for d in diffs)
    if abs(dz) < max(0.05, 2 * spread):
        if say_consistent:
            findings.append(Finding("heights_consistent", "info",
                                    f"Heights agree: median difference {dz:+.3f} m (scatter {spread:.3f} m) over "
                                    f"{len(diffs)} marks.", {"median_dz_m": round(dz, 3), "spread_m": round(spread, 3)}))
        return
    sep = _geoid_separation(centre)
    if sep is not None and abs(abs(dz) - abs(sep[0])) < 0.3:
        n, datum, model = sep
        higher = rb.name if dz > 0 else ra.name
        findings.append(Finding("ellipsoidal_vs_ahd", "problem",
                                f"Heights differ by {dz:+.2f} m, the {model} separation here ({n:.2f} m): {higher} has "
                                f"ellipsoidal (GNSS) heights and the other {datum} heights, or the reverse where the geoid is "
                                "below the ellipsoid.", {"median_dz_m": round(dz, 3), "geoid_separation_m": round(n, 3),
                                                          "height_datum": datum}))
    else:
        findings.append(Finding("height_offset", "caveat",
                                f"Heights differ by a median {dz:+.2f} m (scatter {spread:.2f} m) between the layers"
                                + (f"; that is not the local geoid separation ({sep[0]:.2f} m)." if sep is not None else "."),
                                {"median_dz_m": round(dz, 3), "spread_m": round(spread, 3)}))


def _mark_heights(raw: _Raw) -> list[float | None]:
    fields = _height_fields(raw)
    if any(z is not None for z in raw.z):
        return raw.z
    out: list[float | None] = []
    for p in raw.props if fields else []:
        try:
            out.append(float(p[fields[0]]))
        except (KeyError, TypeError, ValueError):
            out.append(None)
    return out


def _surface_compare(ra: _Raw, rb: _Raw, report: dict[str, Any], findings: list[Finding]) -> None:
    """Survey marks against a point cloud or raster: the surface's height at each mark."""
    from geospark import geodesy

    if ra.surface and rb.surface:
        findings.append(Finding("not_compared", "problem",
                                "Compare a point cloud or raster with survey marks (points with heights), not with another "
                                "point cloud or raster."))
        return
    surf, marks = (ra, rb) if ra.surface else (rb, ra)
    s = surf.surface
    assert s is not None
    heights = _mark_heights(marks)
    keep = [i for i, h in enumerate(heights) if h is not None][: surface.MAX_MARKS]
    if len(keep) < 3:
        findings.append(Finding("not_compared", "problem",
                                f"{marks.name} needs at least 3 points with heights (a Z value or a height field) to check "
                                f"{s.name}'s heights."))
        return
    to_crs = s.horizontal
    assert to_crs is not None  # _read_surface refuses a surface without a CRS
    from_crs = marks.crs.sub_crs_list[0] if marks.crs.is_compound else marks.crs
    pts = [list(marks.xy[i]) for i in keep]
    try:
        xy = pts if from_crs.equals(to_crs) else geodesy.transform(from_crs.to_wkt(), to_crs.to_wkt(), pts).coordinates
    except geodesy.GeodesyError as e:
        findings.append(Finding("not_compared", "problem", f"The marks couldn't be put in {s.name}'s CRS: {e}"))
        return
    try:
        found = s.heights_at([(p[0], p[1]) for p in xy])
    except surface.SurfaceError as e:
        findings.append(Finding("not_compared", "problem", str(e)))
        return
    pairs = [(m, h) for i, h in zip(keep, found, strict=True) if h is not None and (m := heights[i]) is not None]
    report["paired_by"] = ("ground points within 1 m of each mark" if s.kind == "pointcloud" and s.ground
                           else "points within 1 m of each mark" if s.kind == "pointcloud" else "the raster cell at each mark")
    report["pairs"] = len(pairs)
    if len(pairs) < 3:
        findings.append(Finding("no_overlap", "problem",
                                f"Only {len(pairs)} of {len(keep)} marks have a surface height in {s.name}: the files may not "
                                "cover the same area, or one CRS label is wrong (check each file on its own first).",
                                {"marks": len(keep), "with_surface_height": len(pairs)}))
        return
    # B - A, whichever of the two is the surface
    diffs = [(h - m) if surf is rb else (m - h) for m, h in pairs]
    ratios = [h / m for m, h in pairs if abs(m) > 1.0]
    if len(ratios) >= 3:
        ratio = statistics.median(ratios)
        for unit, factor in (("feet", 1 / 0.3048), ("feet", 0.3048)):
            if abs(ratio - factor) < 0.01 * factor:
                findings.append(Finding("height_units_wrong", "problem",
                                        f"{s.name}'s heights are {ratio:.4f} times the marks' heights: one of them is in "
                                        f"{unit} where metres were expected (or the reverse).", {"ratio": round(ratio, 5)}))
                return
    lonlats = _wgs84(marks)
    before = len(findings)
    _height_verdict(diffs, _centre(lonlats), ra, rb, findings, say_consistent=True)
    if s.vertical is None and findings[before:] and findings[-1].code == "heights_consistent":
        findings.append(Finding("height_reference_inferred", "caveat",
                                f"{s.name} declares no vertical CRS, but its heights agree with {marks.name}'s, so they are "
                                "probably in the same height reference. Add the vertical CRS to the file so others needn't "
                                "check."))
