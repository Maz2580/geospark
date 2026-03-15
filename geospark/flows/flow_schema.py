"""
GeoSpark Flows — Schema definitions for AI-powered spatial workflows.

Pydantic models that define the structure of flows, steps, routes,
triggers, and run records. These are the building blocks of GeoSpark's
workflow automation system.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class FlowTrigger(BaseModel):
    """Defines how a flow is triggered.

    Supports manual execution, cron-scheduled runs, and event-driven
    (webhook) triggers.
    """

    trigger_type: Literal["manual", "schedule", "event"] = "manual"
    schedule: str | None = None  # cron expression for scheduled triggers
    event_type: str | None = None  # webhook event name for event triggers


class FlowRoute(BaseModel):
    """A conditional route between flow steps.

    Routes allow branching logic within a flow. The condition is expressed
    in natural language (e.g., "if NDVI < 0.3") and evaluated against the
    current step context.
    """

    condition: str  # natural language condition: "if NDVI < 0.3"
    target_step_id: str
    description: str = ""


class FlowStep(BaseModel):
    """A single step in a flow.

    A step can execute a tool (spatial operation) or be a pure LLM step
    guided by agent_instructions. Steps can depend on other steps and
    include conditional routes for branching.
    """

    id: str
    name: str  # human-readable name, e.g. "Calculate NDVI"
    tool: str | None = None  # tool name (None for pure LLM steps)
    operation: str | None = None  # SpatialOperation value
    parameters: dict[str, Any] = Field(default_factory=dict)
    agent_instructions: str = ""  # mini system prompt for this step
    routes: list[FlowRoute] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)  # step IDs this depends on
    memory_scope: Literal["step", "flow"] = "flow"


class FlowRun(BaseModel):
    """A record of a single flow execution.

    Tracks the status, timing, per-step results, and any errors that
    occurred during a flow run.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    flow_id: str
    status: Literal["pending", "running", "completed", "failed", "paused"] = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    step_results: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    current_step_id: str | None = None


class Flow(BaseModel):
    """A complete flow definition.

    A flow is a directed acyclic graph (DAG) of steps that execute in
    dependency order. Each step can run a spatial tool, evaluate conditions,
    and route to downstream steps.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    steps: list[FlowStep]
    trigger: FlowTrigger = Field(default_factory=lambda: FlowTrigger(trigger_type="manual"))
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def get_step(self, step_id: str) -> FlowStep | None:
        """Look up a step by its ID.

        Args:
            step_id: The unique identifier of the step.

        Returns:
            The matching FlowStep, or None if not found.
        """
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    @property
    def step_ids(self) -> list[str]:
        """Return all step IDs in definition order."""
        return [step.id for step in self.steps]
