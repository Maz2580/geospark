"""
Tool Registry.

Discovers, loads, and manages GeoSpark tools.
"""

from __future__ import annotations

from geospark.tools.base import BaseTool

# Lazy imports for tools to avoid loading unused dependencies
TOOL_CLASSES: dict[str, str] = {
    "geocoder": "geospark.tools.geocoding.nominatim.NominatimGeocoder",
    "reverse_geocoder": "geospark.tools.geocoding.reverse.ReverseGeocoder",
    "satellite": "geospark.tools.satellite.stac_client.STACTool",
    "ndvi": "geospark.tools.satellite.ndvi.NDVITool",
    "spectral_indices": "geospark.tools.satellite.spectral_indices.SpectralIndicesTool",
    "terrain": "geospark.tools.terrain.elevation.ElevationTool",
    "change_detection": "geospark.tools.change_detection.pixel_change.PixelChangeTool",
    "router": "geospark.tools.routing.osrm.OSRMRouteTool",
}

# What each tool can do today: "ready", "partial" (works, but less than its name suggests) or
# "planned" (the protocol has it, the code returns "not implemented"). Planned tools are never
# listed as available, and the status page shows the description so nothing is overclaimed.
TOOL_STATUS: dict[str, tuple[str, str]] = {
    "geocoder": ("ready", "Place names to coordinates (OpenStreetMap Nominatim)"),
    "reverse_geocoder": ("ready", "Coordinates to addresses (OpenStreetMap Nominatim)"),
    "satellite": ("ready", "Satellite scene search (Sentinel-2 and others via STAC)"),
    "ndvi": ("partial", "Finds Sentinel-2 scenes for NDVI; does not compute NDVI values yet"),
    "spectral_indices": ("partial", "Finds scenes for spectral indices; does not compute index values yet"),
    "terrain": ("ready", "Elevation (Copernicus DEM, Open Elevation as fallback), with vertical accuracy"),
    "change_detection": ("planned", "Not built yet"),
    "router": ("ready", "Driving routes between two points (public OSRM server)"),
}

# Optional-dependency extra that each tool needs (tools not listed need only the core install)
TOOL_EXTRAS: dict[str, str] = {
    "satellite": "satellite",
}


class ToolRegistry:
    """Registry for discovering and loading GeoSpark tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._operation_map: dict[str, str] = {}

    def load_tool(self, name: str) -> None:
        """Load a tool by name."""
        if name in self._tools:
            return

        class_path = TOOL_CLASSES.get(name)
        if class_path is None:
            raise ValueError(
                f"Unknown tool: {name}. Available: {list(TOOL_CLASSES.keys())}"
            )

        # Dynamic import
        module_path, class_name = class_path.rsplit(".", 1)
        try:
            import importlib
            module = importlib.import_module(module_path)
            tool_class = getattr(module, class_name)
            tool = tool_class()
            self._tools[name] = tool

            # Map operations to tools
            for op in tool.supported_operations:
                self._operation_map[op] = name
        except ImportError as e:
            extra = TOOL_EXTRAS.get(name)
            hint = f"pip install geospark-ai[{extra}]" if extra else "pip install geospark-ai"
            raise ImportError(
                f"Could not load tool '{name}': {e}. Install required dependencies: {hint}"
            ) from e

    def get_tool(self, name: str) -> BaseTool | None:
        """Get a loaded tool by name."""
        return self._tools.get(name)

    def get_tool_for_operation(self, operation: str) -> BaseTool | None:
        """Get the tool that handles a specific operation."""
        tool_name = self._operation_map.get(operation)
        if tool_name:
            return self._tools.get(tool_name)
        return None

    def list_tools(self) -> list[str]:
        """List all loaded tools."""
        return list(self._tools.keys())

    def list_available_tools(self) -> list[str]:
        """List the tools that can be loaded and do something (planned ones are left out)."""
        return [name for name in TOOL_CLASSES if TOOL_STATUS.get(name, ("ready", ""))[0] != "planned"]

    def register_custom_tool(self, tool: BaseTool) -> None:
        """Register a custom tool instance."""
        self._tools[tool.name] = tool
        for op in tool.supported_operations:
            self._operation_map[op] = tool.name

    def get_all_schemas(self) -> list[dict]:
        """Get OpenAI-compatible function schemas for all loaded tools."""
        return [tool.get_schema() for tool in self._tools.values()]
