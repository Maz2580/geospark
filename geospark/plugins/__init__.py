"""
GeoSpark Plugins -- Community plugin system.

Enables third-party tool contributions through a manifest-based
discovery and loading mechanism with lifecycle hooks.
"""

from __future__ import annotations

from geospark.plugins.hooks import PluginHooks
from geospark.plugins.loader import PluginLoader
from geospark.plugins.manifest import PluginManifest

__all__ = ["PluginHooks", "PluginLoader", "PluginManifest"]
