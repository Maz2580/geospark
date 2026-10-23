"""
Nominatim Geocoder Tool.

Uses OpenStreetMap's Nominatim service for geocoding and reverse geocoding.
"""

from __future__ import annotations

import os
from typing import ClassVar

import httpx

from geospark.protocol.schema import (
    SpatialContext,
    SpatialFeature,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)
from geospark.tools.base import BaseTool
from geospark.tools.geocoding import client as nominatim_client
from geospark.utils import USER_AGENT


class NominatimGeocoder(BaseTool):
    """Geocoding and reverse geocoding using OpenStreetMap Nominatim."""

    name = "geocoder"
    description = "Convert addresses to coordinates and coordinates to addresses"
    supported_operations: ClassVar[list[str]] = [
        SpatialOperation.GEOCODE.value,
        SpatialOperation.REVERSE_GEOCODE.value,
    ]

    BASE_URL: ClassVar[str] = "https://nominatim.openstreetmap.org"
    HEADERS: ClassVar[dict[str, str]] = {"User-Agent": USER_AGENT}

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute geocoding operation."""
        if query.operation == SpatialOperation.GEOCODE:
            return self._geocode(query)
        elif query.operation == SpatialOperation.REVERSE_GEOCODE:
            return self._reverse_geocode(query)
        return SpatialResult(errors=[f"Unsupported operation: {query.operation}"])

    def _geocode(self, query: SpatialQuery) -> SpatialResult:
        """Forward geocode: address/place name → coordinates."""
        search_text = (
            query.metadata.get("query", "") if query.metadata else ""
        )
        if not search_text:
            return SpatialResult(errors=["Geocode requires metadata.query"])

        try:
            data = nominatim_client.get_json(
                "search",
                {
                    "q": search_text,
                    "format": "geojson",
                    # Ask for enough candidates to re-rank, and their country (see _rank)
                    "limit": max(query.limit, 10),
                    "addressdetails": 1,
                },
            )
        except (httpx.HTTPError, ValueError) as e:
            # Upstream outage or bad response: report it instead of raising (which the API
            # would turn into an opaque 500)
            return SpatialResult(
                errors=[f"Geocoding service unavailable ({type(e).__name__}). Try again shortly."],
                sources=["openstreetmap-nominatim"],
            )

        found = data.get("features", [])
        warnings: list[str] = []
        if not found and "," in search_text:
            found, warnings = self._search_inside(search_text, query.limit)
        found, why = self._rank(found)
        found = found[: query.limit]
        warnings.extend(why)

        features = [
            SpatialFeature(
                geometry=f["geometry"],
                properties={
                    "display_name": f["properties"].get("display_name", ""),
                    "type": f["properties"].get("type", ""),
                    "importance": f["properties"].get("importance", 0),
                    **({"country_code": cc} if (cc := _country(f)) else {}),
                },
            )
            for f in found
        ]

        return SpatialResult(
            features=features,
            spatial_context=SpatialContext(
                total_features=len(features),
                summary=f"Found {len(features)} results for '{search_text}'",
            ),
            sources=["openstreetmap-nominatim"],
            warnings=warnings,
        )

    # Kinds of match that are rarely what a name means, and how much importance they lose when ranking.
    # Live: "University of Melbourne" came back first as a future campus still under construction,
    # 4.6 km from the Parkville campus, so every distance from the university was wrong.
    DEMOTE: ClassVar[dict[tuple[str, str], float]] = {
        ("landuse", "construction"): 0.2, ("landuse", "brownfield"): 0.2, ("landuse", "greenfield"): 0.2,
        ("highway", "bus_stop"): 0.05, ("highway", "platform"): 0.05, ("public_transport", "platform"): 0.05,
        ("public_transport", "stop_position"): 0.05, ("railway", "platform"): 0.05,
    }
    PREFER_WINDOW: ClassVar[float] = 0.3  # how much importance a match in the preferred country may lack

    @classmethod
    def _rank(cls, found: list[dict]) -> tuple[list[dict], list[str]]:
        """Re-rank Nominatim's candidates: unlikely kinds of match down, and, if the operator set
        GEOSPARK_GEOCODE_PREFER_COUNTRY (e.g. "au"), a close match in that country first.

        Live: "Parkville" was Parkville, Maryland and "Brunswick" Braunschweig, for a server whose
        users are in Melbourne. A preference is only a tie-break among likely matches, and the result
        says when it changed the answer, so a reader can add the country if they meant elsewhere.
        """
        if len(found) < 2:
            return found, []

        def score(f: dict) -> float:
            props = f.get("properties") or {}
            kind = (str(props.get("category") or ""), str(props.get("type") or ""))
            return float(props.get("importance") or 0) - cls.DEMOTE.get(kind, 0.0)

        ranked = sorted(found, key=score, reverse=True)  # stable: Nominatim's order breaks ties
        warnings: list[str] = []
        preferred = [c.strip().lower() for c in os.getenv("GEOSPARK_GEOCODE_PREFER_COUNTRY", "").split(",") if c.strip()]
        if preferred and _country(ranked[0]) not in preferred:
            best = score(ranked[0])
            local = next((f for f in ranked if _country(f) in preferred and best - score(f) <= cls.PREFER_WINDOW), None)
            if local is not None:
                ranked.remove(local)
                ranked.insert(0, local)
                warnings.append(
                    f"'{_name(local)}' was chosen over '{_name(ranked[1])}' because this server prefers places in "
                    f"{', '.join(c.upper() for c in preferred)}. Add the country to the name if you meant another place.")
        return ranked, warnings

    @staticmethod
    def _search_inside(search_text: str, limit: int) -> tuple[list[dict], list[str]]:
        """"Mount Wellington, Hobart" finds nothing: the peak's address doesn't name Hobart. Search
        for the part before the last comma inside the area named after it instead."""
        name, _, area = search_text.rpartition(",")
        name, area = name.strip(), area.strip()
        if not name or not area:
            return [], []
        try:
            areas = nominatim_client.get_json("search", {"q": area, "format": "geojson", "limit": 1})
            box = ((areas or {}).get("features") or [{}])[0].get("bbox")
            if not box:
                return [], []
            # Widen the area's box: a landmark named after a city is often just outside its boundary
            pad_x, pad_y = max((box[2] - box[0]) * 0.25, 0.05), max((box[3] - box[1]) * 0.25, 0.05)
            data = nominatim_client.get_json("search", {
                "q": name, "format": "geojson", "limit": limit, "bounded": 1,
                "viewbox": f"{box[0] - pad_x},{box[3] + pad_y},{box[2] + pad_x},{box[1] - pad_y}",
            })
        except (httpx.HTTPError, ValueError, TypeError, IndexError):
            return [], []
        found = (data or {}).get("features") or []
        if not found:
            return [], []
        shown = found[0].get("properties", {}).get("display_name", name)
        return found, [f"No exact match for '{search_text}'; used '{shown}', the best match for "
                       f"'{name}' in the {area} area."]

    def _reverse_geocode(self, query: SpatialQuery) -> SpatialResult:
        """Reverse geocode: coordinates → address/place name."""
        if query.geometry is None:
            return SpatialResult(errors=["Reverse geocode requires a point geometry"])

        coords = query.geometry.coordinates  # type: ignore
        lon, lat = coords[0], coords[1]

        try:
            data = nominatim_client.get_json(
                "reverse",
                {
                    "lat": lat,
                    "lon": lon,
                    "format": "geojson",
                },
            )
        except (httpx.HTTPError, ValueError) as e:
            return SpatialResult(
                errors=[f"Geocoding service unavailable ({type(e).__name__}). Try again shortly."],
                sources=["openstreetmap-nominatim"],
            )

        features = []
        if "features" in data:
            for f in data["features"]:
                features.append(
                    SpatialFeature(
                        geometry=f["geometry"],
                        properties=f.get("properties", {}),
                    )
                )

        return SpatialResult(
            features=features,
            spatial_context=SpatialContext(
                total_features=len(features),
                summary=f"Reverse geocoded ({lat}, {lon})",
            ),
            sources=["openstreetmap-nominatim"],
        )


def _country(feature: dict) -> str:
    return str(((feature.get("properties") or {}).get("address") or {}).get("country_code") or "").lower()


def _name(feature: dict) -> str:
    return str((feature.get("properties") or {}).get("display_name") or "?")
