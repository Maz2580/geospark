"""
GeoSpark Flow Runner — Executes flows step by step.

Handles dependency resolution via topological sort, step execution
through the GeoSpark Engine, natural-language condition evaluation,
and flow run lifecycle management.
"""

from __future__ import annotations

import logging
import operator
import re
import time
from collections import deque
from datetime import datetime
from typing import Any

from geospark.engine.core import Engine
from geospark.flows.flow_schema import Flow, FlowRun, FlowStep
from geospark.protocol.schema import SpatialOperation, SpatialQuery, SpatialResult

logger = logging.getLogger(__name__)

# Supported comparison operators for condition evaluation
_OPERATORS: dict[str, Any] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}

# Regex for parsing simple numeric conditions like "NDVI < 0.3"
_CONDITION_PATTERN = re.compile(
    r"(?:if\s+)?(\w+)\s*(<=?|>=?|==|!=)\s*([\d.]+)",
    re.IGNORECASE,
)


class FlowRunnerError(Exception):
    """Raised when a flow execution encounters an unrecoverable error."""


class FlowRunner:
    """Executes GeoSpark flows step by step.

    The runner resolves step dependencies via topological sort, executes
    each step through the GeoSpark Engine (or as a pure-LLM step), evaluates
    route conditions, and assembles the final FlowRun result.

    Usage:
        runner = FlowRunner(engine=Engine())
        run = runner.run(flow)
        print(run.status, run.step_results)
    """

    def __init__(self, engine: Engine | None = None, store: Any | None = None) -> None:
        self.engine = engine or Engine()
        self._store = store  # Optional FlowStore for persistence

    def run(self, flow: Flow) -> FlowRun:
        """Execute a flow, running each step in dependency order.

        Args:
            flow: The Flow definition to execute.

        Returns:
            A FlowRun recording status, results, and errors.
        """
        flow_run = FlowRun(flow_id=flow.id, status="running")
        flow_run.started_at = datetime.utcnow()
        self._persist_run(flow_run)

        context: dict[str, Any] = {}

        try:
            ordered_steps = self._topological_sort(flow.steps)
        except FlowRunnerError as err:
            flow_run.status = "failed"
            flow_run.errors.append(str(err))
            flow_run.completed_at = datetime.utcnow()
            self._persist_run(flow_run)
            return flow_run

        for step in ordered_steps:
            flow_run.current_step_id = step.id
            try:
                result = self._execute_step(step, context)
                context[step.id] = result
                flow_run.step_results[step.id] = result
                self._persist_run(flow_run)

                # Evaluate routes and add routed steps to context
                for route in step.routes:
                    if self._evaluate_condition(route.condition, context):
                        context[f"_route_{step.id}_{route.target_step_id}"] = True

            except Exception as err:
                flow_run.status = "failed"
                flow_run.errors.append(f"Step '{step.id}' failed: {err}")
                flow_run.completed_at = datetime.utcnow()
                flow_run.current_step_id = None
                self._persist_run(flow_run)
                return flow_run

        flow_run.status = "completed"
        flow_run.completed_at = datetime.utcnow()
        flow_run.current_step_id = None
        self._persist_run(flow_run)
        return flow_run

    def _persist_run(self, run: FlowRun) -> None:
        """Persist run state if a store is configured."""
        if self._store is not None:
            try:
                self._store.save_run(run)
            except Exception as err:
                logger.warning("Failed to persist run %s: %s", run.id, err)

    def _execute_step(self, step: FlowStep, context: dict[str, Any]) -> dict[str, Any]:
        """Execute a single flow step.

        If the step specifies a tool and operation, a SpatialQuery is built and
        executed via the engine. Otherwise, the step is treated as a pure-LLM
        step and its agent_instructions are returned as the result.

        Args:
            step: The FlowStep to execute.
            context: Accumulated results from prior steps.

        Returns:
            A dict of result data for this step.
        """
        start_time = time.time()

        # Resolve parameter references like "{step_id.key}"
        resolved_params = self._resolve_parameters(step.parameters, context)

        if step.tool and step.operation:
            # Tool-based step: build a SpatialQuery and execute
            try:
                op = SpatialOperation(step.operation)
            except ValueError as err:
                raise FlowRunnerError(
                    f"Invalid operation '{step.operation}' in step '{step.id}'"
                ) from err

            # Build query kwargs from resolved params that match SpatialQuery fields,
            # excluding 'operation' (already set) and 'metadata' (merged separately).
            query_fields = {
                k: v
                for k, v in resolved_params.items()
                if k in SpatialQuery.model_fields and k not in ("operation", "metadata")
            }
            query = SpatialQuery(
                operation=op,
                metadata={"flow_step": step.id, **resolved_params},
                **query_fields,
            )

            result: SpatialResult = self.engine.execute(query)

            elapsed = (time.time() - start_time) * 1000
            return {
                "status": "error" if result.errors else "success",
                "tool": step.tool,
                "operation": step.operation,
                "features": [f.model_dump() for f in result.features],
                "spatial_context": result.spatial_context.model_dump(),
                "errors": result.errors,
                "execution_time_ms": elapsed,
            }

        # Pure LLM / passthrough step
        elapsed = (time.time() - start_time) * 1000
        return {
            "status": "success",
            "agent_instructions": step.agent_instructions,
            "parameters": resolved_params,
            "execution_time_ms": elapsed,
        }

    def _evaluate_condition(self, condition: str, context: dict[str, Any]) -> bool:
        """Evaluate a natural-language condition against step results.

        Supports simple numeric comparisons of the form
        ``"if <key> <op> <number>"``, where ``<key>`` is searched for
        (case-insensitively) in the flattened context values.

        Args:
            condition: The condition string (e.g. ``"if NDVI < 0.3"``).
            context: Accumulated step results.

        Returns:
            True if the condition is satisfied, False otherwise.
        """
        match = _CONDITION_PATTERN.match(condition.strip())
        if not match:
            # Unrecognised condition format — default to True so the
            # route is taken (safe fallback for complex conditions that
            # will later be handled by an LLM evaluator).
            logger.debug("Could not parse condition '%s'; defaulting to True", condition)
            return True

        key = match.group(1).lower()
        op_str = match.group(2)
        threshold = float(match.group(3))
        cmp = _OPERATORS[op_str]

        # Search context for a matching value
        value = self._find_value_in_context(key, context)
        if value is None:
            logger.debug("Key '%s' not found in context; condition defaults to False", key)
            return False

        try:
            return bool(cmp(float(value), threshold))
        except (ValueError, TypeError):
            return False

    def _find_value_in_context(
        self, key: str, context: dict[str, Any]
    ) -> Any:
        """Recursively search for a key in nested context dicts.

        Args:
            key: The key to search for (case-insensitive).
            context: The context dict to search.

        Returns:
            The first matching value, or None if not found.
        """
        for k, v in context.items():
            if k.lower() == key:
                return v
            if isinstance(v, dict):
                found = self._find_value_in_context(key, v)
                if found is not None:
                    return found
        return None

    def _resolve_parameters(
        self, parameters: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve parameter references of the form ``{step_id.key}``.

        Args:
            parameters: The raw parameter dict (may contain references).
            context: Accumulated step results for lookups.

        Returns:
            A new dict with all references resolved.
        """
        resolved: dict[str, Any] = {}
        for param_key, param_value in parameters.items():
            if isinstance(param_value, str) and param_value.startswith("{") and param_value.endswith("}"):
                ref = param_value[1:-1]  # strip braces
                parts = ref.split(".", 1)
                if len(parts) == 2:
                    step_id, result_key = parts
                    step_result = context.get(step_id, {})
                    if isinstance(step_result, dict):
                        resolved[param_key] = step_result.get(result_key, param_value)
                    else:
                        resolved[param_key] = param_value
                else:
                    resolved[param_key] = context.get(ref, param_value)
            else:
                resolved[param_key] = param_value
        return resolved

    def _topological_sort(self, steps: list[FlowStep]) -> list[FlowStep]:
        """Sort steps by dependency order using Kahn's algorithm.

        Args:
            steps: The list of FlowSteps to sort.

        Returns:
            Steps in a valid execution order.

        Raises:
            FlowRunnerError: If a dependency cycle is detected or a
                dependency references a non-existent step.
        """
        step_map: dict[str, FlowStep] = {s.id: s for s in steps}

        # Validate that all dependencies exist
        for step in steps:
            for dep_id in step.depends_on:
                if dep_id not in step_map:
                    raise FlowRunnerError(
                        f"Step '{step.id}' depends on unknown step '{dep_id}'"
                    ) from None

        # Build in-degree map
        in_degree: dict[str, int] = {s.id: 0 for s in steps}
        for step in steps:
            for _dep_id in step.depends_on:
                in_degree[step.id] += 1

        # Start with zero-dependency steps
        queue: deque[str] = deque(
            sid for sid, deg in in_degree.items() if deg == 0
        )

        ordered: list[FlowStep] = []
        while queue:
            current_id = queue.popleft()
            ordered.append(step_map[current_id])

            # Reduce in-degree for dependents
            for step in steps:
                if current_id in step.depends_on:
                    in_degree[step.id] -= 1
                    if in_degree[step.id] == 0:
                        queue.append(step.id)

        if len(ordered) != len(steps):
            raise FlowRunnerError(
                "Dependency cycle detected in flow steps"
            )

        return ordered
