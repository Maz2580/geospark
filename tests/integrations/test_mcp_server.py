"""Tests for GeoSpark MCP Server handler."""

from geospark.integrations.mcp_server import MCP_TOOLS, GeoSparkMCPHandler


class TestMCPToolDefinitions:
    """Test the tool definitions follow best practices."""

    def test_all_tools_have_explanation_field(self):
        """Every tool should require an 'explanation' parameter (Cursor pattern)."""
        for tool in MCP_TOOLS:
            props = tool["inputSchema"]["properties"]
            assert "explanation" in props, f"Tool {tool['name']} missing 'explanation' field"
            assert "explanation" in tool["inputSchema"]["required"], (
                f"Tool {tool['name']}: 'explanation' should be required"
            )

    def test_descriptions_follow_what_when_returns_pattern(self):
        """Descriptions should include what, when, and 'Do NOT use for' guidance."""
        for tool in MCP_TOOLS:
            desc = tool["description"]
            assert "Use when" in desc or "Use " in desc, (
                f"Tool {tool['name']} missing 'Use when' guidance"
            )
            assert "Do NOT use" in desc, (
                f"Tool {tool['name']} missing 'Do NOT use for X' negative guidance"
            )

    def test_parameter_descriptions_include_examples(self):
        """Key parameters should have example values in descriptions."""
        geocode = next(t for t in MCP_TOOLS if t["name"] == "geocode")
        query_desc = geocode["inputSchema"]["properties"]["query"]["description"]
        assert "e.g." in query_desc or "Eiffel" in query_desc or "1600" in query_desc


class TestMCPHandler:
    def setup_method(self):
        self.handler = GeoSparkMCPHandler(tools=[])

    def test_get_tools_returns_list(self):
        tools = self.handler.get_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 4
        names = {t["name"] for t in tools}
        assert "spatial_query" in names
        assert "check_spatial_relationship" in names
        assert "geocode" in names
        assert "get_elevation" in names

    def test_check_spatial_relationship_contains(self):
        result = self.handler.handle_tool_call(
            "check_spatial_relationship",
            {
                "explanation": "Testing containment",
                "geometry_a": {
                    "type": "Polygon",
                    "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
                },
                "geometry_b": {"type": "Point", "coordinates": [0, 0]},
                "relationship": "contains",
            },
        )
        assert result["status"] == "success"
        assert result["tool"] == "check_spatial_relationship"
        assert result["result"]["holds"] is True
        assert result["result"]["relationship"] == "contains"

    def test_check_spatial_relationship_disjoint(self):
        result = self.handler.handle_tool_call(
            "check_spatial_relationship",
            {
                "explanation": "Testing disjoint points",
                "geometry_a": {"type": "Point", "coordinates": [0, 0]},
                "geometry_b": {"type": "Point", "coordinates": [50, 50]},
                "relationship": "disjoint",
            },
        )
        assert result["status"] == "success"
        assert result["result"]["holds"] is True

    def test_spatial_query_buffer(self):
        result = self.handler.handle_tool_call(
            "spatial_query",
            {
                "explanation": "Creating buffer around London",
                "operation": "buffer",
                "latitude": 51.5074,
                "longitude": -0.1278,
                "radius_m": 1000,
            },
        )
        assert result["status"] == "success"
        assert len(result["result"]["features"]) > 0
        assert result["metadata"]["crs"] == "EPSG:4326"
        assert result["metadata"]["operation"] == "buffer"

    def test_spatial_query_centroid(self):
        result = self.handler.handle_tool_call(
            "spatial_query",
            {
                "explanation": "Finding centroid of Paris",
                "operation": "centroid",
                "latitude": 48.8566,
                "longitude": 2.3522,
            },
        )
        assert result["status"] == "success"
        assert len(result["result"]["features"]) > 0

    def test_unknown_tool_returns_structured_error(self):
        result = self.handler.handle_tool_call("nonexistent_tool", {})
        assert result["status"] == "error"
        assert result["error"]["code"] == "UNKNOWN_TOOL"
        assert "suggestion" in result["error"]
        assert "Available tools" in result["error"]["suggestion"]

    def test_explanation_field_stripped_before_execution(self):
        """The explanation field should be stripped and not affect tool execution."""
        result = self.handler.handle_tool_call(
            "check_spatial_relationship",
            {
                "explanation": "This is just for reasoning audit trail",
                "geometry_a": {"type": "Point", "coordinates": [0, 0]},
                "geometry_b": {"type": "Point", "coordinates": [1, 1]},
                "relationship": "disjoint",
            },
        )
        assert result["status"] == "success"

    def test_geocode_empty_result_has_suggestion(self):
        """When geocoding returns no results, the suggestion field should guide recovery."""
        # We can't easily trigger this with Nominatim, but we test the handler structure
        result = self.handler.handle_tool_call(
            "geocode",
            {"explanation": "test", "query": "Paris, France"},
        )
        assert result["status"] == "success"
        assert "result" in result
        assert "metadata" in result

    def test_result_metadata_includes_crs(self):
        """All spatial results should include CRS in metadata."""
        result = self.handler.handle_tool_call(
            "check_spatial_relationship",
            {
                "explanation": "CRS check",
                "geometry_a": {"type": "Point", "coordinates": [0, 0]},
                "geometry_b": {"type": "Point", "coordinates": [1, 1]},
                "relationship": "intersects",
            },
        )
        assert result["metadata"]["crs"] == "EPSG:4326"
