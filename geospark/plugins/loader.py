"""
Plugin discovery and loading.

Scans configured directories for ``geospark.plugin.json`` manifests,
validates them, and dynamically imports the declared tool classes.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from geospark.plugins.hooks import PluginHooks
from geospark.plugins.manifest import PluginManifest
from geospark.tools.base import BaseTool

MANIFEST_FILENAME = "geospark.plugin.json"


class PluginLoader:
    """Discovers, validates, and loads community plugins.

    Plugins are located by scanning one or more directories for
    ``geospark.plugin.json`` manifest files.  Each manifest declares
    the module path and class name of a :class:`BaseTool` subclass.

    Args:
        plugin_dirs: Directories to scan for plugins.  Defaults to
            ``~/.geospark/plugins`` and a project-local ``plugins/``
            directory.
        hooks: Optional :class:`PluginHooks` instance for lifecycle
            event notification.
    """

    def __init__(
        self,
        plugin_dirs: list[Path] | None = None,
        hooks: PluginHooks | None = None,
    ) -> None:
        self._plugin_dirs: list[Path] = plugin_dirs or [
            Path.home() / ".geospark" / "plugins",
            Path("plugins"),
        ]
        self._loaded: dict[str, PluginManifest] = {}
        self._tools: dict[str, BaseTool] = {}
        self._hooks = hooks or PluginHooks()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[PluginManifest]:
        """Scan plugin directories for manifest files.

        Returns:
            List of validated :class:`PluginManifest` objects found on
            disk.  Manifests that fail to parse are silently skipped.
        """
        manifests: list[PluginManifest] = []
        for plugin_dir in self._plugin_dirs:
            if not plugin_dir.is_dir():
                continue
            # Each plugin lives in its own subdirectory
            for child in sorted(plugin_dir.iterdir()):
                manifest_path = child / MANIFEST_FILENAME
                if manifest_path.is_file():
                    try:
                        manifest = PluginManifest.from_file(manifest_path)
                        manifests.append(manifest)
                    except (ValueError, FileNotFoundError):
                        # Skip malformed manifests
                        continue
        return manifests

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, manifest: PluginManifest) -> BaseTool:
        """Import a plugin's tool class and return an instance.

        The tool class is resolved from the manifest's ``entry_point``
        and ``tool_class`` fields.  If the ``entry_point`` cannot be
        found via the normal import machinery the loader also checks
        whether the manifest file's parent directory contains the
        module as a plain ``.py`` file and inserts its directory into
        ``sys.path`` temporarily.

        Args:
            manifest: A validated plugin manifest.

        Returns:
            An instance of the plugin's tool class.

        Raises:
            ImportError: If the module cannot be imported.
            TypeError: If the class does not extend :class:`BaseTool`.
        """
        # Determine the directory that contains the manifest so we can
        # fall back to a file-based import when the entry_point is a
        # relative/local module inside the plugin directory.
        plugin_base_dir = self._resolve_plugin_base_dir(manifest)

        try:
            module = importlib.import_module(manifest.entry_point)
        except ModuleNotFoundError:
            # Attempt to import from the plugin's own directory
            if plugin_base_dir is not None:
                module = self._import_from_dir(
                    manifest.entry_point, plugin_base_dir
                )
            else:
                raise

        tool_cls: Any = getattr(module, manifest.tool_class, None)
        if tool_cls is None:
            raise ImportError(
                f"Class '{manifest.tool_class}' not found in module "
                f"'{manifest.entry_point}'"
            ) from None

        if not (isinstance(tool_cls, type) and issubclass(tool_cls, BaseTool)):
            raise TypeError(
                f"Plugin '{manifest.id}': class '{manifest.tool_class}' "
                f"does not extend BaseTool"
            )

        tool_instance = tool_cls()
        self._loaded[manifest.id] = manifest
        self._tools[manifest.id] = tool_instance
        self._hooks.trigger("on_load", plugin_id=manifest.id, tool=tool_instance)
        return tool_instance

    def load_all(self) -> dict[str, BaseTool]:
        """Discover and load every available plugin.

        Returns:
            Mapping of plugin id to loaded :class:`BaseTool` instance.
        """
        for manifest in self.discover():
            if manifest.id not in self._loaded:
                try:
                    self.load(manifest)
                except (ImportError, TypeError):
                    # Skip plugins that fail to load
                    continue
        return dict(self._tools)

    def unload(self, plugin_id: str) -> None:
        """Unload a previously loaded plugin.

        Args:
            plugin_id: The unique identifier of the plugin to unload.
        """
        if plugin_id in self._loaded:
            tool = self._tools.pop(plugin_id, None)
            self._loaded.pop(plugin_id, None)
            self._hooks.trigger("on_unload", plugin_id=plugin_id, tool=tool)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, manifest: PluginManifest) -> list[str]:
        """Validate a manifest and return a list of issues.

        An empty list means the manifest is fully valid and the plugin
        can be loaded.

        Args:
            manifest: The manifest to validate.

        Returns:
            List of human-readable issue descriptions.
        """
        issues: list[str] = []

        # Check entry_point is importable
        plugin_base_dir = self._resolve_plugin_base_dir(manifest)
        try:
            module = importlib.import_module(manifest.entry_point)
        except ModuleNotFoundError:
            if plugin_base_dir is not None:
                try:
                    module = self._import_from_dir(
                        manifest.entry_point, plugin_base_dir
                    )
                except (ModuleNotFoundError, ImportError) as err:
                    issues.append(f"Cannot import entry_point '{manifest.entry_point}': {err}")
                    module = None
            else:
                issues.append(
                    f"Cannot import entry_point '{manifest.entry_point}'"
                )
                module = None
        except ImportError as err:
            issues.append(f"Cannot import entry_point '{manifest.entry_point}': {err}")
            module = None

        # Check tool_class exists and extends BaseTool
        if module is not None:
            tool_cls = getattr(module, manifest.tool_class, None)
            if tool_cls is None:
                issues.append(
                    f"Class '{manifest.tool_class}' not found in "
                    f"'{manifest.entry_point}'"
                )
            elif not (isinstance(tool_cls, type) and issubclass(tool_cls, BaseTool)):
                issues.append(
                    f"Class '{manifest.tool_class}' does not extend BaseTool"
                )

        # Check required dependencies
        _, missing = self.check_dependencies(manifest)
        for dep in missing:
            issues.append(f"Missing dependency: {dep}")

        return issues

    def check_dependencies(
        self, manifest: PluginManifest
    ) -> tuple[list[str], list[str]]:
        """Check which pip dependencies are installed versus missing.

        Args:
            manifest: The manifest whose ``requires`` list is checked.

        Returns:
            A tuple of ``(installed, missing)`` package name lists.
        """
        installed: list[str] = []
        missing: list[str] = []
        for dep in manifest.requires:
            # Normalise the distribution name (pip uses dashes, importlib
            # metadata does too, but some packages use underscores).
            dep_normalised = dep.replace("-", "_").replace(".", "_").lower()
            if importlib.util.find_spec(dep_normalised) is not None:
                installed.append(dep)
            else:
                # Also try the original name
                if importlib.util.find_spec(dep) is not None:
                    installed.append(dep)
                else:
                    missing.append(dep)
        return installed, missing

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def loaded_plugins(self) -> dict[str, PluginManifest]:
        """Return a mapping of plugin id to manifest for loaded plugins."""
        return dict(self._loaded)

    @property
    def tools(self) -> dict[str, BaseTool]:
        """Return a mapping of plugin id to tool instance for loaded plugins."""
        return dict(self._tools)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_plugin_base_dir(self, manifest: PluginManifest) -> Path | None:
        """Try to find the directory a manifest was loaded from.

        This scans ``self._plugin_dirs`` for a subdirectory that
        contains the manifest for the given plugin id.
        """
        for plugin_dir in self._plugin_dirs:
            if not plugin_dir.is_dir():
                continue
            for child in plugin_dir.iterdir():
                manifest_path = child / MANIFEST_FILENAME
                if manifest_path.is_file():
                    try:
                        loaded = PluginManifest.from_file(manifest_path)
                        if loaded.id == manifest.id:
                            return child
                    except (ValueError, FileNotFoundError):
                        continue
        return None

    @staticmethod
    def _import_from_dir(module_name: str, directory: Path) -> Any:
        """Import a module by adding *directory* to ``sys.path``.

        Args:
            module_name: Dotted module path.
            directory: Directory to prepend to ``sys.path``.

        Returns:
            The imported module object.

        Raises:
            ImportError: If the module still cannot be found.
        """
        dir_str = str(directory)
        added = False
        if dir_str not in sys.path:
            sys.path.insert(0, dir_str)
            added = True
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as err:
            raise ImportError(
                f"Cannot import '{module_name}' from directory '{directory}': {err}"
            ) from err
        finally:
            if added and dir_str in sys.path:
                sys.path.remove(dir_str)
