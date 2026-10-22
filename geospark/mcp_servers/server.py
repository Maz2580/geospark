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
fires, location reports and site selection.
- Coordinates are GeoJSON order: [longitude, latitude], WGS84.
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
Latitude = Annotated[float, Field(ge=-90, le=90, description="Latitude in degrees (WGS84)")]
Longitude = Annotated[float, Field(ge=-180, le=180, description="Longitude in degrees (WGS84)")]

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


def create_server() -> MCPServer:
    """Build the GeoSpark MCP server with all tools registered."""
    mcp = MCPServer(
        "geospark",
        title="GeoSpark",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/Maz2580/geospark",
    )
    engine = Engine(tools=["geocoder", "reverse_geocoder", "terrain", "router"])

    @mcp.tool(title="Geodesic distance", annotations=READ_ONLY_LOCAL)
    async def calculate_distance(point_a: GeoJSONGeometry, point_b: GeoJSONGeometry) -> DistanceResult:
        """Exact geodesic distance between two geometries on the WGS84 ellipsoid.

        Use for any "how far" question instead of estimating. For lines and polygons the
        distance is between their nearest points. Returns metres and kilometres.
        """
        distance = await _blocking(SpatialReasoner.calculate_distance, point_a, point_b)
        checked = enrich(SpatialResult(features=[SpatialFeature(
            geometry=point_a, properties={"distance_m": distance, "distance_km": distance / 1000})]), "distance")
        return DistanceResult(distance_m=distance, distance_km=distance / 1000, **_checkable(checked))

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

    return mcp


def run() -> None:
    """Entry point for ``geospark-mcp``: serve over stdio."""
    create_server().run()


if __name__ == "__main__":
    run()
