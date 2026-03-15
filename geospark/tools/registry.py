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
            raise ImportError(
                f"Could not load tool '{name}': {e}. "
                f"Install required dependencies: pip install geospark[{name}]"
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
        """List all available (but not necessarily loaded) tools."""
        return list(TOOL_CLASSES.keys())

    def register_custom_tool(self, tool: BaseTool) -> None:
        """Register a custom tool instance."""
        self._tools[tool.name] = tool
        for op in tool.supported_operations:
            self._operation_map[op] = tool.name

    def get_all_schemas(self) -> list[dict]:
        """Get OpenAI-compatible function schemas for all loaded tools."""
        return [tool.get_schema() for tool in self._tools.values()]
