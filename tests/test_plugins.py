"""
Tests for the GeoSpark community plugin system.

Covers manifest validation, serialization, plugin discovery, loading,
dependency checking, lifecycle hooks, and end-to-end loading of a
real test fixture plugin.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from geospark.plugins.hooks import PluginHooks
from geospark.plugins.loader import PluginLoader
from geospark.plugins.manifest import PluginManifest
from geospark.tools.base import BaseTool

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_PLUGIN_DIR = FIXTURES_DIR / "test_plugin"
TEST_MANIFEST_PATH = TEST_PLUGIN_DIR / "geospark.plugin.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_manifest_data(**overrides: Any) -> dict[str, Any]:
    """Return a dict of valid manifest fields, with optional overrides."""
    data: dict[str, Any] = {
        "id": "test-plugin",
        "name": "Test Plugin",
        "version": "1.0.0",
        "description": "A test plugin.",
        "entry_point": "tool",
        "tool_class": "EchoTool",
    }
    data.update(overrides)
    return data


# ===================================================================
# PluginManifest -- validation
# ===================================================================


class TestPluginManifestValidation:
    """Manifest creation and field validation."""

    def test_valid_manifest(self) -> None:
        """A manifest with all required fields should validate."""
        m = PluginManifest(**_minimal_manifest_data())
        assert m.id == "test-plugin"
        assert m.name == "Test Plugin"
        assert m.version == "1.0.0"

    def test_defaults_applied(self) -> None:
        """Optional fields should receive sensible defaults."""
        m = PluginManifest(**_minimal_manifest_data())
        assert m.author == ""
        assert m.license == "Apache-2.0"
        assert m.requires == []
        assert m.mcp_server_name is None
        assert m.tags == []
        assert m.homepage == ""
        assert m.min_geospark_version == "0.1.0"

    def test_missing_required_field_raises(self) -> None:
        """Omitting a required field must raise a validation error."""
        from pydantic import ValidationError

        data = _minimal_manifest_data()
        del data["id"]
        with pytest.raises(ValidationError):
            PluginManifest(**data)

    def test_missing_entry_point_raises(self) -> None:
        """entry_point is required."""
        from pydantic import ValidationError

        data = _minimal_manifest_data()
        del data["entry_point"]
        with pytest.raises(ValidationError):
            PluginManifest(**data)

    def test_missing_tool_class_raises(self) -> None:
        """tool_class is required."""
        from pydantic import ValidationError

        data = _minimal_manifest_data()
        del data["tool_class"]
        with pytest.raises(ValidationError):
            PluginManifest(**data)

    def test_optional_fields_populated(self) -> None:
        """All optional fields can be explicitly set."""
        m = PluginManifest(
            **_minimal_manifest_data(
                author="Alice",
                license="MIT",
                requires=["httpx"],
                mcp_server_name="my_server",
                tags=["geo", "test"],
                homepage="https://example.com",
                min_geospark_version="0.2.0",
            )
        )
        assert m.author == "Alice"
        assert m.license == "MIT"
        assert m.requires == ["httpx"]
        assert m.mcp_server_name == "my_server"
        assert m.tags == ["geo", "test"]
        assert m.homepage == "https://example.com"
        assert m.min_geospark_version == "0.2.0"


# ===================================================================
# PluginManifest -- serialization
# ===================================================================


class TestPluginManifestSerialization:
    """Manifest round-trip via to_file / from_file."""

    def test_from_file_loads_fixture(self) -> None:
        """from_file should load the test fixture manifest."""
        m = PluginManifest.from_file(TEST_MANIFEST_PATH)
        assert m.id == "echo-tool"
        assert m.tool_class == "EchoTool"

    def test_to_file_and_from_file_roundtrip(self, tmp_path: Path) -> None:
        """Saving then loading should produce an identical manifest."""
        original = PluginManifest(**_minimal_manifest_data())
        out = tmp_path / "geospark.plugin.json"
        original.to_file(out)
        loaded = PluginManifest.from_file(out)
        assert loaded == original

    def test_to_file_creates_parent_dirs(self, tmp_path: Path) -> None:
        """to_file should create intermediate directories."""
        out = tmp_path / "deep" / "nested" / "geospark.plugin.json"
        m = PluginManifest(**_minimal_manifest_data())
        m.to_file(out)
        assert out.exists()

    def test_from_file_missing_raises(self, tmp_path: Path) -> None:
        """from_file should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            PluginManifest.from_file(tmp_path / "does_not_exist.json")

    def test_from_file_invalid_json_raises(self, tmp_path: Path) -> None:
        """from_file should raise ValueError for broken JSON."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            PluginManifest.from_file(bad)

    def test_from_file_invalid_schema_raises(self, tmp_path: Path) -> None:
        """from_file should raise ValueError when fields are wrong."""
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"id": "x"}), encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid manifest"):
            PluginManifest.from_file(bad)


# ===================================================================
# PluginLoader -- discover
# ===================================================================


class TestPluginLoaderDiscover:
    """Plugin directory scanning."""

    def test_discover_finds_fixture_plugin(self) -> None:
        """discover() should find the test fixture plugin."""
        loader = PluginLoader(plugin_dirs=[FIXTURES_DIR])
        manifests = loader.discover()
        ids = [m.id for m in manifests]
        assert "echo-tool" in ids

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        """discover() should return an empty list for an empty dir."""
        loader = PluginLoader(plugin_dirs=[tmp_path])
        assert loader.discover() == []

    def test_discover_nonexistent_dir(self, tmp_path: Path) -> None:
        """discover() should not error on a non-existent directory."""
        loader = PluginLoader(plugin_dirs=[tmp_path / "nope"])
        assert loader.discover() == []

    def test_discover_skips_malformed(self, tmp_path: Path) -> None:
        """discover() should skip directories with invalid manifests."""
        bad_dir = tmp_path / "bad_plugin"
        bad_dir.mkdir()
        (bad_dir / "geospark.plugin.json").write_text(
            "NOT JSON", encoding="utf-8"
        )
        loader = PluginLoader(plugin_dirs=[tmp_path])
        assert loader.discover() == []


# ===================================================================
# PluginLoader -- load
# ===================================================================


class TestPluginLoaderLoad:
    """Single-plugin loading."""

    def test_load_fixture_plugin(self) -> None:
        """load() should import and instantiate the test fixture tool."""
        loader = PluginLoader(plugin_dirs=[FIXTURES_DIR])
        manifest = PluginManifest.from_file(TEST_MANIFEST_PATH)
        tool = loader.load(manifest)
        assert isinstance(tool, BaseTool)
        assert tool.name == "echo_tool"

    def test_load_records_plugin(self) -> None:
        """After load(), the plugin appears in loaded_plugins."""
        loader = PluginLoader(plugin_dirs=[FIXTURES_DIR])
        manifest = PluginManifest.from_file(TEST_MANIFEST_PATH)
        loader.load(manifest)
        assert "echo-tool" in loader.loaded_plugins

    def test_load_bad_entry_point_raises(self) -> None:
        """load() should raise ImportError for a bad entry_point."""
        manifest = PluginManifest(
            **_minimal_manifest_data(entry_point="no_such_module_xyz_123")
        )
        loader = PluginLoader(plugin_dirs=[])
        with pytest.raises(ImportError):
            loader.load(manifest)

    def test_load_bad_class_raises(self) -> None:
        """load() should raise ImportError when the class doesn't exist."""
        manifest = PluginManifest(
            **_minimal_manifest_data(
                entry_point="json",  # stdlib, but no tool class
                tool_class="NonExistentClass",
            )
        )
        loader = PluginLoader(plugin_dirs=[])
        with pytest.raises(ImportError, match="not found"):
            loader.load(manifest)

    def test_load_non_basetool_raises(self) -> None:
        """load() should raise TypeError if the class isn't a BaseTool."""
        manifest = PluginManifest(
            **_minimal_manifest_data(
                entry_point="json",
                tool_class="JSONEncoder",  # exists but not a BaseTool
            )
        )
        loader = PluginLoader(plugin_dirs=[])
        with pytest.raises(TypeError, match="does not extend BaseTool"):
            loader.load(manifest)


# ===================================================================
# PluginLoader -- load_all
# ===================================================================


class TestPluginLoaderLoadAll:
    """Bulk loading of discovered plugins."""

    def test_load_all_fixture(self) -> None:
        """load_all() should load the fixture plugin."""
        loader = PluginLoader(plugin_dirs=[FIXTURES_DIR])
        tools = loader.load_all()
        assert "echo-tool" in tools
        assert isinstance(tools["echo-tool"], BaseTool)

    def test_load_all_skips_failures(self, tmp_path: Path) -> None:
        """load_all() should skip plugins that fail to import."""
        # Create a plugin with a bad entry_point
        bad_dir = tmp_path / "bad_plugin"
        bad_dir.mkdir()
        manifest = PluginManifest(
            **_minimal_manifest_data(
                id="bad-plugin",
                entry_point="nonexistent_module_abc",
            )
        )
        manifest.to_file(bad_dir / "geospark.plugin.json")

        loader = PluginLoader(plugin_dirs=[tmp_path])
        tools = loader.load_all()
        assert "bad-plugin" not in tools


# ===================================================================
# PluginLoader -- validate
# ===================================================================


class TestPluginLoaderValidate:
    """Manifest validation via the loader."""

    def test_validate_valid_manifest(self) -> None:
        """A valid, importable manifest should produce no issues."""
        loader = PluginLoader(plugin_dirs=[FIXTURES_DIR])
        manifest = PluginManifest.from_file(TEST_MANIFEST_PATH)
        issues = loader.validate(manifest)
        assert issues == []

    def test_validate_bad_entry_point(self) -> None:
        """validate() should flag a non-importable entry_point."""
        manifest = PluginManifest(
            **_minimal_manifest_data(entry_point="nonexistent_xyz_999")
        )
        loader = PluginLoader(plugin_dirs=[])
        issues = loader.validate(manifest)
        assert any("entry_point" in i for i in issues)

    def test_validate_bad_class(self) -> None:
        """validate() should flag a missing tool class."""
        manifest = PluginManifest(
            **_minimal_manifest_data(
                entry_point="json",
                tool_class="NoSuchClass",
            )
        )
        loader = PluginLoader(plugin_dirs=[])
        issues = loader.validate(manifest)
        assert any("not found" in i for i in issues)

    def test_validate_non_basetool_class(self) -> None:
        """validate() should flag a class that doesn't extend BaseTool."""
        manifest = PluginManifest(
            **_minimal_manifest_data(
                entry_point="json",
                tool_class="JSONEncoder",
            )
        )
        loader = PluginLoader(plugin_dirs=[])
        issues = loader.validate(manifest)
        assert any("does not extend BaseTool" in i for i in issues)

    def test_validate_missing_dependency(self) -> None:
        """validate() should list missing pip dependencies."""
        manifest = PluginManifest(
            **_minimal_manifest_data(
                entry_point="json",
                tool_class="JSONEncoder",
                requires=["nonexistent_package_xyz_999"],
            )
        )
        loader = PluginLoader(plugin_dirs=[])
        issues = loader.validate(manifest)
        assert any("Missing dependency" in i for i in issues)


# ===================================================================
# PluginLoader -- check_dependencies
# ===================================================================


class TestPluginLoaderCheckDeps:
    """Dependency checking."""

    def test_installed_dependency(self) -> None:
        """A package present in the environment should be reported as installed."""
        manifest = PluginManifest(
            **_minimal_manifest_data(requires=["json"])
        )
        loader = PluginLoader(plugin_dirs=[])
        installed, missing = loader.check_dependencies(manifest)
        assert "json" in installed
        assert missing == []

    def test_missing_dependency(self) -> None:
        """A package not present should be reported as missing."""
        manifest = PluginManifest(
            **_minimal_manifest_data(requires=["no_such_dep_xyz_999"])
        )
        loader = PluginLoader(plugin_dirs=[])
        installed, missing = loader.check_dependencies(manifest)
        assert installed == []
        assert "no_such_dep_xyz_999" in missing

    def test_mixed_dependencies(self) -> None:
        """Both installed and missing deps should be classified correctly."""
        manifest = PluginManifest(
            **_minimal_manifest_data(
                requires=["json", "no_such_dep_abc_888"]
            )
        )
        loader = PluginLoader(plugin_dirs=[])
        installed, missing = loader.check_dependencies(manifest)
        assert "json" in installed
        assert "no_such_dep_abc_888" in missing

    def test_no_dependencies(self) -> None:
        """An empty requires list should return two empty lists."""
        manifest = PluginManifest(**_minimal_manifest_data())
        loader = PluginLoader(plugin_dirs=[])
        installed, missing = loader.check_dependencies(manifest)
        assert installed == []
        assert missing == []


# ===================================================================
# PluginLoader -- unload
# ===================================================================


class TestPluginLoaderUnload:
    """Plugin unloading."""

    def test_unload_removes_plugin(self) -> None:
        """unload() should remove the plugin from loaded_plugins."""
        loader = PluginLoader(plugin_dirs=[FIXTURES_DIR])
        manifest = PluginManifest.from_file(TEST_MANIFEST_PATH)
        loader.load(manifest)
        assert "echo-tool" in loader.loaded_plugins
        loader.unload("echo-tool")
        assert "echo-tool" not in loader.loaded_plugins
        assert "echo-tool" not in loader.tools

    def test_unload_nonexistent_is_noop(self) -> None:
        """unload() on an unknown id should not raise."""
        loader = PluginLoader(plugin_dirs=[])
        loader.unload("does-not-exist")  # should not raise


# ===================================================================
# PluginHooks -- registration and triggering
# ===================================================================


class TestPluginHooks:
    """Lifecycle hook registration and firing."""

    def test_register_and_trigger(self) -> None:
        """A registered callback should be called on trigger."""
        hooks = PluginHooks()
        results: list[str] = []
        hooks.register("on_load", lambda **kw: results.append("loaded"))
        hooks.trigger("on_load")
        assert results == ["loaded"]

    def test_trigger_returns_values(self) -> None:
        """trigger() should return callback return values."""
        hooks = PluginHooks()
        hooks.register("on_load", lambda **kw: 42)
        result = hooks.trigger("on_load")
        assert result == [42]

    def test_fifo_ordering(self) -> None:
        """Callbacks must fire in registration (FIFO) order."""
        hooks = PluginHooks()
        order: list[int] = []
        hooks.register("on_load", lambda **kw: order.append(1))
        hooks.register("on_load", lambda **kw: order.append(2))
        hooks.register("on_load", lambda **kw: order.append(3))
        hooks.trigger("on_load")
        assert order == [1, 2, 3]

    def test_unregister_removes_callback(self) -> None:
        """After unregister, the callback should no longer fire."""
        hooks = PluginHooks()
        calls: list[str] = []
        cb = lambda **kw: calls.append("hit")  # noqa: E731
        hooks.register("on_load", cb)
        hooks.unregister("on_load", cb)
        hooks.trigger("on_load")
        assert calls == []

    def test_unregister_unknown_callback_raises(self) -> None:
        """Unregistering a callback that was never added should raise."""
        hooks = PluginHooks()
        with pytest.raises(ValueError, match="not registered"):
            hooks.unregister("on_load", lambda **kw: None)

    def test_register_unknown_hook_raises(self) -> None:
        """Registering on a bogus hook name should raise."""
        hooks = PluginHooks()
        with pytest.raises(ValueError, match="Unknown hook"):
            hooks.register("bogus_hook", lambda **kw: None)

    def test_trigger_unknown_hook_raises(self) -> None:
        """Triggering a bogus hook name should raise."""
        hooks = PluginHooks()
        with pytest.raises(ValueError, match="Unknown hook"):
            hooks.trigger("bogus_hook")

    def test_kwargs_forwarded(self) -> None:
        """Keyword arguments should be forwarded to callbacks."""
        hooks = PluginHooks()
        received: dict[str, Any] = {}
        hooks.register("on_load", lambda **kw: received.update(kw))
        hooks.trigger("on_load", plugin_id="x", tool="y")
        assert received == {"plugin_id": "x", "tool": "y"}

    def test_all_hook_names_valid(self) -> None:
        """All five defined hook names should accept registration."""
        hooks = PluginHooks()
        for name in [
            "before_tool_call",
            "after_tool_call",
            "on_error",
            "on_load",
            "on_unload",
        ]:
            hooks.register(name, lambda **kw: None)  # should not raise

    def test_clear_single_hook(self) -> None:
        """clear(hook_name) should remove all callbacks for that hook only."""
        hooks = PluginHooks()
        hooks.register("on_load", lambda **kw: 1)
        hooks.register("on_unload", lambda **kw: 2)
        hooks.clear("on_load")
        assert hooks.trigger("on_load") == []
        assert hooks.trigger("on_unload") == [2]

    def test_clear_all_hooks(self) -> None:
        """clear() with no argument should remove everything."""
        hooks = PluginHooks()
        hooks.register("on_load", lambda **kw: 1)
        hooks.register("on_error", lambda **kw: 2)
        hooks.clear()
        assert hooks.trigger("on_load") == []
        assert hooks.trigger("on_error") == []


# ===================================================================
# PluginHooks integration with PluginLoader
# ===================================================================


class TestPluginHooksIntegration:
    """Hooks fired during plugin load/unload via PluginLoader."""

    def test_on_load_hook_fires(self) -> None:
        """Loading a plugin should trigger the on_load hook."""
        hooks = PluginHooks()
        events: list[str] = []
        hooks.register("on_load", lambda **kw: events.append(kw["plugin_id"]))

        loader = PluginLoader(plugin_dirs=[FIXTURES_DIR], hooks=hooks)
        manifest = PluginManifest.from_file(TEST_MANIFEST_PATH)
        loader.load(manifest)
        assert events == ["echo-tool"]

    def test_on_unload_hook_fires(self) -> None:
        """Unloading a plugin should trigger the on_unload hook."""
        hooks = PluginHooks()
        events: list[str] = []
        hooks.register("on_unload", lambda **kw: events.append(kw["plugin_id"]))

        loader = PluginLoader(plugin_dirs=[FIXTURES_DIR], hooks=hooks)
        manifest = PluginManifest.from_file(TEST_MANIFEST_PATH)
        loader.load(manifest)
        loader.unload("echo-tool")
        assert events == ["echo-tool"]


# ===================================================================
# End-to-end: real plugin test
# ===================================================================


class TestRealPlugin:
    """End-to-end test using the fixture plugin."""

    def test_full_lifecycle(self) -> None:
        """discover -> load -> execute -> unload cycle."""
        loader = PluginLoader(plugin_dirs=[FIXTURES_DIR])

        # Discover
        manifests = loader.discover()
        assert len(manifests) >= 1

        echo_manifest = next(m for m in manifests if m.id == "echo-tool")

        # Validate
        issues = loader.validate(echo_manifest)
        assert issues == [], f"Unexpected issues: {issues}"

        # Load
        tool = loader.load(echo_manifest)
        assert isinstance(tool, BaseTool)
        assert tool.name == "echo_tool"
        assert "echo" in tool.supported_operations

        # Execute
        from geospark.protocol.schema import SpatialOperation, SpatialQuery

        query = SpatialQuery(operation=SpatialOperation.GEOCODE)
        result = tool.execute(query)
        assert "echo:geocode" in (result.spatial_context.summary or "")

        # Unload
        loader.unload("echo-tool")
        assert "echo-tool" not in loader.loaded_plugins
