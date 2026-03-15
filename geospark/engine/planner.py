"""
Query Planner.

Decomposes complex spatial queries into ordered operation chains,
enabling multi-step spatial analysis pipelines.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from geospark.protocol.schema import SpatialOperation, SpatialQuery


class PlannedStep(BaseModel):
    """A single step in a query execution plan."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    operation: SpatialOperation
    query: SpatialQuery
    depends_on: list[str] = Field(default_factory=list)


class QueryPlanner:
    """
    Decomposes complex queries into ordered operation chains.

    Provides plan/optimize workflow:
    1. plan() breaks a query into PlannedSteps
    2. optimize() reorders/merges steps for efficiency

    Usage:
        planner = QueryPlanner()
        steps = planner.plan(query)
        steps = planner.optimize(steps)
    """

    # Operations that can be parallelised (no geometry dependency)
    _INDEPENDENT_OPS: ClassVar[set[str]] = {"geocode", "reverse_geocode", "elevation"}

    # Operations that must run after geometry is available
    _GEOMETRY_OPS: ClassVar[set[str]] = {
        "buffer", "centroid", "convex_hull", "area", "distance",
    }

    def plan(self, query: SpatialQuery) -> list[PlannedStep]:
        """
        Decompose a query into ordered execution steps.

        Args:
            query: The spatial query to plan.

        Returns:
            Ordered list of PlannedSteps ready for execution.
        """
        steps: list[PlannedStep] = []

        # Check metadata for chained operations
        chain = (query.metadata or {}).get("chain")
        if chain and isinstance(chain, list):
            return self._plan_chain(query, chain)

        # Single-step passthrough for simple queries
        steps.append(PlannedStep(operation=query.operation, query=query))
        return steps

    def _plan_chain(
        self, base_query: SpatialQuery, chain: list[dict[str, Any]]
    ) -> list[PlannedStep]:
        """Build a multi-step plan from a chain definition.

        Args:
            base_query: The original query providing geometry/crs context.
            chain: List of dicts, each with at least an ``operation`` key.

        Returns:
            Ordered list of PlannedSteps with dependency edges.
        """
        steps: list[PlannedStep] = []
        prev_id: str | None = None

        for item in chain:
            op = SpatialOperation(item["operation"])
            step_query = base_query.model_copy(
                update={"operation": op, "metadata": item.get("metadata")},
            )
            step = PlannedStep(
                operation=op,
                query=step_query,
                depends_on=[prev_id] if prev_id else [],
            )
            steps.append(step)
            prev_id = step.id

        return steps

    def optimize(self, steps: list[PlannedStep]) -> list[PlannedStep]:
        """
        Reorder and merge steps for efficiency.

        Current optimisations:
        - Move independent operations before geometry-dependent ones.
        - Remove duplicate consecutive operations.

        Args:
            steps: The planned steps to optimize.

        Returns:
            Optimized list of PlannedSteps.
        """
        if len(steps) <= 1:
            return steps

        # Separate independent and dependent steps
        independent: list[PlannedStep] = []
        dependent: list[PlannedStep] = []

        for step in steps:
            if (
                step.operation.value in self._INDEPENDENT_OPS
                and not step.depends_on
            ):
                independent.append(step)
            else:
                dependent.append(step)

        # Deduplicate consecutive identical operations
        deduped: list[PlannedStep] = []
        for step in dependent:
            if deduped and deduped[-1].operation == step.operation:
                continue
            deduped.append(step)

        return independent + deduped
