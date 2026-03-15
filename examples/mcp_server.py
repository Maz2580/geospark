"""Run GeoSpark as an MCP server for Claude, ChatGPT, or any MCP-compatible AI."""
from __future__ import annotations

from geospark.integrations.mcp_server import GeoSparkMCPHandler

# Initialize the MCP handler (loads spatial reasoning + geocoding tools)
handler = GeoSparkMCPHandler()

# List available tools (these are what the AI sees)
tools = handler.get_tools()
print(f"GeoSpark MCP server ready with {len(tools)} tools:\n")
for tool in tools:
    print(f"  - {tool['name']}: {tool['description'][:70]}...")

# Example: Handle a topology check tool call from the AI
# (In production, this comes from the MCP protocol transport)
print("\n--- Topology Check ---")
result = handler.handle_tool_call(
    "check_spatial_relationship",
    {
        "explanation": "Checking if a point is inside a polygon",
        "geometry_a": {
            "type": "Polygon",
            "coordinates": [
                [[2.29, 48.85], [2.30, 48.85], [2.30, 48.86], [2.29, 48.86], [2.29, 48.85]]
            ],
        },
        "geometry_b": {"type": "Point", "coordinates": [2.295, 48.855]},
        "relationship": "contains",
    },
)
print(f"Status: {result['status']}")
print(f"Contains? {result['result']['holds']}")

# Example: Spatial query (buffer operation)
print("\n--- Spatial Query (Buffer) ---")
result = handler.handle_tool_call(
    "spatial_query",
    {
        "explanation": "Creating a 1km buffer around the Eiffel Tower for proximity analysis",
        "operation": "buffer",
        "latitude": 48.8584,
        "longitude": 2.2945,
        "radius_m": 1000,
    },
)
print(f"Status: {result['status']}")
print(f"Tool: {result['tool']}")
if result["status"] == "success":
    print(f"CRS: {result['metadata']['crs']}")
