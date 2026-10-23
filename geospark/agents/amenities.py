"""Nearby amenities for the agents, from OpenStreetMap with Overture Maps as the fallback.

The public Overpass servers are slow (20-30 s per query) and rate-limit by IP: after a few
queries they refuse connections or answer 504, and every agent that asked them then failed.
This module asks Overpass once per request (all amenity types in one query, with a time limit),
remembers a failure for a few minutes so later requests don't wait for it again, and falls back
to Overture Maps places, which GeoSpark reads itself (no rate limit).

Overture's categories are broader than OpenStreetMap's (a doctor's office can be filed as a
hospital, a driving school as a school), so each amenity type maps to specific Overture
categories and low-confidence places are dropped; the result says which source answered and
carries a caveat when it was the fallback. If neither source answers, ``AmenityLookupError`` is
raised: callers must report "not checked", never "nothing nearby".
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from geospark.knowledge.entities import SpatialEntity
from geospark.knowledge.loaders import OverpassLoader
from geospark.protocol.provenance import Provenance, source_provenance
from geospark.utils.geo import overpass_bbox

OVERPASS_TIMEOUT_S = 20.0  # one combined query; the public servers rarely answer later than this
OVERPASS_COOLDOWN_S = 300.0  # after a failure, skip Overpass for this long and go straight to Overture
OVERTURE_MAX_RADIUS_M = 2000.0  # Overture queries are capped (cost); a larger search is narrowed and noted
OVERTURE_MIN_CONFIDENCE = 0.6

# Types Overture is NOT used for: its health records are unreliable (in Paris, private practices,
# a bar called "the hospital of broken hearts" and a hospital in Cameroon all came back as
# hospitals near the Eiffel Tower). If OpenStreetMap is down these are reported as not retrieved.
NO_FALLBACK = frozenset({"hospital", "clinic", "doctors", "dentist"})

# OSM amenity value -> (Overture search term, Overture categories accepted). A place matches on its
# taxonomy (e.g. "grocery_store") when it has one, otherwise on its basic category; the terms were
# checked against Overture near the University of Melbourne (2026-10): "supermarket", "university"
# and "police" match nothing in Overture, so supermarkets were reported as none near the CBD.
OVERTURE_CATEGORIES: dict[str, tuple[str, frozenset[str]]] = {
    "school": ("school", frozenset({"school", "elementary_school", "middle_school", "high_school",
                                    "private_school", "public_school"})),
    "kindergarten": ("preschool", frozenset({"preschool", "kindergarten"})),
    "university": ("college_university", frozenset({"college_university", "university"})),
    "pharmacy": ("pharmacy", frozenset({"pharmacy", "pharmacy_and_drug_store", "drugstore"})),
    "restaurant": ("restaurant", frozenset({"restaurant"})),
    "cafe": ("cafe", frozenset({"cafe", "coffee_shop"})),
    "bank": ("bank", frozenset({"bank", "bank_or_credit_union"})),
    "supermarket": ("grocery_store", frozenset({"grocery_store", "supermarket"})),
    "library": ("library", frozenset({"library", "public_library"})),
    "police": ("police_station", frozenset({"police_department", "police_station"})),
    "fire_station": ("fire_station", frozenset({"fire_department", "fire_station"})),
}


def _accepted(properties: dict, amenity: str, accepted: frozenset[str]) -> bool:
    """Does an Overture place count as this amenity? Its taxonomy decides ("grocery_store"), or its
    basic category when the taxonomy is a kind of it ("italian_restaurant") or missing."""
    taxonomy = str(properties.get("taxonomy") or "").lower()
    category = str(properties.get("category") or "").lower()
    if taxonomy in accepted:
        return True
    return category in accepted and (not taxonomy or taxonomy.endswith(f"_{amenity}"))


_lock = threading.Lock()
_overpass_down_until = 0.0


class AmenityLookupError(RuntimeError):
    """Neither OpenStreetMap nor Overture Maps answered."""


@dataclass
class AmenityLookup:
    """Amenities found per type, and where they came from."""

    by_type: dict[str, list[SpatialEntity]]
    source: str  # "openstreetmap-overpass" or "overture-maps"
    provenance: list[Provenance] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    radius_m: float = 0.0  # the radius actually searched
    unavailable: list[str] = field(default_factory=list)  # types not retrieved (unknown, not "none")


def _overpass_available() -> bool:
    return time.monotonic() >= _overpass_down_until


def _mark_overpass_down() -> None:
    global _overpass_down_until
    with _lock:
        _overpass_down_until = time.monotonic() + OVERPASS_COOLDOWN_S


def reset() -> None:
    """Forget a remembered Overpass failure (tests)."""
    global _overpass_down_until
    with _lock:
        _overpass_down_until = 0.0


def find_amenities(
    lat: float, lon: float, radius_m: float, types: list[str], overpass: OverpassLoader | None = None,
) -> AmenityLookup:
    """Amenities of each type around a point: OpenStreetMap first, Overture Maps if it fails."""
    types = list(dict.fromkeys(t for t in types if t))
    if not types:
        return AmenityLookup(by_type={}, source="none", radius_m=radius_m)
    overpass_error: Exception | None = None
    loader = overpass or OverpassLoader()
    bbox = overpass_bbox(lat, lon, radius_m)
    # A self-hosted Overpass covering this area is always asked; the cooldown is for the public servers
    covers = getattr(loader, "covers", None)
    local = bool(covers and covers(bbox))
    public_ok = _overpass_available()
    if local or public_ok:
        try:
            kwargs = {} if public_ok else {"allow_public": False}
            by_type = loader.load_amenities_by_type(bbox, types, timeout=OVERPASS_TIMEOUT_S, **kwargs)
            return AmenityLookup(by_type=by_type, source="openstreetmap-overpass",
                                 provenance=[source_provenance("openstreetmap-overpass")], radius_m=radius_m)
        except Exception as e:  # rate limit, 504, connection refused, timeout
            overpass_error = e
            if public_ok:
                _mark_overpass_down()
    try:
        return _from_overture(lat, lon, radius_m, types)
    except Exception as e:
        osm = ("OpenStreetMap's public servers did not answer" if overpass_error
               else "OpenStreetMap's public servers were not answering a few minutes ago")
        if all(t in NO_FALLBACK for t in types):
            fallback = f"there is no reliable fallback for {', '.join(types)}"
        else:
            fallback = f"Overture Maps also failed ({str(e)[:100]})"
        raise AmenityLookupError(f"Nearby places could not be retrieved: {osm}, and {fallback}.") from e


def _from_overture(lat: float, lon: float, radius_m: float, types: list[str]) -> AmenityLookup:
    from geospark.tools.overture.client import query

    radius = min(radius_m, OVERTURE_MAX_RADIUS_M)
    by_type: dict[str, list[SpatialEntity]] = {}
    provenance: list[Provenance] = []
    unavailable = [t for t in types if t in NO_FALLBACK]
    if unavailable and len(unavailable) == len(types):
        raise RuntimeError(f"no reliable fallback for {', '.join(unavailable)}")
    for amenity in [t for t in types if t not in NO_FALLBACK]:
        term, accepted = OVERTURE_CATEGORIES.get(amenity, (amenity, frozenset({amenity})))
        result = query("places", lat, lon, radius_m=radius, category=term)
        if not provenance:
            provenance = list(result.provenance)
        entities = []
        for f in result.features:
            p = f.properties
            if not _accepted(p, amenity, accepted):
                continue
            if (p.get("confidence") or 0) < OVERTURE_MIN_CONFIDENCE:
                continue
            geometry = f.geometry if isinstance(f.geometry, dict) else f.geometry.model_dump()
            entities.append(SpatialEntity(
                id=str(p.get("id") or f.id or ""), name=str(p.get("name") or amenity),
                entity_type=amenity, geometry=geometry,
                properties={"overture_category": p.get("category"), "confidence": p.get("confidence")},
            ))
        by_type[amenity] = entities
    warnings = ["Nearby places come from Overture Maps because OpenStreetMap's public servers did not "
                "answer. Overture's categories are broader than OpenStreetMap's (a driving school can be "
                "filed as a school), and places with confidence below 0.6 were left out."]
    # Types in ``unavailable`` are reported by each agent as a data gap (unknown, not "none")
    if radius < radius_m:
        warnings.append(f"Overture searches are limited to {int(OVERTURE_MAX_RADIUS_M)} m, so nearby places "
                        f"were searched within {int(radius)} m instead of {int(radius_m)} m.")
    return AmenityLookup(by_type=by_type, source="overture-maps", provenance=provenance,
                         warnings=warnings, radius_m=radius, unavailable=unavailable)


def place_boundary(name: str) -> dict | None:
    """A place's boundary from Nominatim (simplified), or None if it has none (a point, e.g. a building)."""
    from geospark.tools.geocoding import client as nominatim_client
    from geospark.tools.geocoding.nominatim import NominatimGeocoder

    try:
        data = nominatim_client.get_json("search", {
            "q": name, "format": "geojson", "limit": 10, "addressdetails": 1,
            "polygon_geojson": 1, "polygon_threshold": 0.0005,
        })
    except Exception:
        return None
    # The same ranking as geocoding, so "Parkville" is the same Parkville in both (not Maryland here)
    features, _ = NominatimGeocoder._rank((data or {}).get("features") or [])
    geometry = features[0].get("geometry") if features else None
    if geometry and geometry.get("type") in ("Polygon", "MultiPolygon"):
        return dict(geometry)
    return None
