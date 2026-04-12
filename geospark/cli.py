"""
GeoSpark CLI.

Command-line interface for GeoSpark operations.
"""

from __future__ import annotations

import json

import click
from rich.console import Console
from rich.table import Table

from geospark import __version__

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="geospark")
def main() -> None:
    """GeoSpark: The Open-Source Geospatial Intelligence Engine."""
    pass


@main.command()
@click.argument("query_json")
def query(query_json: str) -> None:
    """Execute a GSP spatial query (JSON string)."""
    from geospark import Engine
    from geospark.protocol.schema import SpatialQuery

    try:
        query_dict = json.loads(query_json)
        spatial_query = SpatialQuery(**query_dict)
        engine = Engine()
        result = engine.execute(spatial_query)

        console.print_json(result.model_dump_json(indent=2))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@main.command()
@click.argument("address")
def geocode(address: str) -> None:
    """Geocode an address to coordinates."""
    from geospark import Engine
    from geospark.protocol.schema import SpatialOperation, SpatialQuery

    engine = Engine(tools=["geocoder"])
    q = SpatialQuery(
        operation=SpatialOperation.GEOCODE,
        metadata={"query": address},
    )
    result = engine.execute(q)

    if result.features:
        table = Table(title=f"Geocoding results for: {address}")
        table.add_column("Name", style="cyan")
        table.add_column("Coordinates", style="green")
        table.add_column("Type", style="yellow")

        for f in result.features:
            coords = f.geometry.get("coordinates", [])
            name = f.properties.get("display_name", "Unknown")
            ftype = f.properties.get("type", "")
            coord_str = f"({coords[1]:.6f}, {coords[0]:.6f})" if len(coords) >= 2 else str(coords)
            table.add_row(name[:80], coord_str, ftype)

        console.print(table)
    else:
        console.print("[yellow]No results found[/yellow]")


@main.command()
@click.argument("lat", type=float)
@click.argument("lon", type=float)
def elevation(lat: float, lon: float) -> None:
    """Get elevation at a coordinate (lat lon)."""
    from geospark import Engine
    from geospark.protocol.schema import Point, SpatialOperation, SpatialQuery

    engine = Engine(tools=["terrain"])
    q = SpatialQuery(
        operation=SpatialOperation.ELEVATION,
        geometry=Point.from_latlon(lat, lon),
    )
    result = engine.execute(q)

    if result.features:
        elev = result.features[0].properties.get("elevation_m", "N/A")
        console.print(f"Elevation at ({lat}, {lon}): [bold green]{elev}m[/bold green]")
    elif result.errors:
        console.print(f"[red]Error:[/red] {result.errors[0]}")


@main.command()
@click.argument("coords", nargs=4, type=float)
def distance(coords: tuple[float, ...]) -> None:
    """Calculate geodesic distance: geospark distance LAT_A LON_A LAT_B LON_B."""
    lat_a, lon_a, lat_b, lon_b = coords
    from geospark.engine.spatial_reasoner import SpatialReasoner

    geom_a = {"type": "Point", "coordinates": [lon_a, lat_a]}
    geom_b = {"type": "Point", "coordinates": [lon_b, lat_b]}
    d = SpatialReasoner.calculate_distance(geom_a, geom_b)

    table = Table(title="Geodesic Distance")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("From", f"({lat_a}, {lon_a})")
    table.add_row("To", f"({lat_b}, {lon_b})")
    table.add_row("Distance (m)", f"{d:,.2f}")
    table.add_row("Distance (km)", f"{d / 1000:,.3f}")
    console.print(table)


@main.command()
@click.argument("relationship", type=click.Choice([
    "contains", "within", "intersects", "touches", "crosses", "overlaps", "disjoint",
]))
@click.argument("geojson_a")
@click.argument("geojson_b")
def check(relationship: str, geojson_a: str, geojson_b: str) -> None:
    """Check spatial relationship between two GeoJSON geometries."""
    from geospark.engine.spatial_reasoner import SpatialReasoner

    try:
        a = json.loads(geojson_a)
        b = json.loads(geojson_b)
        result = SpatialReasoner.check_relationship(a, b, relationship)
        color = "green" if result else "red"
        console.print(f"{relationship}: [{color}]{result}[/{color}]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@main.command()
@click.argument("question")
@click.option("--provider", type=click.Choice(["auto", "ollama", "openrouter"]), default="auto")
@click.option("--model", default=None, help="Override LLM model")
def ask(question: str, provider: str, model: str | None) -> None:
    """Ask a natural language spatial question."""
    from geospark import Engine

    engine = Engine(tools=["geocoder", "terrain"])
    prov = None if provider == "auto" else provider
    result = engine.ask(question, model=model, provider=prov)

    if result.errors:
        console.print(f"[red]Error:[/red] {result.errors[0]}")
        return

    console.print(f"\n[bold]{result.spatial_context.summary}[/bold]\n")
    if result.metadata:
        source = result.metadata.get("source", "unknown")
        used = result.metadata.get("tools_used", [])
        if used:
            console.print(f"[dim]Tools used: {', '.join(used)} | Source: {source}[/dim]")


@main.command()
def tools() -> None:
    """List available tools."""
    from geospark.tools.registry import TOOL_CLASSES

    table = Table(title="Available GeoSpark Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Module", style="dim")

    for name, path in TOOL_CLASSES.items():
        table.add_row(name, path)

    console.print(table)


@main.command()
def info() -> None:
    """Show GeoSpark system information."""
    import geospark

    table = Table(title="GeoSpark System Info")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Version", geospark.__version__)
    table.add_row("Protocol", "GSP v0.1")

    # Check optional dependencies
    deps = {
        "shapely": "shapely",
        "pyproj": "pyproj",
        "geopandas": "geopandas",
        "rasterio": "rasterio",
        "h3": "h3",
        "duckdb": "duckdb",
        "pystac_client": "pystac-client",
        "fastapi": "fastapi",
    }

    for module_name, display_name in deps.items():
        try:
            mod = __import__(module_name)
            version = getattr(mod, "__version__", "installed")
            table.add_row(display_name, f"v{version}")
        except ImportError:
            table.add_row(display_name, "[dim]not installed[/dim]")

    console.print(table)


@main.group()
def flow() -> None:
    """Manage GeoSpark flows."""


@flow.command("list")
def flow_list() -> None:
    """List available flow templates."""
    from geospark.flows import list_templates

    templates = list_templates()
    table = Table(title="Flow Templates")
    table.add_column("Template", style="cyan")
    for t in templates:
        table.add_row(t)
    console.print(table)


@flow.command("run")
@click.argument("template_name")
@click.option("--params", default=None, help="JSON overrides for template parameters")
def flow_run(template_name: str, params: str | None) -> None:
    """Run a flow template by name."""
    from geospark import Engine
    from geospark.flows import FlowRunner, get_template

    overrides = json.loads(params) if params else {}
    try:
        f = get_template(template_name, **overrides)
    except KeyError:
        console.print(f"[red]Unknown template: {template_name}[/red]")
        return

    engine = Engine(tools=["geocoder", "terrain"])
    runner = FlowRunner(engine=engine)
    console.print(f"Running flow: [bold]{f.name}[/bold] ({len(f.steps)} steps)")

    run = runner.run(f)

    table = Table(title=f"Flow Run: {run.status}")
    table.add_column("Step", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Result")

    for step in f.steps:
        result = run.step_results.get(step.id, {})
        status = "done" if step.id in run.step_results else "skipped"
        summary = str(result.get("summary", result.get("features", "")))[:60]
        table.add_row(step.name, status, summary)

    console.print(table)

    if run.errors:
        for err in run.errors:
            console.print(f"[red]Error: {err}[/red]")


@flow.command("info")
@click.argument("template_name")
def flow_info(template_name: str) -> None:
    """Show details of a flow template."""
    from geospark.flows import get_template

    try:
        f = get_template(template_name)
    except KeyError:
        console.print(f"[red]Unknown template: {template_name}[/red]")
        return

    console.print(f"[bold]{f.name}[/bold]")
    console.print(f"{f.description}\n")

    table = Table(title="Steps")
    table.add_column("#", style="dim")
    table.add_column("Step", style="cyan")
    table.add_column("Operation", style="green")
    table.add_column("Depends On", style="yellow")

    for i, step in enumerate(f.steps, 1):
        deps = ", ".join(step.depends_on) if step.depends_on else "-"
        table.add_row(str(i), step.name, step.operation, deps)

    console.print(table)


@flow.command("saved")
def flow_saved() -> None:
    """List saved flows (requires Supabase persistence)."""
    from geospark.flows.persistence import get_flow_store

    store = get_flow_store()
    if store is None:
        console.print("[yellow]Flow persistence not configured. Set GEOSPARK_FLOW_BACKEND=supabase[/yellow]")
        return

    flows = store.list_flows()
    if not flows:
        console.print("[dim]No saved flows[/dim]")
        return

    table = Table(title=f"Saved Flows ({len(flows)})")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Name", style="cyan")
    table.add_column("Steps", style="green")
    table.add_column("Trigger")

    for f in flows:
        table.add_row(f.id[:12], f.name, str(len(f.steps)), f.trigger.trigger_type)

    console.print(table)


@flow.command("get")
@click.argument("flow_id")
def flow_get(flow_id: str) -> None:
    """Get a saved flow by ID."""
    from geospark.flows.persistence import get_flow_store

    store = get_flow_store()
    if store is None:
        console.print("[yellow]Flow persistence not configured[/yellow]")
        return

    f = store.get_flow(flow_id)
    if f is None:
        console.print(f"[red]Flow not found: {flow_id}[/red]")
        return

    console.print(f"[bold]{f.name}[/bold]")
    console.print(f"{f.description}\n")

    table = Table(title="Steps")
    table.add_column("#", style="dim")
    table.add_column("Step", style="cyan")
    table.add_column("Operation", style="green")

    for i, step in enumerate(f.steps, 1):
        table.add_row(str(i), step.name, step.operation or "-")

    console.print(table)


@flow.command("delete")
@click.argument("flow_id")
def flow_delete(flow_id: str) -> None:
    """Delete a saved flow."""
    from geospark.flows.persistence import get_flow_store

    store = get_flow_store()
    if store is None:
        console.print("[yellow]Flow persistence not configured[/yellow]")
        return

    deleted = store.delete_flow(flow_id)
    if deleted:
        console.print(f"[green]Deleted flow: {flow_id}[/green]")
    else:
        console.print(f"[red]Flow not found: {flow_id}[/red]")


@flow.command("runs")
@click.argument("flow_id")
def flow_runs(flow_id: str) -> None:
    """List runs for a saved flow."""
    from geospark.flows.persistence import get_flow_store

    store = get_flow_store()
    if store is None:
        console.print("[yellow]Flow persistence not configured[/yellow]")
        return

    runs = store.list_runs(flow_id=flow_id)
    if not runs:
        console.print("[dim]No runs found[/dim]")
        return

    table = Table(title=f"Runs ({len(runs)})")
    table.add_column("Run ID", style="dim", max_width=12)
    table.add_column("Status", style="green")
    table.add_column("Steps")
    table.add_column("Started")

    for r in runs:
        started = r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "-"
        table.add_row(r.id[:12], r.status, str(len(r.step_results)), started)

    console.print(table)


@main.command()
@click.argument("goal")
def agent(goal: str) -> None:
    """Run the autonomous spatial agent with a goal."""
    from geospark.agents import GeoAgent

    ag = GeoAgent()
    console.print(f"[bold]GeoAgent[/bold]: {goal}\n")
    result = ag.run(goal)

    for step in result.steps:
        icon = "[green]done[/green]" if not step.error else f"[red]{step.error[:40]}[/red]"
        console.print(f"  {step.action}: {step.description} [{icon}]")

    console.print(f"\n[bold]Summary[/bold]: {result.summary}")
    console.print(f"[dim]({result.total_duration_s}s, {len(result.steps)} steps)[/dim]")


@main.command()
@click.argument("location")
@click.option("--radius", default=2000, help="Search radius in meters")
def report(location: str, radius: int) -> None:
    """Generate a spatial intelligence report for a location."""
    from geospark.agents import SpatialReport

    reporter = SpatialReport()
    console.print(f"[bold]Analyzing[/bold]: {location}\n")
    rep = reporter.analyze(location, radius_m=radius)

    table = Table(title=f"Spatial Report: {location}")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Address", rep.address[:80] if rep.address else "N/A")
    table.add_row("Coordinates", str(rep.coordinates))
    table.add_row("Elevation", f"{rep.elevation_m}m" if rep.elevation_m else "N/A")
    table.add_row("Nearby amenities", str(len(rep.nearby)))

    console.print(table)

    if rep.accessibility:
        acc_table = Table(title="Accessibility")
        acc_table.add_column("Service", style="cyan")
        acc_table.add_column("Nearest", style="green")
        acc_table.add_column("Distance")
        for a in rep.accessibility:
            if a.available:
                acc_table.add_row(a.service, a.nearest_name[:40], f"{a.distance_m}m")
            else:
                acc_table.add_row(a.service, "[dim]none found[/dim]", "-")
        console.print(acc_table)

    console.print(f"\n[bold]Summary[/bold]: {rep.summary}")
    console.print(f"[dim]({rep.duration_s}s)[/dim]")


@main.command("site-select")
@click.option("--within", required=True, help="Search area (city/neighborhood)")
@click.option("--near", default=None, help="Comma-separated amenity types to be near")
@click.option("--avoid", default=None, help="Comma-separated amenity types to avoid")
@click.option("--facility", default="restaurant", help="Facility type to place")
@click.option("--radius", default=5000, help="Search radius in meters")
def site_select(within: str, near: str | None, avoid: str | None, facility: str, radius: int) -> None:
    """Find optimal locations based on spatial criteria."""
    from geospark.agents import SiteSelector

    near_list = [x.strip() for x in near.split(",")] if near else []
    avoid_list = [x.strip() for x in avoid.split(",")] if avoid else []

    selector = SiteSelector()
    console.print(f"[bold]Site Selection[/bold]: {facility} in {within}\n")
    result = selector.find(
        within=within,
        near=near_list,
        avoid=avoid_list,
        facility_type=facility,
        radius_m=radius,
    )

    if result.candidates:
        table = Table(title=f"Top Candidates ({len(result.candidates)} found)")
        table.add_column("#", style="dim")
        table.add_column("Location", style="cyan")
        table.add_column("Score", style="green")
        table.add_column("Details")

        for i, c in enumerate(result.candidates[:10], 1):
            details = ", ".join(f"{k}: {v}m" for k, v in c.details.items() if k.startswith("nearest"))
            table.add_row(str(i), c.name[:50], f"{c.score:.2f}", details[:60])
        console.print(table)

    console.print(f"\n[bold]Summary[/bold]: {result.summary}")
    console.print(f"[dim]({result.duration_s}s)[/dim]")


@main.group()
def data() -> None:
    """Access live geospatial data channels."""


@data.command("list")
def data_list() -> None:
    """List available data channels."""
    from geospark.data_channels import ChannelRegistry

    registry = ChannelRegistry()
    channels = registry.load_all()

    table = Table(title="Data Channels")
    table.add_column("Name", style="cyan")
    table.add_column("Tier", style="green")
    table.add_column("Description")

    for ch in channels:
        tier_label = {0: "Free", 1: "Free+Key", 2: "Commercial"}.get(ch.tier, "?")
        table.add_row(ch.name, tier_label, ch.description[:60])

    console.print(table)


@data.command("status")
def data_status() -> None:
    """Check health of all data channels."""
    from geospark.data_channels import ChannelRegistry

    registry = ChannelRegistry()
    statuses = registry.check_all()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Message")

    for s in statuses:
        color = {"ok": "green", "warn": "yellow", "error": "red"}.get(s.status, "dim")
        table.add_row(s.name, f"[{color}]{s.status}[/{color}]", s.message)

    console.print(table)


@data.command("weather")
@click.argument("location")
@click.option("--forecast", default=3, help="Forecast days (1-16)")
def data_weather(location: str, forecast: int) -> None:
    """Get weather data for a location."""
    import asyncio

    from geospark.data_channels.weather import WeatherChannel

    async def _run():
        ch = WeatherChannel()
        return await ch.search(location=location, filters={"forecast_days": forecast})

    result = asyncio.run(_run())

    if result.errors:
        console.print(f"[red]Error: {result.errors[0]}[/red]")
        return

    # Current conditions
    current = next((f for f in result.features if f.get("type") == "current_weather"), None)
    if current:
        table = Table(title=f"Current Weather: {current.get('location', location)}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Temperature", f"{current.get('temperature_c')}°C")
        table.add_row("Feels Like", f"{current.get('feels_like_c')}°C")
        table.add_row("Humidity", f"{current.get('humidity_pct')}%")
        table.add_row("Wind", f"{current.get('wind_speed_kmh')} km/h")
        table.add_row("Conditions", current.get("weather_description", ""))
        table.add_row("Precipitation", f"{current.get('precipitation_mm')} mm")

        console.print(table)

    # Forecast
    forecasts = [f for f in result.features if f.get("type") == "daily_forecast"]
    if forecasts:
        ftable = Table(title=f"Forecast ({len(forecasts)} days)")
        ftable.add_column("Date", style="cyan")
        ftable.add_column("High", style="red")
        ftable.add_column("Low", style="blue")
        ftable.add_column("Rain", style="green")
        ftable.add_column("Wind", style="yellow")

        for f in forecasts:
            ftable.add_row(
                f.get("date", ""),
                f"{f.get('temp_max_c')}°C",
                f"{f.get('temp_min_c')}°C",
                f"{f.get('precipitation_mm')} mm",
                f"{f.get('wind_max_kmh')} km/h",
            )

        console.print(ftable)


@data.command("air-quality")
@click.argument("location")
@click.option("--radius", default=25000, help="Search radius in meters")
def data_air_quality(location: str, radius: int) -> None:
    """Get air quality data for a location."""
    import asyncio

    from geospark.data_channels.air_quality import AirQualityChannel

    async def _run():
        ch = AirQualityChannel()
        return await ch.search(location=location, filters={"radius_m": radius})

    result = asyncio.run(_run())

    if result.errors:
        console.print(f"[red]Error: {result.errors[0]}[/red]")
        return

    if result.is_empty:
        console.print(f"[yellow]No air quality stations found near {location}[/yellow]")
        return

    table = Table(title=f"Air Quality: {location}")
    table.add_column("Station", style="cyan")
    table.add_column("PM2.5")
    table.add_column("NO2")
    table.add_column("O3")
    table.add_column("AQI Category", style="green")
    table.add_column("Distance")

    for f in result.features[:10]:
        m = f.get("measurements", {})
        pm25 = m.get("pm25", {}).get("value", "-")
        no2 = m.get("no2", {}).get("value", "-")
        o3 = m.get("o3", {}).get("value", "-")
        aqi = f.get("aqi_category", "-") or "-"
        dist = f"{f.get('distance_m', 0):.0f}m" if f.get("distance_m") else "-"
        table.add_row(f.get("station_name", "?")[:30], str(pm25), str(no2), str(o3), aqi, dist)

    console.print(table)


@data.command("fires")
@click.argument("location")
@click.option("--days", default=1, help="Lookback days (1-2)")
def data_fires(location: str, days: int) -> None:
    """Check for active fires near a location."""
    import asyncio

    from geospark.data_channels.fires import FiresChannel

    async def _run():
        ch = FiresChannel()
        return await ch.search(location=location, filters={"days": days})

    result = asyncio.run(_run())

    if result.errors:
        console.print(f"[red]Error: {result.errors[0]}[/red]")
        return

    if result.is_empty:
        console.print(f"[green]No active fires detected near {location} (last {days} day(s))[/green]")
        return

    table = Table(title=f"Active Fires: {location} (last {days} day(s))")
    table.add_column("Date", style="cyan")
    table.add_column("Time")
    table.add_column("Lat")
    table.add_column("Lon")
    table.add_column("Confidence", style="green")
    table.add_column("FRP")
    table.add_column("Satellite")

    for f in result.features[:20]:
        coords = f.get("coordinates", [0, 0])
        table.add_row(
            f.get("acq_date", ""),
            f.get("acq_time", ""),
            f"{coords[1]:.4f}",
            f"{coords[0]:.4f}",
            f"{f.get('confidence', '')}",
            str(f.get("frp", "-")),
            f.get("satellite", ""),
        )

    console.print(table)
    console.print(f"[dim]Total fires: {result.total_results}[/dim]")


@main.group()
def memory() -> None:
    """Spatial intelligence memory — facts, episodes, contradictions."""


@memory.command("recall")
@click.argument("query")
@click.option("--type", "mem_type", type=click.Choice(["fact", "episode"]), default=None)
@click.option("--limit", default=10, help="Max results")
def memory_recall(query: str, mem_type: str | None, limit: int) -> None:
    """Recall spatial memories matching a query."""
    from geospark.memory.intelligence import SpatialIntelligence

    intel = SpatialIntelligence()
    results = intel.recall(query, limit=limit, memory_type=mem_type)

    if not results:
        console.print("[dim]No memories found[/dim]")
        return

    table = Table(title=f"Memory Recall: {query}")
    table.add_column("Type", style="cyan", max_width=8)
    table.add_column("Content", style="green")
    table.add_column("Score", style="yellow", max_width=8)
    table.add_column("Source", style="dim", max_width=15)

    for r in results:
        table.add_row(r["type"], r["content"][:80], str(r["score"]), r.get("source", "")[:15])

    console.print(table)


@memory.command("contradictions")
def memory_contradictions() -> None:
    """Find contradicting spatial facts."""
    from geospark.memory.intelligence import SpatialIntelligence

    intel = SpatialIntelligence()
    contradictions = intel.find_contradictions()

    if not contradictions:
        console.print("[green]No contradictions found[/green]")
        return

    table = Table(title=f"Contradictions ({len(contradictions)})")
    table.add_column("Fact A", style="cyan")
    table.add_column("Fact B", style="yellow")
    table.add_column("Similarity", style="red")

    for c in contradictions:
        table.add_row(c.fact_a_content[:50], c.fact_b_content[:50], f"{c.similarity:.2f}")

    console.print(table)


@memory.command("stats")
def memory_stats() -> None:
    """Show spatial intelligence statistics."""
    from geospark.memory.intelligence import SpatialIntelligence

    intel = SpatialIntelligence()
    s = intel.stats()

    table = Table(title="Spatial Intelligence")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Active Facts", str(s.active_facts))
    table.add_row("Total Facts", str(s.total_facts))
    table.add_row("Active Episodes", str(s.active_episodes))
    table.add_row("Total Episodes", str(s.total_episodes))
    table.add_row("Connections", str(s.total_connections))
    table.add_row("Contradictions", str(s.contradictions_found))
    table.add_row("Vector Store", str(s.vector_store_count))
    if s.faiss_available:
        backend = "yes (active)" if s.using_faiss else "yes (available, idle)"
    else:
        backend = "no (numpy fallback)"
    table.add_row("FAISS", backend)

    console.print(table)


@memory.command("compact")
@click.option("--max-age", default=30, help="Max age in days for episodes")
@click.option("--importance", default=0.7, help="Keep episodes above this importance")
def memory_compact(max_age: int, importance: float) -> None:
    """Compact old low-importance episodes."""
    from geospark.memory.intelligence import SpatialIntelligence

    intel = SpatialIntelligence()
    result = intel.compact(max_age_days=max_age, keep_important=importance)

    console.print(f"[green]Compacted {result['compacted']} episodes[/green]")
    console.print(f"[dim]Kept {result['kept']} episodes, {result['facts_preserved']} facts preserved[/dim]")


@main.group()
def context() -> None:
    """Geospatial context database -- missions, datasets, analysis history."""


@context.command("list")
@click.option("--category", default=None, help="Filter by category")
@click.option("--archived", is_flag=True, help="Include archived contexts")
def context_list(category: str | None, archived: bool) -> None:
    """List stored contexts."""
    from geospark.context import ContextStore

    store = ContextStore()
    contexts = store.list_all(category=category, include_archived=archived)

    if not contexts:
        console.print("[dim]No contexts stored[/dim]")
        return

    table = Table(title=f"Contexts ({len(contexts)})")
    table.add_column("URI", style="cyan", max_width=50)
    table.add_column("Name", style="green")
    table.add_column("Category", style="yellow", max_width=12)
    table.add_column("Accesses", max_width=8)
    table.add_column("Archived", max_width=8)

    for ctx in contexts:
        table.add_row(
            ctx.uri[:50],
            ctx.name[:30],
            ctx.category,
            str(ctx.access_count),
            "yes" if ctx.is_archived else "no",
        )
    console.print(table)


@context.command("show")
@click.argument("uri")
@click.option("--tier", type=click.Choice(["L0", "L1", "L2"]), default="L1")
def context_show(uri: str, tier: str) -> None:
    """Show a context by URI at a given tier."""
    from geospark.context import ContextStore, ContextTier

    store = ContextStore()
    ctx = store.load(uri, touch=False)
    if ctx is None:
        console.print(f"[red]Context not found: {uri}[/red]")
        return

    tier_enum = ContextTier(tier)
    console.print(ctx.to_prompt_summary(tier_enum))
    console.print(f"\n[dim]Access count: {ctx.access_count} | Archived: {ctx.is_archived}[/dim]")


@context.command("query")
@click.argument("query")
@click.option("--bbox", default=None, help="Bounding box: 'min_lon,min_lat,max_lon,max_lat'")
@click.option("--category", default=None)
@click.option("--limit", default=10)
def context_query(query: str, bbox: str | None, category: str | None, limit: int) -> None:
    """Query contexts by text, bbox, and category."""
    from geospark.context import ContextRetriever, ContextStore

    bbox_list = None
    if bbox:
        try:
            bbox_list = [float(x) for x in bbox.split(",")]
            if len(bbox_list) != 4:
                raise ValueError("bbox must have 4 values")
        except ValueError as e:
            console.print(f"[red]Invalid bbox: {e}[/red]")
            return

    store = ContextStore()
    retriever = ContextRetriever(store)
    results, stats = retriever.retrieve(
        query=query, bbox=bbox_list, category=category, limit=limit
    )

    if not results:
        console.print(f"[dim]No contexts match '{query}'[/dim]")
        return

    table = Table(title=f"Context Query: {query}")
    table.add_column("#", style="dim", max_width=3)
    table.add_column("URI", style="cyan", max_width=40)
    table.add_column("Score", style="green", max_width=8)
    table.add_column("Semantic", max_width=10)
    table.add_column("Hotness", max_width=10)

    for i, r in enumerate(results, 1):
        table.add_row(
            str(i),
            r.context.uri[:40],
            f"{r.final_score:.3f}",
            f"{r.semantic_score:.3f}",
            f"{r.hotness_score:.3f}",
        )
    console.print(table)
    console.print(
        f"[dim]Candidates: {stats.total_candidates} | "
        f"Filtered by bbox: {stats.filtered_by_bbox} | "
        f"Convergence rounds: {stats.convergence_rounds}[/dim]"
    )


@context.command("stats")
def context_stats() -> None:
    """Show context database statistics."""
    from geospark.context import ContextRetriever, ContextStore

    store = ContextStore()
    retriever = ContextRetriever(store)

    total = store.count()
    archived = store.count(include_archived=True) - total
    categories = store.list_categories()
    hottest = retriever.hottest(limit=3)

    table = Table(title="Context Database")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Total contexts", str(total))
    table.add_row("Archived", str(archived))
    table.add_row("Categories", ", ".join(categories) if categories else "none")
    console.print(table)

    if hottest:
        hot_table = Table(title="Hottest Contexts")
        hot_table.add_column("URI", style="cyan", max_width=50)
        hot_table.add_column("Score", style="green", max_width=8)
        hot_table.add_column("Accesses", max_width=8)
        for h in hottest:
            hot_table.add_row(h.uri[:50], f"{h.score:.3f}", str(h.access_count))
        console.print(hot_table)


@context.command("archive-cold")
@click.option("--threshold", default=0.1, help="Hotness threshold")
def context_archive_cold(threshold: float) -> None:
    """Archive contexts with hotness below threshold."""
    from geospark.context import ContextRetriever, ContextStore

    store = ContextStore()
    retriever = ContextRetriever(store)
    archived = retriever.archive_cold(threshold=threshold)

    if archived:
        console.print(f"[green]Archived {len(archived)} cold contexts[/green]")
        for uri in archived:
            console.print(f"  - {uri}")
    else:
        console.print("[dim]No cold contexts to archive[/dim]")


@main.command("multi-agent")
@click.argument("goal")
@click.option("--stream", is_flag=True, help="Stream progress events as they happen")
def multi_agent(goal: str, stream: bool) -> None:
    """Route a goal through the multi-agent coordinator.

    The coordinator classifies the goal, picks the right specialist agent
    (GeoAgent, SiteSelector, or SpatialReport), and dispatches the task.

    Example:
        geospark multi-agent "Find the best location for a cafe in Melbourne"
    """
    from geospark.agents import AgentCoordinator

    coord = AgentCoordinator()

    if stream:
        import asyncio

        async def _run_stream() -> None:
            async for ev in coord.stream(goal):
                icon = {
                    "classify": "[cyan]*[/cyan]",
                    "dispatch": "[yellow]>[/yellow]",
                    "agent_start": "[blue]>>[/blue]",
                    "agent_done": "[green]OK[/green]",
                    "complete": "[bold green]DONE[/bold green]",
                    "error": "[red]X[/red]",
                }.get(ev.event_type, "-")
                console.print(f"  {icon} {ev.event_type}: {ev.message}")

        asyncio.run(_run_stream())
        return

    console.print(f"[bold]Coordinator[/bold]: {goal}\n")
    result = coord.run(goal)

    if result.classification:
        console.print(
            f"[cyan]Routed to[/cyan]: {result.agent_used} "
            f"(score={result.classification.score:.2f})"
        )
        console.print(f"[dim]{result.classification.reason}[/dim]\n")

    if result.error:
        console.print(f"[red]Error:[/red] {result.error}")
    else:
        console.print(f"[bold]Result[/bold]: {result.summary}")

    console.print(f"[dim]({result.duration_s}s)[/dim]")


@main.command("agents")
def agents_list() -> None:
    """List registered specialist agents in the coordinator."""
    from geospark.agents import AgentCoordinator

    coord = AgentCoordinator()
    cards = coord.list_agents()

    if not cards:
        console.print("[dim]No agents registered[/dim]")
        return

    table = Table(title=f"Registered Agents ({len(cards)})")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="green")
    table.add_column("Capabilities", style="yellow")

    for card in cards:
        table.add_row(
            card.name,
            card.description[:60],
            ", ".join(card.capabilities[:4]),
        )
    console.print(table)


@main.group()
def admin() -> None:
    """Admin tools -- audit logs, usage stats."""


@admin.command("audit")
@click.option("--date", default=None, help="Date (YYYY-MM-DD), defaults to today")
@click.option("--limit", default=20, help="Max entries to show")
def admin_audit(date: str | None, limit: int) -> None:
    """View audit log entries."""
    from geospark.middleware.audit_log import AuditStore

    store = AuditStore()
    entries = store.read_date(date, limit=limit) if date else store.read_today(limit=limit)

    if not entries:
        console.print("[dim]No audit entries found[/dim]")
        return

    table = Table(title=f"Audit Log ({len(entries)} entries)")
    table.add_column("Time", style="dim", max_width=12)
    table.add_column("Method", max_width=6)
    table.add_column("Path", style="cyan", max_width=35)
    table.add_column("Status", max_width=6)
    table.add_column("Duration", max_width=8)
    table.add_column("IP", style="dim", max_width=15)

    for e in entries:
        ts = e.get("timestamp", "")[-12:-1] if e.get("timestamp") else ""
        status = str(e.get("status_code", ""))
        color = "green" if status.startswith("2") else "red" if status.startswith("5") else "yellow"
        table.add_row(
            ts,
            e.get("method", ""),
            e.get("path", "")[:35],
            f"[{color}]{status}[/{color}]",
            f"{e.get('duration_ms', 0):.0f}ms",
            e.get("client_ip", "")[:15],
        )
    console.print(table)


@admin.command("usage")
def admin_usage() -> None:
    """Show API usage statistics."""
    from geospark.middleware.usage_tracker import UsageTracker

    tracker = UsageTracker()
    summary = tracker.summary()

    table = Table(title="API Usage")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Total requests", str(summary["total_requests"]))
    table.add_row("Unique API keys", str(summary["unique_keys"]))
    table.add_row("Unique endpoints", str(summary["unique_endpoints"]))
    table.add_row("Tracking since", summary.get("tracking_since", "?")[:19])
    console.print(table)

    if summary.get("status_codes"):
        sc_table = Table(title="Status Codes")
        sc_table.add_column("Code", style="cyan")
        sc_table.add_column("Count", style="green")
        for code, count in sorted(summary["status_codes"].items()):
            sc_table.add_row(str(code), str(count))
        console.print(sc_table)

    if summary.get("top_endpoints"):
        ep_table = Table(title="Top Endpoints")
        ep_table.add_column("Path", style="cyan")
        ep_table.add_column("Count", style="green")
        for ep in summary["top_endpoints"][:10]:
            ep_table.add_row(ep["path"], str(ep["count"]))
        console.print(ep_table)


if __name__ == "__main__":
    main()
