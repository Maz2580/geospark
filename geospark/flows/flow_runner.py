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
from datetime import datetime, timezone
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

# A parameter that is still an unresolved "{step.key}" reference
_REF = re.compile(r"\{[\w.]+\}")

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
        flow_run.started_at = datetime.now(timezone.utc)
        self._persist_run(flow_run)

        context: dict[str, Any] = {}

        try:
            ordered_steps = self._topological_sort(flow.steps)
        except FlowRunnerError as err:
            flow_run.status = "failed"
            flow_run.errors.append(str(err))
            flow_run.completed_at = datetime.now(timezone.utc)
            self._persist_run(flow_run)
            return flow_run

        for step in ordered_steps:
            flow_run.current_step_id = step.id
            # A step whose input failed can't run; say which input, instead of running it on nothing
            broken = [d for d in step.depends_on if context.get(d, {}).get("status") in ("error", "skipped")]
            if broken:
                result = {"status": "skipped", "errors": [f"Not run: it needs {', '.join(broken)}, which did not succeed."]}
                context[step.id] = result
                flow_run.step_results[step.id] = result
                continue
            try:
                result = self._execute_step(step, context)
                context[step.id] = result
                flow_run.step_results[step.id] = result
                if result.get("status") == "error":
                    flow_run.errors.extend(f"Step '{step.id}': {e}" for e in result.get("errors") or ["failed"])
                self._persist_run(flow_run)

                # Evaluate routes and add routed steps to context
                for route in step.routes:
                    if self._evaluate_condition(route.condition, context):
                        context[f"_route_{step.id}_{route.target_step_id}"] = True

            except Exception as err:
                flow_run.status = "failed"
                flow_run.errors.append(f"Step '{step.id}' failed: {err}")
                flow_run.completed_at = datetime.now(timezone.utc)
                flow_run.current_step_id = None
                self._persist_run(flow_run)
                return flow_run

        # A run is complete only if every step did its job; a run whose steps all errored used to
        # report "completed"
        flow_run.status = "failed" if flow_run.errors else "completed"
        flow_run.completed_at = datetime.now(timezone.utc)
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
            except ValueError:
                return self._step_error(step, start_time, f"Unknown operation '{step.operation}'.")

            unresolved = [k for k, v in resolved_params.items() if isinstance(v, str) and _REF.fullmatch(v)]
            if unresolved:
                return self._step_error(step, start_time, "Missing input: " + ", ".join(
                    f"{k}={resolved_params[k]}" for k in unresolved))
            try:
                query = self._build_query(op, step, resolved_params)
            except ValueError as err:
                return self._step_error(step, start_time, f"Invalid parameters: {err}")

            self._ensure_tool(step.tool)
            result: SpatialResult = self.engine.execute(query)
            errors = list(result.errors)
            if errors:
                from geospark.tools.registry import TOOL_STATUS

                status, what = TOOL_STATUS.get(step.tool, ("ready", ""))
                if status in ("partial", "planned"):
                    errors.append(f"The {step.tool} tool is {status}: {what}.")
            warnings = list(result.warnings)
            if not errors:
                from geospark.tools.registry import TOOL_STATUS

                status, what = TOOL_STATUS.get(step.tool, ("ready", ""))
                if status in ("partial", "planned"):
                    warnings.append(f"The {step.tool} tool is {status}: {what}.")
            first = result.features[0] if result.features else None
            elapsed = (time.time() - start_time) * 1000
            return {
                "status": "error" if errors else "success",
                "tool": step.tool,
                "operation": step.operation,
                # The first feature's geometry and values, for later steps' {step.key} references
                "geometry": first.geometry if first else None,
                "values": dict(first.properties) if first else {},
                "features": [f.model_dump() for f in result.features],
                "spatial_context": result.spatial_context.model_dump(),
                "errors": errors,
                "warnings": warnings,
                "execution_time_ms": elapsed,
            }

        unresolved = [k for k, v in resolved_params.items() if isinstance(v, str) and _REF.fullmatch(v)]
        if unresolved:  # e.g. {ndvi.ndvi_value} when the NDVI step produced no value
            return self._step_error(step, start_time, "Missing input: " + ", ".join(
                f"{k}={resolved_params[k]} (the step produced no such value)" for k in unresolved))

        # Instruction step: no tool runs. Its inputs and route conditions are resolved, and the
        # instruction is recorded for a person or model to act on; it is not executed here.
        elapsed = (time.time() - start_time) * 1000
        return {
            "status": "success",
            "agent_instructions": step.agent_instructions,
            "parameters": resolved_params,
            # The step's own inputs come first: "if distance > 500" reads its "distance" parameter
            "routes_taken": [r.target_step_id for r in step.routes
                             if self._evaluate_condition(r.condition, {step.id: resolved_params, **context})],
            "note": "Instruction step: recorded, not executed by a model.",
            "execution_time_ms": elapsed,
        }

    # Parameter names templates and the flow builder use, and the query field each one sets
    _QUERY_TEXT = ("address", "query", "place")
    _GEOMETRY = ("geometry", "geometry_ref", "origin", "origin_ref")
    _GEOMETRY_B = ("geometry_b", "geometry_b_ref", "destination", "destination_ref")

    def _build_query(self, op: SpatialOperation, step: FlowStep, params: dict[str, Any]) -> SpatialQuery:
        metadata: dict[str, Any] = {"flow_step": step.id, **params}
        fields: dict[str, Any] = {
            k: v for k, v in params.items()
            if k in SpatialQuery.model_fields and k not in ("operation", "metadata", "geometry")
        }
        text = next((params[k] for k in self._QUERY_TEXT if isinstance(params.get(k), str)), None)
        if text:
            metadata["query"] = text
        geometry = next((params[k] for k in self._GEOMETRY if isinstance(params.get(k), dict)), None)
        if geometry:
            fields["geometry"] = geometry
        geometry_b = next((params[k] for k in self._GEOMETRY_B if isinstance(params.get(k), dict)), None)
        if geometry_b:
            metadata["geometry_b"] = geometry_b
        return SpatialQuery(operation=op, metadata=metadata, **fields)

    def _ensure_tool(self, tool: str) -> None:
        """Load the step's tool if the engine doesn't have it (a default Engine has none)."""
        if tool == "spatial_reasoner":
            return
        registry = getattr(self.engine, "tool_registry", None)
        try:
            if registry is not None and tool not in self.engine.available_tools:
                registry.load_tool(tool)
        except Exception as err:  # unknown tool: the engine reports it when the step runs
            logger.debug("Could not load tool %s: %s", tool, err)

    @staticmethod
    def _step_error(step: FlowStep, start_time: float, message: str) -> dict[str, Any]:
        return {"status": "error", "tool": step.tool, "operation": step.operation, "errors": [message],
                "execution_time_ms": (time.time() - start_time) * 1000}

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
                        # A key of the step's result, or a value of its first feature ({calc.distance_km})
                        value = step_result.get(result_key)
                        if value is None:
                            value = (step_result.get("values") or {}).get(result_key)
                        resolved[param_key] = param_value if value is None else value
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
