"""
GeoSpark CLI.

Command-line interface for GeoSpark operations.
"""

from __future__ import annotations

import json

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="geospark")
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


if __name__ == "__main__":
    main()
