"""Hand-curated catalog of spatial tools + operations for the chat-to-flow builder.

This catalog is injected into the chat-to-flow LLM system prompt so the model
knows which `tool` / `operation` combinations are valid when constructing
Flow steps. Keeping it hand-curated (rather than dynamic from ToolRegistry)
lets us keep the prompt compact and emphasise the common shapes that work
well with the runner's parameter-reference syntax.
"""

from __future__ import annotations

TOOL_CATALOG: str = """\
Available spatial tools and operations. Use these in the `tool` and `operation`
arguments of add_step. Parameter reference syntax: "{step_id.field}" resolves
to the named field of a prior step's result at runtime.

geocoder
  - geocode: address -> coordinates + bounds. Params: {"address": "Paris, France"}

reverse_geocoder
  - reverse_geocode: coordinates -> address. Params: {"lat": 48.86, "lon": 2.35}

spatial_reasoner
  - distance: geodesic distance between two points.
      Params: {"origin_ref": "{geocode_a.geometry}", "destination_ref": "{geocode_b.geometry}"}
  - buffer: create a buffer polygon around a geometry.
      Params: {"geometry_ref": "{step.geometry}", "radius_m": 1000}
  - topology: check a topological predicate between two geometries.
      Params: {"a_ref": "{step_a.geometry}", "b_ref": "{step_b.geometry}",
               "predicate": "contains|intersects|within|touches|crosses|overlaps|disjoint"}
  - area: compute geodesic area of a polygon. Params: {"geometry_ref": "{step.geometry}"}
  - centroid: get centroid. Params: {"geometry_ref": "{step.geometry}"}

terrain
  - elevation: terrain height for a location.
      Params: {"geometry_ref": "{step.geometry}"}  OR  {"lat": 48.86, "lon": 2.35}

ndvi
  - ndvi: compute NDVI for an area. Params: {"geometry_ref": "{step.geometry}"}

spectral_indices
  - ndvi | ndwi | ndbi | msavi | evi | savi: vegetation / water / built-up indices.
      Params: {"geometry_ref": "{step.geometry}"}

satellite
  - search: STAC scene search.
      Params: {"geometry_ref": "{step.geometry}", "date_range": ["2024-01-01", "2024-12-31"]}

router
  - route: OSRM routing.
      Params: {"origin_ref": "{origin.geometry}", "destination_ref": "{dest.geometry}"}

change_detection
  - change: pixel-level change detection between two dates.
      Params: {"geometry_ref": "{step.geometry}", "before_date": "2020-01-01", "after_date": "2024-01-01"}

For pure LLM / interpretation / alert steps that do not need a tool, leave
`tool` and `operation` as empty strings ("") and put guidance in
`agent_instructions` instead.
"""


__all__ = ["TOOL_CATALOG"]
