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
    from geospark.protocol.schema import SpatialQuery, SpatialOperation

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
    from geospark.protocol.schema import SpatialQuery, SpatialOperation, Point

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


if __name__ == "__main__":
    main()
