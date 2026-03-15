"""
GeoSpark Flow Builder — Programmatic and template-based flow construction.

Provides a fluent API for assembling flows step by step, plus factory
methods for loading pre-built templates.
"""

from __future__ import annotations

import uuid
from typing import Any

from geospark.flows.flow_schema import Flow, FlowRoute, FlowStep, FlowTrigger


class FlowBuilderError(Exception):
    """Raised when the builder encounters an invalid configuration."""


class FlowBuilder:
    """Build flows programmatically with a fluent chaining API.

    Usage:
        flow = (
            FlowBuilder()
            .add_step("geocode", tool="geocoder", operation="geocode",
                       parameters={"address": "Paris, France"})
            .add_step("ndvi", tool="ndvi", operation="ndvi",
                       depends_on=["geocode"])
            .add_route("ndvi", "alert", condition="if NDVI < 0.3")
            .build("Vegetation Monitor", description="Check crop health")
        )
    """

    def __init__(self) -> None:
        self._steps: list[FlowStep] = []
        self._step_ids: set[str] = set()
        self._trigger: FlowTrigger = FlowTrigger(trigger_type="manual")
        self._metadata: dict[str, Any] = {}

    def add_step(
        self,
        name: str,
        *,
        step_id: str | None = None,
        tool: str | None = None,
        operation: str | None = None,
        parameters: dict[str, Any] | None = None,
        agent_instructions: str = "",
        depends_on: list[str] | None = None,
        memory_scope: str = "flow",
    ) -> FlowBuilder:
        """Add a step to the flow.

        Args:
            name: Human-readable step name.
            step_id: Unique step identifier (auto-generated from name if omitted).
            tool: Tool name to execute (None for pure LLM steps).
            operation: SpatialOperation value.
            parameters: Parameters to pass to the tool.
            agent_instructions: Mini system prompt for LLM steps.
            depends_on: List of step IDs this step depends on.
            memory_scope: ``"step"`` or ``"flow"`` scoping for result memory.

        Returns:
            self, for method chaining.

        Raises:
            FlowBuilderError: If the step_id already exists.
        """
        sid = step_id or name.lower().replace(" ", "_")

        if sid in self._step_ids:
            raise FlowBuilderError(f"Duplicate step ID: '{sid}'")

        step = FlowStep(
            id=sid,
            name=name,
            tool=tool,
            operation=operation,
            parameters=parameters or {},
            agent_instructions=agent_instructions,
            depends_on=depends_on or [],
            memory_scope=memory_scope,  # type: ignore[arg-type]
        )
        self._steps.append(step)
        self._step_ids.add(sid)
        return self

    def add_route(
        self,
        from_step: str,
        to_step: str,
        condition: str,
        description: str = "",
    ) -> FlowBuilder:
        """Add a conditional route between steps.

        Args:
            from_step: Source step ID.
            to_step: Target step ID.
            condition: Natural-language condition (e.g. ``"if NDVI < 0.3"``).
            description: Human-readable description of the route.

        Returns:
            self, for method chaining.

        Raises:
            FlowBuilderError: If the source step does not exist.
        """
        source = self._find_step(from_step)
        if source is None:
            raise FlowBuilderError(
                f"Cannot add route: source step '{from_step}' not found"
            )

        route = FlowRoute(
            condition=condition,
            target_step_id=to_step,
            description=description,
        )
        source.routes.append(route)
        return self

    def set_trigger(
        self,
        trigger_type: str = "manual",
        schedule: str | None = None,
        event_type: str | None = None,
    ) -> FlowBuilder:
        """Set the flow trigger.

        Args:
            trigger_type: ``"manual"``, ``"schedule"``, or ``"event"``.
            schedule: Cron expression (required for ``"schedule"``).
            event_type: Webhook event name (required for ``"event"``).

        Returns:
            self, for method chaining.
        """
        self._trigger = FlowTrigger(
            trigger_type=trigger_type,  # type: ignore[arg-type]
            schedule=schedule,
            event_type=event_type,
        )
        return self

    def set_metadata(self, **kwargs: Any) -> FlowBuilder:
        """Set arbitrary metadata on the flow.

        Returns:
            self, for method chaining.
        """
        self._metadata.update(kwargs)
        return self

    def build(self, name: str, description: str = "") -> Flow:
        """Build the final Flow object.

        Args:
            name: Flow name.
            description: Flow description.

        Returns:
            The assembled Flow.

        Raises:
            FlowBuilderError: If no steps have been added.
        """
        if not self._steps:
            raise FlowBuilderError("Cannot build a flow with no steps")

        return Flow(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            steps=list(self._steps),
            trigger=self._trigger,
            metadata=dict(self._metadata),
        )

    @classmethod
    def from_template(cls, template_name: str, **overrides: Any) -> Flow:
        """Create a flow from a pre-built template.

        Args:
            template_name: Name of the template to load.
            **overrides: Parameter overrides to apply to the template.

        Returns:
            A Flow built from the template.

        Raises:
            FlowBuilderError: If the template name is unknown.
        """
        from geospark.flows.templates import get_template

        return get_template(template_name, **overrides)

    def _find_step(self, step_id: str) -> FlowStep | None:
        """Look up a step by ID in the builder's current list.

        Args:
            step_id: The step identifier.

        Returns:
            The matching FlowStep, or None.
        """
        for step in self._steps:
            if step.id == step_id:
                return step
        return None
