"""
GeoSpark Flow Templates — Pre-built workflow templates for common spatial tasks.

Templates provide ready-to-use flow definitions that can be customised
via parameter overrides. They serve as both starting points for users
and reference implementations of the Flows API.
"""

from __future__ import annotations

from typing import Any

from geospark.flows.flow_schema import Flow, FlowRoute, FlowStep, FlowTrigger

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, Any] = {}


def _register(name: str):
    """Decorator to register a template builder function."""

    def decorator(func):
        _TEMPLATES[name] = func
        return func

    return decorator


def get_template(name: str, **overrides: Any) -> Flow:
    """Load a template by name with optional parameter overrides.

    Args:
        name: Template name (e.g. ``"vegetation_monitor"``).
        **overrides: Key-value overrides for template parameters.

    Returns:
        A fully-constructed Flow.

    Raises:
        ValueError: If the template name is unknown.
    """
    builder = _TEMPLATES.get(name)
    if builder is None:
        available = ", ".join(sorted(_TEMPLATES.keys()))
        raise ValueError(
            f"Unknown template '{name}'. Available: {available}"
        ) from None
    return builder(**overrides)


def list_templates() -> list[str]:
    """Return the names of all registered templates.

    Returns:
        Sorted list of template names.
    """
    return sorted(_TEMPLATES.keys())


# ---------------------------------------------------------------------------
# Vegetation Monitor
# ---------------------------------------------------------------------------


@_register("vegetation_monitor")
def _vegetation_monitor(
    address: str = "Valencia, Spain",
    ndvi_threshold: float = 0.3,
    **kwargs: Any,
) -> Flow:
    """Monitor vegetation health: geocode -> NDVI -> threshold check -> alert.

    Args:
        address: The area to monitor.
        ndvi_threshold: NDVI value below which an alert is raised.
        **kwargs: Additional metadata.

    Returns:
        A vegetation monitoring Flow.
    """
    return Flow(
        name="Vegetation Monitor",
        description=(
            f"Monitor vegetation health for {address}. "
            f"Alert when NDVI drops below {ndvi_threshold}."
        ),
        steps=[
            FlowStep(
                id="geocode",
                name="Geocode Area",
                tool="geocoder",
                operation="geocode",
                parameters={"address": address},
            ),
            FlowStep(
                id="ndvi",
                name="Calculate NDVI",
                tool="ndvi",
                operation="ndvi",
                parameters={"geometry_ref": "{geocode.geometry}"},
                depends_on=["geocode"],
            ),
            FlowStep(
                id="threshold_check",
                name="Check NDVI Threshold",
                agent_instructions=(
                    f"Evaluate whether the NDVI value is below {ndvi_threshold}. "
                    "If so, flag the area for review."
                ),
                parameters={"ndvi_ref": "{ndvi.ndvi_value}"},
                depends_on=["ndvi"],
                routes=[
                    FlowRoute(
                        condition=f"if ndvi < {ndvi_threshold}",
                        target_step_id="alert",
                        description="Route to alert when vegetation is stressed",
                    ),
                ],
            ),
            FlowStep(
                id="alert",
                name="Generate Alert",
                agent_instructions=(
                    "Generate a vegetation stress alert report summarising "
                    "the NDVI findings and recommended next steps."
                ),
                depends_on=["threshold_check"],
            ),
        ],
        trigger=FlowTrigger(trigger_type="manual"),
        metadata={"template": "vegetation_monitor", **kwargs},
    )


# ---------------------------------------------------------------------------
# Distance Analysis
# ---------------------------------------------------------------------------


@_register("distance_analysis")
def _distance_analysis(
    origin: str = "Paris, France",
    destination: str = "London, UK",
    max_distance_km: float = 500.0,
    **kwargs: Any,
) -> Flow:
    """Analyse distance between two locations: geocode both -> distance -> compare.

    Args:
        origin: Starting location address.
        destination: Target location address.
        max_distance_km: Distance threshold for the comparison step.
        **kwargs: Additional metadata.

    Returns:
        A distance analysis Flow.
    """
    return Flow(
        name="Distance Analysis",
        description=(
            f"Calculate distance from {origin} to {destination} and "
            f"compare against {max_distance_km} km threshold."
        ),
        steps=[
            FlowStep(
                id="geocode_origin",
                name="Geocode Origin",
                tool="geocoder",
                operation="geocode",
                parameters={"address": origin},
            ),
            FlowStep(
                id="geocode_destination",
                name="Geocode Destination",
                tool="geocoder",
                operation="geocode",
                parameters={"address": destination},
            ),
            FlowStep(
                id="calculate_distance",
                name="Calculate Distance",
                tool="spatial_reasoner",
                operation="distance",
                parameters={
                    "origin_ref": "{geocode_origin.geometry}",
                    "destination_ref": "{geocode_destination.geometry}",
                },
                depends_on=["geocode_origin", "geocode_destination"],
            ),
            FlowStep(
                id="compare_threshold",
                name="Compare Distance Threshold",
                agent_instructions=(
                    f"Check whether the calculated distance exceeds "
                    f"{max_distance_km} km and summarise the result."
                ),
                parameters={"distance_ref": "{calculate_distance.distance_km}"},
                depends_on=["calculate_distance"],
                routes=[
                    FlowRoute(
                        condition=f"if distance > {max_distance_km}",
                        target_step_id="over_threshold",
                        description="Distance exceeds threshold",
                    ),
                ],
            ),
        ],
        trigger=FlowTrigger(trigger_type="manual"),
        metadata={"template": "distance_analysis", **kwargs},
    )


# ---------------------------------------------------------------------------
# Area Survey
# ---------------------------------------------------------------------------


@_register("area_survey")
def _area_survey(
    address: str = "Zurich, Switzerland",
    buffer_m: float = 1000.0,
    **kwargs: Any,
) -> Flow:
    """Survey an area: geocode -> elevation -> buffer -> report.

    Args:
        address: The area to survey.
        buffer_m: Buffer distance in metres.
        **kwargs: Additional metadata.

    Returns:
        An area survey Flow.
    """
    return Flow(
        name="Area Survey",
        description=(
            f"Survey the area around {address}: elevation, "
            f"{buffer_m}m buffer, and summary report."
        ),
        steps=[
            FlowStep(
                id="geocode",
                name="Geocode Area",
                tool="geocoder",
                operation="geocode",
                parameters={"address": address},
            ),
            FlowStep(
                id="elevation",
                name="Check Elevation",
                tool="terrain",
                operation="elevation",
                parameters={"geometry_ref": "{geocode.geometry}"},
                depends_on=["geocode"],
            ),
            FlowStep(
                id="buffer",
                name="Create Buffer",
                tool="spatial_reasoner",
                operation="buffer",
                parameters={
                    "geometry_ref": "{geocode.geometry}",
                    "radius_m": buffer_m,
                },
                depends_on=["geocode"],
            ),
            FlowStep(
                id="report",
                name="Generate Report",
                agent_instructions=(
                    "Compile a survey report combining the elevation data "
                    "and buffer zone information for the target area."
                ),
                depends_on=["elevation", "buffer"],
            ),
        ],
        trigger=FlowTrigger(trigger_type="manual"),
        metadata={"template": "area_survey", **kwargs},
    )
