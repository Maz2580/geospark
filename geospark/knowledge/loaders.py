"""Data loaders for the spatial knowledge graph.

Provides adapters to populate a ``SpatialKnowledgeGraph`` from common
geospatial data sources (GeoJSON files, OpenStreetMap via Overpass API).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from geospark.knowledge.entities import SpatialEntity


class GeoJSONLoader:
    """Load GeoJSON features as ``SpatialEntity`` objects.

    Each GeoJSON Feature becomes an entity whose ``id`` is derived from
    the feature's ``"id"`` property (if present) or a hash of its geometry.
    """

    def load(
        self,
        geojson: dict[str, Any],
        entity_type: str = "feature",
    ) -> list[SpatialEntity]:
        """Convert a GeoJSON object into a list of spatial entities.

        Accepts both a ``FeatureCollection`` and a single ``Feature``.

        Args:
            geojson: A GeoJSON dict (FeatureCollection or Feature).
            entity_type: Default entity type assigned to every loaded
                entity. Individual features can override this via the
                ``"entity_type"`` or ``"category"`` property.

        Returns:
            List of created ``SpatialEntity`` instances.
        """
        features: list[dict[str, Any]]
        if geojson.get("type") == "FeatureCollection":
            features = geojson.get("features", [])
        elif geojson.get("type") == "Feature":
            features = [geojson]
        else:
            # Bare geometry -- wrap it
            features = [{"type": "Feature", "geometry": geojson, "properties": {}}]

        entities: list[SpatialEntity] = []
        for feat in features:
            geometry = feat.get("geometry")
            if geometry is None:
                continue

            props = feat.get("properties") or {}

            # Determine entity ID
            feat_id = feat.get("id") or props.get("id")
            if feat_id is None:
                # Deterministic hash from geometry so the same feature
                # always gets the same ID.
                geom_str = json.dumps(geometry, sort_keys=True)
                feat_id = hashlib.sha256(geom_str.encode()).hexdigest()[:12]
            feat_id = str(feat_id)

            # Determine name
            name = (
                props.get("name")
                or props.get("title")
                or props.get("label")
                or feat_id
            )

            # Determine entity type (allow override from properties)
            etype = (
                props.get("entity_type")
                or props.get("category")
                or entity_type
            )

            # Collect tags
            tags: list[str] = []
            if "tags" in props and isinstance(props["tags"], list):
                tags = props["tags"]

            entities.append(
                SpatialEntity(
                    id=feat_id,
                    name=str(name),
                    entity_type=str(etype),
                    geometry=geometry,
                    properties=props,
                    tags=tags,
                )
            )

        return entities


class OverpassLoader:
    """Load OpenStreetMap data via the Overpass API.

    Queries the public Overpass endpoint for amenities within a bounding
    box and converts the results into ``SpatialEntity`` objects.
    """

    OVERPASS_URL = "https://overpass-api.de/api/interpreter"

    def load_amenities(
        self,
        bbox: tuple[float, float, float, float],
        amenity_type: str,
    ) -> list[SpatialEntity]:
        """Fetch amenities from OSM via Overpass and return as entities.

        Args:
            bbox: Bounding box as ``(min_lat, min_lon, max_lat, max_lon)``.
                Note: Overpass uses ``(south, west, north, east)`` order.
            amenity_type: OSM amenity value (e.g. ``"hospital"``,
                ``"school"``, ``"restaurant"``).

        Returns:
            List of ``SpatialEntity`` objects.

        Raises:
            httpx.HTTPStatusError: If the Overpass API returns an error.
            RuntimeError: If the response cannot be parsed.
        """
        south, west, north, east = bbox
        query = (
            f"[out:json][timeout:25];"
            f'node["amenity"="{amenity_type}"]'
            f"({south},{west},{north},{east});"
            f"out body;"
        )

        try:
            response = httpx.post(
                self.OVERPASS_URL,
                data={"data": query},
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise
        except httpx.HTTPError as err:
            raise RuntimeError(
                f"Overpass API request failed: {err}"
            ) from err

        try:
            data = response.json()
        except Exception as err:
            raise RuntimeError(
                f"Failed to parse Overpass response: {err}"
            ) from err

        entities: list[SpatialEntity] = []
        for element in data.get("elements", []):
            if "lat" not in element or "lon" not in element:
                continue

            osm_id = str(element.get("id", ""))
            tags = element.get("tags", {})
            name = tags.get("name", f"{amenity_type}_{osm_id}")

            geometry: dict[str, Any] = {
                "type": "Point",
                "coordinates": [element["lon"], element["lat"]],
            }

            properties: dict[str, Any] = {
                "osm_id": osm_id,
                "amenity": amenity_type,
                **tags,
            }

            tag_list = [amenity_type]
            if "cuisine" in tags:
                tag_list.append(tags["cuisine"])

            entities.append(
                SpatialEntity(
                    id=f"osm_{osm_id}",
                    name=name,
                    entity_type=amenity_type,
                    geometry=geometry,
                    properties=properties,
                    tags=tag_list,
                )
            )

        return entities
