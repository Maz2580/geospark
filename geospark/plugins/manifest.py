"""
Plugin manifest schema.

Defines the metadata for a GeoSpark community plugin, including
its entry point, dependencies, and versioning information.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class PluginManifest(BaseModel):
    """Schema for a GeoSpark plugin manifest (geospark.plugin.json).

    Each community plugin ships a manifest file that describes the plugin,
    its entry point, required dependencies, and optional MCP server name.

    Example manifest::

        {
            "id": "ndvi-analysis",
            "name": "NDVI Analysis",
            "version": "1.0.0",
            "description": "Compute NDVI from satellite imagery.",
            "author": "GeoSpark Community",
            "entry_point": "geospark.tools.satellite.ndvi",
            "tool_class": "NDVITool"
        }
    """

    id: str = Field(..., description="Unique plugin identifier, e.g. 'ndvi-analysis'")
    name: str = Field(..., description="Human-readable display name")
    version: str = Field(..., description="Semantic version string, e.g. '1.0.0'")
    description: str = Field(..., description="Brief description of the plugin")
    author: str = Field(default="", description="Plugin author or organisation")
    license: str = Field(default="Apache-2.0", description="SPDX license identifier")
    entry_point: str = Field(
        ...,
        description="Dotted module path to import, e.g. 'geospark.tools.satellite.ndvi'",
    )
    tool_class: str = Field(
        ...,
        description="Class name within the entry_point module, e.g. 'NDVITool'",
    )
    requires: list[str] = Field(
        default_factory=list,
        description="Pip package names required by this plugin",
    )
    mcp_server_name: str | None = Field(
        default=None,
        description="Optional MCP server name for server integration",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Search tags, e.g. ['satellite', 'vegetation']",
    )
    homepage: str = Field(default="", description="URL to the plugin homepage")
    min_geospark_version: str = Field(
        default="0.1.0",
        description="Minimum GeoSpark version required",
    )

    @classmethod
    def from_file(cls, path: Path) -> PluginManifest:
        """Load a manifest from a ``geospark.plugin.json`` file.

        Args:
            path: Path to the JSON manifest file.

        Returns:
            A validated PluginManifest instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file contains invalid JSON or fails validation.
        """
        if not path.exists():
            raise FileNotFoundError(f"Manifest file not found: {path}")

        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except json.JSONDecodeError as err:
            raise ValueError(f"Invalid JSON in manifest {path}: {err}") from err

        try:
            return cls.model_validate(data)
        except Exception as err:
            raise ValueError(f"Invalid manifest {path}: {err}") from err

    def to_file(self, path: Path) -> None:
        """Save the manifest to a JSON file.

        Args:
            path: Destination file path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
