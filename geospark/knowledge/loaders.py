"""Data loaders for the spatial knowledge graph.

Provides adapters to populate a ``SpatialKnowledgeGraph`` from common
geospatial data sources (GeoJSON files, OpenStreetMap via Overpass API).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, ClassVar

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

    Queries the public Overpass endpoint and converts results into
    ``SpatialEntity`` objects. Supports amenities, administrative
    boundaries, and city data (boundary + landmarks).
    """

    OVERPASS_URL = "https://overpass-api.de/api/interpreter"
    # Asked at the same time; the first good answer is used. The public
    # servers often take 15-30 s and answer 504 when busy, so waiting on one
    # and then trying the next made a report take a minute or more.
    OVERPASS_URLS = (
        OVERPASS_URL,
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    )
    # The public Overpass servers answer 406/403 to the default httpx user agent.
    USER_AGENT = "GeoSpark (https://github.com/Maz2580/geospark)"

    # Answers are kept for a while: OpenStreetMap changes slowly and the same
    # town is often asked about repeatedly.
    CACHE_TTL_S = 6 * 3600
    CACHE_SIZE = 256
    _cache: ClassVar[OrderedDict[str, tuple[float, dict[str, Any]]]] = OrderedDict()
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()

    def _query(self, overpass_ql: str, timeout: float = 40.0) -> dict[str, Any]:
        """Overpass query, recorded in an active run record (see geospark.runs)."""
        from geospark.runs import record

        data = self._query_uncached_or_cached(overpass_ql, timeout)
        record("data", "overpass", overpass_ql, data, "openstreetmap-overpass")
        return data

    def _query_uncached_or_cached(self, overpass_ql: str, timeout: float = 40.0) -> dict[str, Any]:
        """Execute an Overpass QL query and return the JSON response.

        Every endpoint in ``OVERPASS_URLS`` is asked at once and the first
        good answer wins. If they all fail quickly (a busy server answers 504
        at once) they are asked again while time remains. ``timeout`` bounds
        the whole call; the last error is raised if no endpoint answers.
        """
        key = hashlib.sha256(overpass_ql.encode()).hexdigest()
        cached = self._cached(key)
        if cached is not None:
            return cached

        deadline = time.monotonic() + timeout
        last_error: Exception = RuntimeError("Overpass API request timed out")
        for _ in range(2):
            remaining = deadline - time.monotonic()
            if remaining < 2:
                break
            try:
                data = self._race(overpass_ql, remaining)
            except Exception as err:
                last_error = err
                continue
            self._remember(key, data)
            return data
        raise last_error

    def _race(self, overpass_ql: str, timeout: float) -> dict[str, Any]:
        """Ask every endpoint at once; return the first good answer."""
        pool = ThreadPoolExecutor(max_workers=len(self.OVERPASS_URLS))
        pending = {pool.submit(self._post, url, overpass_ql, timeout) for url in self.OVERPASS_URLS}
        last_error: Exception = RuntimeError("Overpass API request timed out")
        deadline = time.monotonic() + timeout
        try:
            while pending:
                done, pending = wait(
                    pending,
                    timeout=max(deadline - time.monotonic(), 0),
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    break
                for future in done:
                    try:
                        return future.result()
                    except Exception as err:
                        last_error = err
            raise last_error
        finally:
            # Slower requests finish on their own; nobody waits for them
            pool.shutdown(wait=False, cancel_futures=True)

    def _post(self, url: str, overpass_ql: str, timeout: float) -> dict[str, Any]:
        try:
            response = httpx.post(
                url,
                data={"data": overpass_ql},
                headers={"User-Agent": self.USER_AGENT},
                timeout=timeout,
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
        except httpx.HTTPStatusError:
            raise
        except httpx.HTTPError as err:
            raise RuntimeError(f"Overpass API request failed: {err}") from err
        except ValueError as err:
            raise RuntimeError(f"Failed to parse Overpass response: {err}") from err

    @classmethod
    def _cached(cls, key: str) -> dict[str, Any] | None:
        with cls._cache_lock:
            entry = cls._cache.get(key)
            if entry is None or time.monotonic() - entry[0] > cls.CACHE_TTL_S:
                return None
            cls._cache.move_to_end(key)
            return entry[1]

    @classmethod
    def _remember(cls, key: str, data: dict[str, Any]) -> None:
        with cls._cache_lock:
            cls._cache[key] = (time.monotonic(), data)
            cls._cache.move_to_end(key)
            while len(cls._cache) > cls.CACHE_SIZE:
                cls._cache.popitem(last=False)

    @staticmethod
    def _element_to_entity(
        element: dict[str, Any],
        entity_type: str,
        tag_keys: list[str] | None = None,
    ) -> SpatialEntity | None:
        """Convert a single Overpass element to a SpatialEntity."""
        osm_id = str(element.get("id", ""))
        tags = element.get("tags", {})
        name = tags.get("name", f"{entity_type}_{osm_id}")
        elem_type = element.get("type", "node")

        # Build geometry
        geometry: dict[str, Any] | None = None
        if elem_type == "node" and "lat" in element and "lon" in element:
            geometry = {"type": "Point", "coordinates": [element["lon"], element["lat"]]}
        elif elem_type == "way" and "geometry" in element:
            coords = [[p["lon"], p["lat"]] for p in element["geometry"]]
            if len(coords) >= 4 and coords[0] == coords[-1]:
                geometry = {"type": "Polygon", "coordinates": [coords]}
            elif len(coords) >= 2:
                geometry = {"type": "LineString", "coordinates": coords}
        elif elem_type == "relation" and "members" in element:
            # Extract outer way geometries for relations (simplified)
            outer_coords: list[list[list[float]]] = []
            for member in element.get("members", []):
                if member.get("role") == "outer" and "geometry" in member:
                    ring = [[p["lon"], p["lat"]] for p in member["geometry"]]
                    if len(ring) >= 4:
                        if ring[0] != ring[-1]:
                            ring.append(ring[0])
                        outer_coords.append(ring)
            if len(outer_coords) == 1:
                geometry = {"type": "Polygon", "coordinates": outer_coords}
            elif len(outer_coords) > 1:
                geometry = {"type": "MultiPolygon", "coordinates": [[r] for r in outer_coords]}

        # "out center" gives ways and relations a single representative point
        center = element.get("center")
        if geometry is None and center and "lat" in center and "lon" in center:
            geometry = {"type": "Point", "coordinates": [center["lon"], center["lat"]]}

        if geometry is None:
            return None

        properties: dict[str, Any] = {"osm_id": osm_id, "osm_type": elem_type, **tags}
        tag_list = [entity_type]
        for k in tag_keys or []:
            if k in tags:
                tag_list.append(tags[k])

        return SpatialEntity(
            id=f"osm_{osm_id}",
            name=name,
            entity_type=entity_type,
            geometry=geometry,
            properties=properties,
            tags=tag_list,
        )

    def load_amenities(
        self,
        bbox: tuple[float, float, float, float],
        amenity_type: str,
    ) -> list[SpatialEntity]:
        """Fetch amenities from OSM via Overpass and return as entities.

        Args:
            bbox: Bounding box as ``(min_lat, min_lon, max_lat, max_lon)``.
            amenity_type: OSM amenity value (e.g. ``"hospital"``).

        Returns:
            List of ``SpatialEntity`` objects.
        """
        return self.load_amenities_by_type(bbox, [amenity_type])[amenity_type]

    def load_amenities_by_type(
        self,
        bbox: tuple[float, float, float, float],
        amenity_types: list[str],
    ) -> dict[str, list[SpatialEntity]]:
        """Fetch several amenity types in one Overpass request.

        Hospitals, schools and the like are often mapped as building outlines
        (ways) rather than points, so nodes, ways and relations are all
        queried and each is reduced to a single point.

        Args:
            bbox: Bounding box as ``(min_lat, min_lon, max_lat, max_lon)``.
            amenity_types: OSM amenity values (e.g. ``["hospital", "school"]``).

        Returns:
            Entities grouped by amenity type; every requested type has a key.

        Raises:
            Exception: if no Overpass endpoint answers. Callers must treat that
                as "unknown", never as "nothing there".
        """
        south, west, north, east = bbox
        wanted = [t for t in amenity_types if t.replace("_", "").isalnum()]
        pattern = "|".join(wanted)
        query = (
            f"[out:json][timeout:25];"
            f'nwr["amenity"~"^({pattern})$"]'
            f"({south},{west},{north},{east});"
            f"out center;"
        )
        data = self._query(query)

        grouped: dict[str, list[SpatialEntity]] = {t: [] for t in amenity_types}
        for element in data.get("elements", []):
            amenity = element.get("tags", {}).get("amenity")
            if amenity not in grouped:
                continue
            ent = self._element_to_entity(element, amenity, ["cuisine"])
            if ent:
                grouped[amenity].append(ent)
        return grouped

    def load_admin_boundary(
        self,
        name: str,
        admin_level: int = 8,
    ) -> SpatialEntity | None:
        """Fetch an administrative boundary by name.

        Args:
            name: Name of the admin area (e.g. ``"Paris"``, ``"Melbourne"``).
            admin_level: OSM admin_level (2=country, 4=state, 6=county,
                8=city/town). Default 8 (city).

        Returns:
            A ``SpatialEntity`` with Polygon/MultiPolygon geometry, or None.
        """
        query = (
            f'[out:json][timeout:30];'
            f'relation["boundary"="administrative"]'
            f'["admin_level"="{admin_level}"]'
            f'["name"="{name}"];'
            f'out body geom;'
        )
        data = self._query(query, timeout=45.0)

        elements = data.get("elements", [])
        if not elements:
            return None

        return self._element_to_entity(elements[0], "admin_boundary", ["admin_level", "boundary"])

    def load_city(
        self,
        city_name: str,
        include_landmarks: bool = True,
        landmark_types: list[str] | None = None,
    ) -> list[SpatialEntity]:
        """Load a city boundary and optionally its key landmarks.

        Args:
            city_name: City name (e.g. ``"Melbourne"``).
            include_landmarks: Whether to also load tourism/landmark nodes.
            landmark_types: OSM tourism values to load. Defaults to
                ``["attraction", "museum", "monument", "viewpoint"]``.

        Returns:
            List of entities: the city boundary + any landmarks found.
        """
        entities: list[SpatialEntity] = []

        # Load city boundary
        boundary = self.load_admin_boundary(city_name, admin_level=8)
        if boundary is None:
            # Try admin_level 6 (some cities use this)
            boundary = self.load_admin_boundary(city_name, admin_level=6)
        if boundary:
            entities.append(boundary)

        if not include_landmarks:
            return entities

        # Load landmarks within the city's area
        types = landmark_types or ["attraction", "museum", "monument", "viewpoint"]
        type_filter = "|".join(types)
        query = (
            f'[out:json][timeout:30];'
            f'area["name"="{city_name}"]["boundary"="administrative"]->.a;'
            f'node["tourism"~"{type_filter}"](area.a);'
            f'out body;'
        )
        data = self._query(query, timeout=45.0)

        for element in data.get("elements", []):
            ent = self._element_to_entity(element, "landmark", ["tourism"])
            if ent:
                entities.append(ent)

        return entities
