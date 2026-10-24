"""GeoSpark MCP server (MCP SDK 2.x, protocol 2026-07-28; still negotiates older handshakes).

Every tool computes or fetches its answer and returns it as **structured content** with a
documented output schema: GeoJSON for places and shapes, plus the provenance (source, licence,
attribution, method), units and warnings that make the answer checkable. Bad input or an
unanswerable question comes back as a tool error (``isError``) that says why, never as a guess.

Run it over stdio (Claude Desktop, IDEs): ``geospark-mcp``. The REST app can also mount it as
Streamable HTTP at ``/mcp`` (see ``geospark.api``; off unless ``GEOSPARK_MCP_HTTP=true``).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from geospark import __version__
from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.protocol.provenance import engine_provenance, enrich
from geospark.protocol.schema import (
    Point,
    SpatialFeature,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)
from geospark.utils import concurrency

INSTRUCTIONS = """\
GeoSpark computes spatial answers instead of guessing them. Use it for distances, containment and
other topology, buffers and areas, geocoding, elevation, routing, weather, air quality, active
fires, location reports, site selection, and official datum and height conversions.
- For datum shifts (GDA94/GDA2020, OSGB36, NAD27/NAD83) and heights (AHD, ODN, NZVD2016, NAVD88),
  call transform_coordinates / convert_height: they use the national grids. Don't estimate them.
- Coordinates are GeoJSON order: [longitude, latitude], WGS84.
- For distances between named places, give calculate_distance the names (place_a, place_b): the
  server geocodes them. Never type coordinates for a place from memory.
- Every result carries provenance (source, licence, attribution) and units; cite the
  attribution when you present data from OpenStreetMap, Copernicus, Open-Meteo etc.
- Read `warnings` (e.g. an ambiguous place name) before answering.
- A tool error means GeoSpark could not answer reliably (invalid geometry, unknown place, a data
  source down): tell the user why instead of estimating.
"""

GeoJSONGeometry = Annotated[
    dict[str, Any],
    Field(description='A GeoJSON geometry, e.g. {"type": "Point", "coordinates": [lon, lat]}'),
]
OptionalGeometry = Annotated[
    dict[str, Any] | None,
    Field(description='A GeoJSON geometry, e.g. {"type": "Point", "coordinates": [lon, lat]}; only for '
                      "coordinates the user gave or a tool returned"),
]
PlaceName = Annotated[
    str | None,
    Field(max_length=500, description="A place NAME, e.g. 'Adelaide Oval'; geocoded on the server (preferred)"),
]
Latitude = Annotated[float, Field(ge=-90, le=90, description="Latitude in degrees (WGS84)")]
Longitude = Annotated[float, Field(ge=-180, le=180, description="Longitude in degrees (WGS84)")]

FilePath = Annotated[str, Field(min_length=1, max_length=1000,
                                description="Path to a GeoJSON/GeoPackage/Shapefile/GeoParquet/CSV file")]
CrsArg = Annotated[str | None, Field(description="The file's CRS if it doesn't declare one, e.g. EPSG:28355")]

READ_ONLY_LOCAL = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                                  open_world_hint=False)
READ_ONLY_WEB = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                                open_world_hint=True)


# --- Output schemas -----------------------------------------------------------------------


class Checkable(BaseModel):
    """What makes an answer verifiable."""

    status: Literal["ok", "partial", "cannot_answer"] = "ok"
    units: dict[str, str] = Field(default_factory=dict, description="Unit of each numeric field")
    warnings: list[str] = Field(default_factory=list, description="Caveats to tell the user")
    provenance: list[dict[str, Any]] = Field(
        default_factory=list, description="Source, licence, attribution, retrieval time and method"
    )


class DistanceResult(Checkable):
    distance_m: float = Field(description="Geodesic distance in metres (WGS84 ellipsoid)")
    distance_km: float
    places: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Named places as geocoded on the server: query, display_name, coordinates [lon, lat]",
    )


class RelationshipResult(Checkable):
    relationship: str
    holds: bool = Field(description="Whether geometry_a <relationship> geometry_b is true")


class ElevationResult(Checkable):
    latitude: float
    longitude: float
    elevation_m: float | None
    vertical_datum: str | None = None
    quality: dict[str, Any] = Field(default_factory=dict, description="e.g. vertical_accuracy_le90_m")
    attribution: str | None = None


class TransformResult(Checkable):
    coordinates: list[list[float]] = Field(description="Transformed points, in the target CRS's x/y(/z) order")
    source_crs: str
    target_crs: str
    method: str = Field(description="The EPSG operation used")
    accuracy_m: float | None = Field(description="The operation's stated accuracy; null for an exact conversion")
    grids: list[str] = Field(default_factory=list, description="Official grid files the operation used")
    area_of_use: str | None = None


class HeightResult(Checkable):
    height_m: float
    from_reference: str
    to_reference: str
    geoid_model: str
    separation_m: float = Field(description="Ellipsoidal height minus the datum height at this point")
    method: str
    accuracy_m: float | None
    grids: list[str] = Field(default_factory=list)


class FeatureCollection(BaseModel):
    """An RFC 7946 GeoJSON FeatureCollection; `geospark` holds status, units, warnings, provenance."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[dict[str, Any]]
    bbox: list[float] | None = None
    geospark: dict[str, Any] = Field(default_factory=dict)


class DataResult(Checkable):
    channel: str
    features: list[dict[str, Any]] = Field(description="Records from the data source")
    total_results: int = 0
    query: dict[str, Any] = Field(default_factory=dict)


# --- helpers ------------------------------------------------------------------------------------


def _checkable(result: SpatialResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "units": result.spatial_context.units,
        "warnings": result.warnings,
        "provenance": [p.model_dump(mode="json", exclude_none=True) for p in result.provenance],
    }


def _require_answer(result: SpatialResult) -> SpatialResult:
    """Turn 'cannot answer' into a tool error that tells the model why."""
    if result.status == "cannot_answer":
        raise ToolError("GeoSpark cannot answer this reliably: " + "; ".join(result.errors))
    return result


def _collection(result: SpatialResult) -> FeatureCollection:
    return FeatureCollection(**_require_answer(result).to_geojson())


async def _blocking(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run blocking work (network, geometry) off the event loop; ValueError -> tool error."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except ValueError as e:
        raise ToolError(str(e)) from e


async def _heavy(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Expensive work shares the server-wide concurrency cap with the REST API."""
    def guarded() -> Any:
        with concurrency.heavy_work_slot():
            return fn(*args, **kwargs)

    try:
        return await _blocking(guarded)
    except concurrency.ServerBusyError as e:
        raise ToolError(str(e)) from e


# --- the server -----------------------------------------------------------------------------------


def create_server(local_files: bool = False) -> MCPServer:
    """Build the GeoSpark MCP server with all tools registered.

    ``local_files=True`` adds tools that read files from this machine (your own layers). Only
    the stdio server (running on your computer) enables it; the hosted HTTP endpoint never does.
    """
    mcp = MCPServer(
        "geospark",
        title="GeoSpark",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/Maz2580/geospark",
    )
    engine = Engine(tools=["geocoder", "reverse_geocoder", "terrain", "router"])

    @mcp.tool(title="Geodesic distance", annotations=READ_ONLY_WEB)
    async def calculate_distance(
        place_a: PlaceName = None,
        place_b: PlaceName = None,
        point_a: OptionalGeometry = None,
        point_b: OptionalGeometry = None,
    ) -> DistanceResult:
        """Exact geodesic distance between two places or geometries on the WGS84 ellipsoid.

        Use for any "how far" question instead of estimating. For NAMED places pass place_a and
        place_b; the server geocodes them, so never type coordinates for a place yourself. Use
        point_a/point_b only for coordinates the user gave or another tool returned. For lines
        and polygons the distance is between their nearest points. Returns metres and kilometres.
        """
        geometries: dict[str, dict[str, Any]] = {}
        places: list[dict[str, Any]] = []
        lookups: list[SpatialResult] = []
        for side, name, geometry in (("a", place_a, point_a), ("b", place_b, point_b)):
            if name and name.strip():
                q = SpatialQuery(operation=SpatialOperation.GEOCODE, metadata={"query": name.strip()}, limit=1)
                found = _require_answer(await _blocking(engine.execute, q))
                if not found.features:
                    raise ToolError(f"No place found for '{name}'. Try a more specific name or add a country.")
                best = found.features[0]
                geom = best.geometry if isinstance(best.geometry, dict) else best.geometry.model_dump()
                geometries[side] = geom
                places.append({"query": name.strip(), "display_name": best.properties.get("display_name"),
                               "coordinates": geom.get("coordinates")})
                lookups.append(found)
            elif geometry is not None:
                geometries[side] = geometry
            else:
                raise ToolError(f"Give place_{side} (a place name) or point_{side} (a GeoJSON geometry).")
        distance = await _blocking(SpatialReasoner.calculate_distance, geometries["a"], geometries["b"])
        checked = enrich(SpatialResult(features=[SpatialFeature(
            geometry=geometries["a"], properties={"distance_m": distance, "distance_km": distance / 1000})]),
            "distance")
        for found in lookups:  # where the places came from, and any ambiguity, travel with the distance
            checked.provenance = [*found.provenance, *checked.provenance]
            checked.warnings.extend(w for w in found.warnings if w not in checked.warnings)
        unique: dict[tuple[str, str | None], Any] = {}
        for p in checked.provenance:  # one entry per source and method, however many lookups used it
            unique.setdefault((p.source, p.method), p)
        checked.provenance = list(unique.values())
        return DistanceResult(distance_m=distance, distance_km=distance / 1000, places=places, **_checkable(checked))

    @mcp.tool(title="Topological relationship", annotations=READ_ONLY_LOCAL)
    async def check_spatial_relationship(
        geometry_a: GeoJSONGeometry,
        geometry_b: GeoJSONGeometry,
        relationship: Literal["contains", "intersects", "within", "touches", "crosses", "overlaps", "disjoint"],
    ) -> RelationshipResult:
        """Ground-truth topology: does geometry_a <relationship> geometry_b?

        Use instead of guessing containment, overlap or adjacency. Invalid geometries (for
        example self-intersecting polygons) are refused with the reason.
        """
        holds = await _blocking(SpatialReasoner.check_relationship, geometry_a, geometry_b, relationship)
        checked = enrich(SpatialResult(), relationship, [geometry_a, geometry_b])
        return RelationshipResult(relationship=relationship, holds=holds, **_checkable(checked))

    @mcp.tool(title="Geometry operation", annotations=READ_ONLY_LOCAL)
    async def spatial_operation(
        operation: Literal["buffer", "area", "length", "centroid", "convex_hull"],
        geometry: GeoJSONGeometry,
        radius_m: Annotated[float | None, Field(ge=0, le=100_000, description="Buffer radius in metres")] = None,
    ) -> FeatureCollection:
        """Compute a buffer (shape-preserving, metres), geodesic area or length, centroid or convex hull.

        Returns the resulting geometry as GeoJSON with its measurements and units.
        """
        query = SpatialQuery(operation=SpatialOperation(operation), geometry=geometry, radius_m=radius_m)
        return _collection(await _blocking(engine.execute, query))

    @mcp.tool(title="Geocode a place", annotations=READ_ONLY_WEB)
    async def geocode(
        query: Annotated[str, Field(min_length=1, max_length=500, description="Address or place name")],
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> FeatureCollection:
        """Find coordinates for an address or place name (OpenStreetMap Nominatim).

        Check `geospark.warnings` for ambiguous names (e.g. "Springfield") and ask the user
        which one they mean, or add a region.
        """
        q = SpatialQuery(operation=SpatialOperation.GEOCODE, metadata={"query": query}, limit=limit)
        result = await _blocking(engine.execute, q)
        if result.status == "ok" and not result.features:
            raise ToolError(f"No place found for '{query}'. Try a more specific name or add a country.")
        return _collection(result)

    @mcp.tool(title="Reverse geocode", annotations=READ_ONLY_WEB)
    async def reverse_geocode(latitude: Latitude, longitude: Longitude) -> FeatureCollection:
        """Find the address or place at a coordinate (OpenStreetMap Nominatim)."""
        q = SpatialQuery(operation=SpatialOperation.REVERSE_GEOCODE, geometry=Point.from_latlon(latitude, longitude))
        return _collection(await _blocking(engine.execute, q))

    @mcp.tool(title="Elevation", annotations=READ_ONLY_WEB)
    async def get_elevation(latitude: Latitude, longitude: Longitude) -> ElevationResult:
        """Ground elevation in metres (Copernicus GLO-30, Open Elevation fallback), with its
        vertical datum and accuracy."""
        q = SpatialQuery(operation=SpatialOperation.ELEVATION, geometry=Point.from_latlon(latitude, longitude))
        result = _require_answer(await _blocking(engine.execute, q))
        props = result.features[0].properties if result.features else {}
        return ElevationResult(
            latitude=latitude, longitude=longitude, elevation_m=props.get("elevation_m"),
            vertical_datum=props.get("vertical_datum"), quality=result.quality,
            attribution=props.get("attribution"), **_checkable(result),
        )

    @mcp.tool(title="Driving route", annotations=READ_ONLY_WEB)
    async def route(
        from_latitude: Latitude, from_longitude: Longitude, to_latitude: Latitude, to_longitude: Longitude,
    ) -> FeatureCollection:
        """Driving route between two points (OSRM over OpenStreetMap): line geometry, distance
        in metres and duration in seconds."""
        q = SpatialQuery(operation=SpatialOperation.ROUTE, metadata={
            "origin": [from_longitude, from_latitude], "destination": [to_longitude, to_latitude]})
        return _collection(await _blocking(engine.execute, q))

    async def _channel(name: str, **kwargs: Any) -> DataResult:
        from geospark.data_channels.registry import ChannelRegistry

        try:
            result = await ChannelRegistry().search(name, **kwargs)
        except ValueError as e:
            raise ToolError(str(e)) from e
        if result.errors and not result.features:
            raise ToolError(f"{name} data unavailable: " + "; ".join(result.errors))
        status = "partial" if result.errors else "ok"
        return DataResult(
            channel=name, features=result.features, total_results=result.total_results, query=result.query,
            status=status, warnings=result.errors,
            provenance=[p.model_dump(mode="json", exclude_none=True) for p in result.provenance],
        )

    @mcp.tool(title="Weather", annotations=READ_ONLY_WEB)
    async def get_weather(
        latitude: Latitude, longitude: Longitude,
        forecast_days: Annotated[int, Field(ge=1, le=16)] = 3,
    ) -> DataResult:
        """Current weather and a daily forecast for a point (Open-Meteo, no key needed)."""
        return await _channel("weather", lat=latitude, lon=longitude, filters={"forecast_days": forecast_days})

    @mcp.tool(title="Air quality", annotations=READ_ONLY_WEB)
    async def get_air_quality(latitude: Latitude, longitude: Longitude) -> DataResult:
        """Latest PM2.5, NO2, O3 from the nearest monitoring stations (OpenAQ; the server needs
        an OPENAQ_API_KEY), with each station's data licence."""
        return await _channel("air-quality", lat=latitude, lon=longitude)

    @mcp.tool(title="Active fires", annotations=READ_ONLY_WEB)
    async def get_active_fires(
        latitude: Latitude, longitude: Longitude, days: Annotated[int, Field(ge=1, le=2)] = 1,
    ) -> DataResult:
        """Satellite active-fire detections near a point (NASA FIRMS; the server needs a FIRMS_MAP_KEY)."""
        return await _channel("fires", lat=latitude, lon=longitude, filters={"days": days})

    def _routing(fn: Any, *args: Any) -> Any:
        from geospark.tools.routing.valhalla import RoutingUnavailableError

        try:
            return fn(*args)
        except RoutingUnavailableError as e:
            raise ToolError(str(e)) from e

    @mcp.tool(title="Isochrone (reachable area)", annotations=READ_ONLY_WEB)
    async def isochrone(
        latitude: Latitude,
        longitude: Longitude,
        minutes: Annotated[list[int], Field(min_length=1, max_length=4, description="Contour times, 1-60")] = [10],  # noqa: B006
        mode: Literal["walk", "bike", "drive"] = "walk",
    ) -> FeatureCollection:
        """Where can you get to from a point within N minutes on foot, by bike or by car?
        Returns one polygon per contour with its geodesic area (Valhalla over OpenStreetMap)."""
        from geospark.tools.routing import valhalla

        return _collection(await _heavy(_routing, valhalla.isochrone, latitude, longitude, minutes, mode))

    @mcp.tool(title="Travel-time matrix", annotations=READ_ONLY_WEB)
    async def travel_time_matrix(
        origins: Annotated[list[tuple[float, float]], Field(min_length=1, max_length=5, description="[[lat, lon], ...]")],
        destinations: Annotated[list[tuple[float, float]], Field(min_length=1, max_length=5, description="[[lat, lon], ...]")],
        mode: Literal["walk", "bike", "drive"] = "walk",
    ) -> FeatureCollection:
        """Network travel time (minutes) and distance (metres) from each origin to each destination.
        Note: points here are [latitude, longitude] pairs."""
        from geospark.tools.routing import valhalla

        return _collection(await _heavy(_routing, valhalla.travel_time_matrix, origins, destinations, mode))

    @mcp.tool(title="Overture Maps features", annotations=READ_ONLY_WEB)
    async def overture_features(
        theme: Literal["places", "buildings", "transportation", "divisions"],
        latitude: Latitude,
        longitude: Longitude,
        radius_m: Annotated[float, Field(gt=0, le=2000, description="Search radius in metres")] = 300,
        category: Annotated[str | None, Field(max_length=100, description="Places only, e.g. 'cafe'")] = None,
        limit: Annotated[int | None, Field(ge=1, le=2000)] = None,
    ) -> FeatureCollection:
        """Open global map data from Overture Maps, no API key: points of interest (with
        categories), building footprints (height, floors, geodesic footprint area), road and path
        segments (geodesic length), or `divisions`, the administrative areas containing the point
        (country, region, city, neighbourhood). Results are nearest first, with distances in metres.
        Can take 5-20 s on a cold cache."""
        from geospark.tools.overture.client import OvertureError
        from geospark.tools.overture.client import query as overture_query

        try:
            result = await _heavy(overture_query, theme, latitude, longitude, radius_m=radius_m,
                                  category=category, limit=limit)
        except OvertureError as e:
            raise ToolError(str(e)) from e
        return _collection(result)

    @mcp.tool(title="Transform coordinates (official datums)", annotations=READ_ONLY_WEB)
    async def transform_coordinates(
        source_crs: Annotated[str, Field(max_length=100, description="CRS name or EPSG code, e.g. 'GDA94 / MGA zone 55' or EPSG:28355")],
        target_crs: Annotated[str, Field(max_length=100, description="CRS name or EPSG code, e.g. 'GDA2020 / MGA zone 55' or EPSG:7855")],
        coordinates: Annotated[list[list[float]], Field(min_length=1, max_length=1000,
                                                        description="[x, y] or [x, y, z]: [lon, lat] or [easting, northing]")],
        epoch: Annotated[float | None, Field(ge=1900, le=2100, description="Decimal year, for ITRF/ATRF frames")] = None,
    ) -> TransformResult:
        """Convert coordinates between CRSs as the official transformation does: GDA94 to GDA2020,
        MGA zones, British National Grid (OSTN15), NAD27 to NAD83 (NADCON), ITRF at an epoch, and
        any other EPSG pair. Uses national grids (downloaded once), refuses PROJ's ballpark
        approximations, and returns the operation and its stated accuracy. Use this instead of
        applying datum parameters yourself."""
        from geospark import geodesy

        try:
            done = await _blocking(geodesy.transform, source_crs, target_crs, coordinates, epoch)
        except geodesy.GeodesyError as e:
            raise ToolError(str(e)) from e
        out = done.as_dict()
        return TransformResult(
            coordinates=out["coordinates"], source_crs=out["source_crs"], target_crs=out["target_crs"],
            method=out["method"], accuracy_m=out["accuracy_m"], grids=out["grids"], area_of_use=out["area_of_use"],
            warnings=out["warnings"], provenance=out["provenance"],
            units={"coordinates": "degrees or metres, as the target CRS defines"},
        )

    @mcp.tool(title="Convert height (geoid models)", annotations=READ_ONLY_WEB)
    async def convert_height(
        latitude: Latitude,
        longitude: Longitude,
        height_m: Annotated[float, Field(ge=-1000, le=10_000, description="The height to convert, in metres")],
        from_reference: Annotated[str, Field(description="'ellipsoidal', AHD, ODN, NZVD2016, NAVD88 or EGM2008")],
        to_reference: Annotated[str, Field(description="'ellipsoidal', AHD, ODN, NZVD2016, NAVD88 or EGM2008")],
    ) -> HeightResult:
        """Convert a height between the ellipsoid (GNSS, drones) and a national height datum with the
        official geoid model: AHD (AUSGeoid2020), ODN (OSGM15), NZVD2016 (NZGeoid2016), NAVD88
        (GEOID18), or global EGM2008. Never estimate a geoid separation from memory: it is often
        tens of metres and varies by metres across a region."""
        from geospark import geodesy

        try:
            out = await _blocking(geodesy.convert_height, latitude, longitude, height_m, from_reference, to_reference)
        except geodesy.GeodesyError as e:
            raise ToolError(str(e)) from e
        return HeightResult(
            height_m=out["height_m"], from_reference=out["from"], to_reference=out["to"], geoid_model=out["geoid_model"],
            separation_m=out["separation_m"], method=out["method"], accuracy_m=out["accuracy_m"], grids=out["grids"],
            warnings=out["warnings"], provenance=out["provenance"], units={"height_m": "metre", "separation_m": "metre"},
        )

    @mcp.tool(title="Location report", annotations=READ_ONLY_WEB)
    async def location_report(
        location: Annotated[str, Field(min_length=1, max_length=500, description="Place to analyse")],
        radius_m: Annotated[float, Field(gt=0, le=10_000)] = 1000,
    ) -> FeatureCollection:
        """A dossier for a place: address, elevation, weather, and nearby amenities with exact
        distances, as a GeoJSON map layer listing every data source used. Takes ~10-30 s."""
        from geospark.agents import SpatialReport

        report = await _heavy(SpatialReport(engine=engine).analyze, location, radius_m=radius_m)
        if not report.coordinates:
            raise ToolError(report.summary or f"Could not find '{location}'.")
        return FeatureCollection(**report.to_geojson())

    @mcp.tool(title="Site selection", annotations=READ_ONLY_WEB)
    async def select_site(
        within: Annotated[str, Field(min_length=1, max_length=500, description="City or neighbourhood")],
        near: Annotated[list[str], Field(max_length=10, description="Amenity types to be close to")] = [],  # noqa: B006
        avoid: Annotated[list[str], Field(max_length=10, description="Amenity types to stay away from")] = [],  # noqa: B006
        facility_type: Annotated[str, Field(max_length=100)] = "restaurant",
        radius_m: Annotated[float, Field(gt=0, le=10_000)] = 3000,
    ) -> FeatureCollection:
        """Rank candidate sites in an area by geodesic distance to amenities you want nearby and
        away from ones to avoid (OpenStreetMap data). Takes ~10-30 s."""
        from geospark.agents import SiteSelector

        result = await _heavy(SiteSelector(engine=engine).find, within=within, near=near, avoid=avoid,
                              facility_type=facility_type, radius_m=radius_m)
        if not result.candidates:
            raise ToolError(result.summary or "No candidate sites found.")
        features = [SpatialFeature(geometry={"type": "Point", "coordinates": c.coordinates[:2]},
                                   properties={"rank": i + 1, "name": c.name, "score": c.score, **c.details})
                    for i, c in enumerate(result.candidates) if len(c.coordinates) >= 2]
        spatial = enrich(SpatialResult(features=features, sources=["openstreetmap-nominatim", "openstreetmap-overpass"]))
        spatial.provenance.append(engine_provenance("distance"))
        spatial.spatial_context.summary = result.summary
        return FeatureCollection(**spatial.to_geojson())

    if local_files:
        _add_local_file_tools(mcp)
    return mcp


def _add_local_file_tools(mcp: MCPServer) -> None:
    """Tools that read the user's own files. stdio (local) only."""
    from geospark.io import layers

    def load(path: str, crs: str | None, repair: bool) -> Any:
        try:
            return layers.load_layer(path, crs=crs, repair=repair)
        except layers.LayerError as e:
            raise ToolError(str(e)) from e

    @mcp.tool(title="Describe a local data file", annotations=READ_ONLY_LOCAL)
    async def layer_info(path: FilePath, crs: CrsArg = None, repair: bool = False) -> FeatureCollection:
        """Read one of the user's vector files and report features, fields, geometry types, its CRS
        (never guessed), bbox and total geodesic area/length."""
        layer = await _blocking(load, path, crs, repair)
        return FeatureCollection(**layer.summary().to_geojson())

    @mcp.tool(title="Count points in polygons (local files)", annotations=READ_ONLY_LOCAL)
    async def layer_count_within(points_path: FilePath, polygons_path: FilePath, crs: CrsArg = None,
                                 repair: bool = False) -> FeatureCollection:
        """For each polygon in one file, count the points from another file inside it (exact), with
        density per km²."""
        pts = await _blocking(load, points_path, crs, repair)
        polys = await _blocking(load, polygons_path, crs, repair)
        return FeatureCollection(**(await _blocking(layers.count_within, pts, polys)).to_geojson())

    @mcp.tool(title="Check a data file's coordinates (local files)", annotations=READ_ONLY_LOCAL)
    async def check_dataset(path: FilePath, crs: CrsArg = None,
                            against_path: Annotated[str | None, Field(description="A reference file of the same "
                                                                      "features to compare against")] = None,
                            against_crs: CrsArg = None,
                            id_field: Annotated[str | None, Field(description="Field identifying the same feature "
                                                                  "in both files")] = None) -> dict[str, Any]:
        """Check one of the user's files before analysis: is a CRS declared, do the coordinates fit it
        (projected numbers labelled as degrees, swapped lat/lon, points outside the zone), datum and
        height-reference caveats. With against_path, measure the offset to a reference layer and name
        the cause when the numbers match one: GDA94 data labelled GDA2020, the wrong MGA zone, feet,
        a plate-motion epoch, or ellipsoidal vs AHD heights. Says 'unexplained' rather than guessing."""
        from geospark.io.check import check_layer, compare_layers

        if against_path:
            return await _blocking(compare_layers, against_path, path, against_crs, crs, id_field)
        return await _blocking(check_layer, path, None, crs)

    @mcp.tool(title="Nearest feature (local files)", annotations=READ_ONLY_LOCAL)
    async def layer_nearest(sources_path: FilePath, targets_path: FilePath, crs: CrsArg = None,
                            repair: bool = False) -> FeatureCollection:
        """For each feature in one file, the nearest feature in another and the geodesic distance."""
        src = await _blocking(load, sources_path, crs, repair)
        dst = await _blocking(load, targets_path, crs, repair)
        return FeatureCollection(**(await _blocking(layers.nearest, src, dst)).to_geojson())


def run() -> None:
    """Entry point for ``geospark-mcp``: serve over stdio, with local-file tools."""
    create_server(local_files=True).run()


if __name__ == "__main__":
    run()
