"""Tests for the GeoSpark Flows module."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from geospark.flows.flow_builder import FlowBuilder, FlowBuilderError
from geospark.flows.flow_runner import FlowRunner, FlowRunnerError
from geospark.flows.flow_schema import (
    Flow,
    FlowRoute,
    FlowRun,
    FlowStep,
    FlowTrigger,
)
from geospark.flows.templates import get_template, list_templates
from geospark.protocol.schema import SpatialContext, SpatialFeature, SpatialResult

# ---------------------------------------------------------------------------
# FlowTrigger
# ---------------------------------------------------------------------------


class TestFlowTrigger:
    """Tests for the FlowTrigger schema."""

    def test_default_trigger_is_manual(self) -> None:
        trigger = FlowTrigger()
        assert trigger.trigger_type == "manual"
        assert trigger.schedule is None
        assert trigger.event_type is None

    def test_schedule_trigger(self) -> None:
        trigger = FlowTrigger(trigger_type="schedule", schedule="0 6 * * *")
        assert trigger.trigger_type == "schedule"
        assert trigger.schedule == "0 6 * * *"

    def test_event_trigger(self) -> None:
        trigger = FlowTrigger(trigger_type="event", event_type="ndvi_alert")
        assert trigger.trigger_type == "event"
        assert trigger.event_type == "ndvi_alert"


# ---------------------------------------------------------------------------
# FlowRoute
# ---------------------------------------------------------------------------


class TestFlowRoute:
    """Tests for the FlowRoute schema."""

    def test_route_creation(self) -> None:
        route = FlowRoute(
            condition="if NDVI < 0.3",
            target_step_id="alert",
            description="Low vegetation alert",
        )
        assert route.condition == "if NDVI < 0.3"
        assert route.target_step_id == "alert"
        assert route.description == "Low vegetation alert"

    def test_route_default_description(self) -> None:
        route = FlowRoute(condition="if x > 1", target_step_id="next")
        assert route.description == ""


# ---------------------------------------------------------------------------
# FlowStep
# ---------------------------------------------------------------------------


class TestFlowStep:
    """Tests for the FlowStep schema."""

    def test_step_with_tool(self) -> None:
        step = FlowStep(
            id="geocode",
            name="Geocode Area",
            tool="geocoder",
            operation="geocode",
            parameters={"address": "Paris"},
        )
        assert step.id == "geocode"
        assert step.tool == "geocoder"
        assert step.operation == "geocode"
        assert step.parameters["address"] == "Paris"
        assert step.depends_on == []
        assert step.memory_scope == "flow"

    def test_pure_llm_step(self) -> None:
        step = FlowStep(
            id="report",
            name="Generate Report",
            agent_instructions="Summarise the spatial findings.",
        )
        assert step.tool is None
        assert step.operation is None
        assert step.agent_instructions == "Summarise the spatial findings."

    def test_step_with_dependencies(self) -> None:
        step = FlowStep(
            id="ndvi",
            name="NDVI Analysis",
            depends_on=["geocode", "satellite"],
        )
        assert step.depends_on == ["geocode", "satellite"]

    def test_step_with_routes(self) -> None:
        route = FlowRoute(condition="if NDVI < 0.3", target_step_id="alert")
        step = FlowStep(
            id="check",
            name="Check",
            routes=[route],
        )
        assert len(step.routes) == 1
        assert step.routes[0].target_step_id == "alert"

    def test_step_memory_scope(self) -> None:
        step = FlowStep(id="s1", name="S1", memory_scope="step")
        assert step.memory_scope == "step"


# ---------------------------------------------------------------------------
# FlowRun
# ---------------------------------------------------------------------------


class TestFlowRun:
    """Tests for the FlowRun schema."""

    def test_default_run(self) -> None:
        run = FlowRun(flow_id="flow-1")
        assert run.id  # auto-generated UUID
        assert run.flow_id == "flow-1"
        assert run.status == "pending"
        assert run.started_at is None
        assert run.completed_at is None
        assert run.step_results == {}
        assert run.errors == []

    def test_run_status_transitions(self) -> None:
        run = FlowRun(flow_id="flow-1")
        assert run.status == "pending"

        run.status = "running"
        run.started_at = datetime.utcnow()
        assert run.status == "running"
        assert run.started_at is not None

        run.status = "completed"
        run.completed_at = datetime.utcnow()
        assert run.status == "completed"
        assert run.completed_at is not None

    def test_run_failed_with_errors(self) -> None:
        run = FlowRun(flow_id="flow-1", status="failed")
        run.errors.append("Step 'geocode' failed: connection timeout")
        assert run.status == "failed"
        assert len(run.errors) == 1

    def test_run_paused(self) -> None:
        run = FlowRun(flow_id="flow-1", status="paused")
        run.current_step_id = "manual_review"
        assert run.status == "paused"
        assert run.current_step_id == "manual_review"


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


class TestFlow:
    """Tests for the Flow schema."""

    def test_minimal_flow(self) -> None:
        flow = Flow(
            name="Test Flow",
            steps=[FlowStep(id="s1", name="Step 1")],
        )
        assert flow.id  # auto-generated
        assert flow.name == "Test Flow"
        assert len(flow.steps) == 1
        assert flow.trigger.trigger_type == "manual"

    def test_flow_with_description_and_metadata(self) -> None:
        flow = Flow(
            name="Complex Flow",
            description="A multi-step workflow",
            steps=[FlowStep(id="s1", name="Step 1")],
            metadata={"version": "1.0", "author": "test"},
        )
        assert flow.description == "A multi-step workflow"
        assert flow.metadata["version"] == "1.0"

    def test_flow_get_step(self) -> None:
        flow = Flow(
            name="Test",
            steps=[
                FlowStep(id="a", name="A"),
                FlowStep(id="b", name="B"),
            ],
        )
        assert flow.get_step("a") is not None
        assert flow.get_step("a").name == "A"
        assert flow.get_step("nonexistent") is None

    def test_flow_step_ids(self) -> None:
        flow = Flow(
            name="Test",
            steps=[
                FlowStep(id="x", name="X"),
                FlowStep(id="y", name="Y"),
                FlowStep(id="z", name="Z"),
            ],
        )
        assert flow.step_ids == ["x", "y", "z"]

    def test_flow_created_at(self) -> None:
        flow = Flow(name="T", steps=[FlowStep(id="s", name="S")])
        assert isinstance(flow.created_at, datetime)


# ---------------------------------------------------------------------------
# FlowBuilder
# ---------------------------------------------------------------------------


class TestFlowBuilder:
    """Tests for the FlowBuilder chaining API."""

    def test_single_step_build(self) -> None:
        flow = (
            FlowBuilder()
            .add_step("Geocode", tool="geocoder", operation="geocode")
            .build("Simple Flow")
        )
        assert flow.name == "Simple Flow"
        assert len(flow.steps) == 1
        assert flow.steps[0].id == "geocode"

    def test_chaining_multiple_steps(self) -> None:
        flow = (
            FlowBuilder()
            .add_step("Geocode", tool="geocoder", operation="geocode")
            .add_step("NDVI", tool="ndvi", operation="ndvi", depends_on=["geocode"])
            .add_step("Report", agent_instructions="Summarise results", depends_on=["ndvi"])
            .build("Pipeline", description="Three-step pipeline")
        )
        assert len(flow.steps) == 3
        assert flow.steps[1].depends_on == ["geocode"]
        assert flow.description == "Three-step pipeline"

    def test_add_route(self) -> None:
        flow = (
            FlowBuilder()
            .add_step("Check", agent_instructions="Evaluate")
            .add_step("Alert", agent_instructions="Send alert")
            .add_route("check", "alert", condition="if NDVI < 0.3")
            .build("Routed Flow")
        )
        assert len(flow.steps[0].routes) == 1
        assert flow.steps[0].routes[0].condition == "if NDVI < 0.3"
        assert flow.steps[0].routes[0].target_step_id == "alert"

    def test_set_trigger(self) -> None:
        flow = (
            FlowBuilder()
            .add_step("S1", tool="geocoder", operation="geocode")
            .set_trigger("schedule", schedule="0 8 * * *")
            .build("Scheduled Flow")
        )
        assert flow.trigger.trigger_type == "schedule"
        assert flow.trigger.schedule == "0 8 * * *"

    def test_set_metadata(self) -> None:
        flow = (
            FlowBuilder()
            .add_step("S1", tool="geocoder", operation="geocode")
            .set_metadata(author="test", version="2.0")
            .build("Meta Flow")
        )
        assert flow.metadata["author"] == "test"
        assert flow.metadata["version"] == "2.0"

    def test_custom_step_id(self) -> None:
        flow = (
            FlowBuilder()
            .add_step("My Step", step_id="custom_id", tool="geocoder", operation="geocode")
            .build("Custom ID Flow")
        )
        assert flow.steps[0].id == "custom_id"

    def test_duplicate_step_id_raises(self) -> None:
        with pytest.raises(FlowBuilderError, match="Duplicate step ID"):
            (
                FlowBuilder()
                .add_step("Step A", step_id="dup")
                .add_step("Step B", step_id="dup")
            )

    def test_route_to_unknown_step_raises(self) -> None:
        with pytest.raises(FlowBuilderError, match=r"source step.*not found"):
            (
                FlowBuilder()
                .add_step("A")
                .add_route("nonexistent", "a", condition="always")
            )

    def test_build_empty_raises(self) -> None:
        with pytest.raises(FlowBuilderError, match="no steps"):
            FlowBuilder().build("Empty")

    def test_from_template(self) -> None:
        flow = FlowBuilder.from_template("vegetation_monitor")
        assert flow.name == "Vegetation Monitor"
        assert len(flow.steps) >= 3


# ---------------------------------------------------------------------------
# FlowRunner — topological sort
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    """Tests for step dependency resolution."""

    def test_sort_no_deps(self) -> None:
        steps = [
            FlowStep(id="a", name="A"),
            FlowStep(id="b", name="B"),
            FlowStep(id="c", name="C"),
        ]
        runner = FlowRunner()
        ordered = runner._topological_sort(steps)
        assert len(ordered) == 3
        ids = [s.id for s in ordered]
        assert set(ids) == {"a", "b", "c"}

    def test_sort_linear_chain(self) -> None:
        steps = [
            FlowStep(id="c", name="C", depends_on=["b"]),
            FlowStep(id="a", name="A"),
            FlowStep(id="b", name="B", depends_on=["a"]),
        ]
        runner = FlowRunner()
        ordered = runner._topological_sort(steps)
        ids = [s.id for s in ordered]
        assert ids.index("a") < ids.index("b") < ids.index("c")

    def test_sort_diamond_deps(self) -> None:
        steps = [
            FlowStep(id="d", name="D", depends_on=["b", "c"]),
            FlowStep(id="b", name="B", depends_on=["a"]),
            FlowStep(id="c", name="C", depends_on=["a"]),
            FlowStep(id="a", name="A"),
        ]
        runner = FlowRunner()
        ordered = runner._topological_sort(steps)
        ids = [s.id for s in ordered]
        assert ids[0] == "a"
        assert ids[-1] == "d"

    def test_cycle_detection(self) -> None:
        steps = [
            FlowStep(id="a", name="A", depends_on=["b"]),
            FlowStep(id="b", name="B", depends_on=["a"]),
        ]
        runner = FlowRunner()
        with pytest.raises(FlowRunnerError, match="cycle"):
            runner._topological_sort(steps)

    def test_unknown_dependency_raises(self) -> None:
        steps = [
            FlowStep(id="a", name="A", depends_on=["missing"]),
        ]
        runner = FlowRunner()
        with pytest.raises(FlowRunnerError, match="unknown step"):
            runner._topological_sort(steps)


# ---------------------------------------------------------------------------
# FlowRunner — condition evaluation
# ---------------------------------------------------------------------------


class TestConditionEvaluation:
    """Tests for natural-language condition evaluation."""

    def test_less_than_true(self) -> None:
        runner = FlowRunner()
        ctx = {"ndvi": 0.2}
        assert runner._evaluate_condition("if ndvi < 0.3", ctx) is True

    def test_less_than_false(self) -> None:
        runner = FlowRunner()
        ctx = {"ndvi": 0.5}
        assert runner._evaluate_condition("if ndvi < 0.3", ctx) is False

    def test_greater_than(self) -> None:
        runner = FlowRunner()
        ctx = {"distance": 750.0}
        assert runner._evaluate_condition("if distance > 500", ctx) is True

    def test_equals(self) -> None:
        runner = FlowRunner()
        ctx = {"count": 10}
        assert runner._evaluate_condition("if count == 10", ctx) is True

    def test_nested_key_lookup(self) -> None:
        runner = FlowRunner()
        ctx = {"step_1": {"ndvi_value": 0.1}}
        assert runner._evaluate_condition("if ndvi_value < 0.3", ctx) is True

    def test_missing_key_returns_false(self) -> None:
        runner = FlowRunner()
        ctx = {"other": 42}
        assert runner._evaluate_condition("if ndvi < 0.3", ctx) is False

    def test_unparseable_condition_returns_true(self) -> None:
        runner = FlowRunner()
        ctx = {}
        assert runner._evaluate_condition("always proceed", ctx) is True


# ---------------------------------------------------------------------------
# FlowRunner — parameter resolution
# ---------------------------------------------------------------------------


class TestParameterResolution:
    """Tests for parameter reference resolution."""

    def test_resolve_simple_reference(self) -> None:
        runner = FlowRunner()
        context = {"geocode": {"geometry": {"type": "Point", "coordinates": [2.35, 48.86]}}}
        params = {"geom": "{geocode.geometry}"}
        resolved = runner._resolve_parameters(params, context)
        assert resolved["geom"] == {"type": "Point", "coordinates": [2.35, 48.86]}

    def test_resolve_non_reference_passthrough(self) -> None:
        runner = FlowRunner()
        params = {"address": "Paris, France", "limit": 10}
        resolved = runner._resolve_parameters(params, {})
        assert resolved["address"] == "Paris, France"
        assert resolved["limit"] == 10

    def test_resolve_missing_reference_keeps_original(self) -> None:
        runner = FlowRunner()
        params = {"val": "{missing_step.result}"}
        resolved = runner._resolve_parameters(params, {})
        assert resolved["val"] == "{missing_step.result}"


# ---------------------------------------------------------------------------
# FlowRunner — full run
# ---------------------------------------------------------------------------


class TestFlowRunExecution:
    """Tests for end-to-end flow execution with mock engine."""

    def _mock_engine(self) -> MagicMock:
        """Create a mock Engine that returns successful SpatialResults."""
        engine = MagicMock()
        engine.execute.return_value = SpatialResult(
            features=[
                SpatialFeature(
                    geometry={"type": "Point", "coordinates": [2.35, 48.86]},
                    properties={"name": "Paris"},
                )
            ],
            spatial_context=SpatialContext(summary="OK"),
        )
        return engine

    def test_run_single_llm_step(self) -> None:
        flow = Flow(
            name="Simple",
            steps=[
                FlowStep(
                    id="report",
                    name="Report",
                    agent_instructions="Generate a report",
                ),
            ],
        )
        runner = FlowRunner()
        run = runner.run(flow)
        assert run.status == "completed"
        assert "report" in run.step_results
        assert run.step_results["report"]["status"] == "success"

    def test_run_tool_step_with_mock_engine(self) -> None:
        engine = self._mock_engine()
        flow = Flow(
            name="Tool Flow",
            steps=[
                FlowStep(
                    id="geocode",
                    name="Geocode",
                    tool="geocoder",
                    operation="geocode",
                ),
            ],
        )
        runner = FlowRunner(engine=engine)
        run = runner.run(flow)
        assert run.status == "completed"
        assert run.step_results["geocode"]["status"] == "success"
        engine.execute.assert_called_once()

    def test_run_with_dependencies(self) -> None:
        engine = self._mock_engine()
        flow = Flow(
            name="Dep Flow",
            steps=[
                FlowStep(id="a", name="A", tool="geocoder", operation="geocode"),
                FlowStep(id="b", name="B", agent_instructions="Use A results", depends_on=["a"]),
            ],
        )
        runner = FlowRunner(engine=engine)
        run = runner.run(flow)
        assert run.status == "completed"
        assert "a" in run.step_results
        assert "b" in run.step_results

    def test_run_records_timing(self) -> None:
        flow = Flow(
            name="Timing",
            steps=[FlowStep(id="s1", name="S1", agent_instructions="Quick step")],
        )
        runner = FlowRunner()
        run = runner.run(flow)
        assert run.started_at is not None
        assert run.completed_at is not None
        assert run.completed_at >= run.started_at

    def test_run_step_failure_sets_failed(self) -> None:
        engine = MagicMock()
        engine.execute.side_effect = RuntimeError("Connection refused")

        flow = Flow(
            name="Fail Flow",
            steps=[
                FlowStep(id="bad", name="Bad Step", tool="geocoder", operation="geocode"),
            ],
        )
        runner = FlowRunner(engine=engine)
        run = runner.run(flow)
        assert run.status == "failed"
        assert len(run.errors) == 1
        assert "bad" in run.errors[0]

    def test_run_cycle_fails_gracefully(self) -> None:
        flow = Flow(
            name="Cycle",
            steps=[
                FlowStep(id="a", name="A", depends_on=["b"]),
                FlowStep(id="b", name="B", depends_on=["a"]),
            ],
        )
        runner = FlowRunner()
        run = runner.run(flow)
        assert run.status == "failed"
        assert any("cycle" in e.lower() for e in run.errors)

    def test_run_clears_current_step_on_completion(self) -> None:
        flow = Flow(
            name="T",
            steps=[FlowStep(id="s1", name="S1")],
        )
        runner = FlowRunner()
        run = runner.run(flow)
        assert run.current_step_id is None


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestTemplates:
    """Tests for pre-built flow templates."""

    def test_list_templates(self) -> None:
        names = list_templates()
        assert "vegetation_monitor" in names
        assert "distance_analysis" in names
        assert "area_survey" in names

    def test_vegetation_monitor_template(self) -> None:
        flow = get_template("vegetation_monitor")
        assert flow.name == "Vegetation Monitor"
        assert len(flow.steps) == 4
        step_ids = [s.id for s in flow.steps]
        assert "geocode" in step_ids
        assert "ndvi" in step_ids

    def test_vegetation_monitor_with_overrides(self) -> None:
        flow = get_template("vegetation_monitor", address="Berlin, Germany", ndvi_threshold=0.5)
        assert "Berlin" in flow.description
        assert "0.5" in flow.description

    def test_distance_analysis_template(self) -> None:
        flow = get_template("distance_analysis")
        assert flow.name == "Distance Analysis"
        assert len(flow.steps) == 4

    def test_area_survey_template(self) -> None:
        flow = get_template("area_survey")
        assert flow.name == "Area Survey"
        assert len(flow.steps) == 4

    def test_unknown_template_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown template"):
            get_template("nonexistent_template")

    def test_template_metadata_has_template_name(self) -> None:
        flow = get_template("vegetation_monitor")
        assert flow.metadata.get("template") == "vegetation_monitor"


# ---------------------------------------------------------------------------
# Integration: Builder + Runner
# ---------------------------------------------------------------------------


class TestBuilderRunnerIntegration:
    """Tests combining builder and runner."""

    def test_build_and_run_llm_flow(self) -> None:
        flow = (
            FlowBuilder()
            .add_step("Analyse", agent_instructions="Analyse the area")
            .add_step("Report", agent_instructions="Write report", depends_on=["analyse"])
            .build("Integration Test")
        )
        runner = FlowRunner()
        run = runner.run(flow)
        assert run.status == "completed"
        assert len(run.step_results) == 2

    def test_build_and_run_tool_flow(self) -> None:
        engine = MagicMock()
        engine.execute.return_value = SpatialResult(
            spatial_context=SpatialContext(summary="OK"),
        )
        flow = (
            FlowBuilder()
            .add_step("Geocode", tool="geocoder", operation="geocode",
                       parameters={"address": "Paris"})
            .add_step("Buffer", tool="spatial_reasoner", operation="buffer",
                       depends_on=["geocode"])
            .build("Tool Pipeline")
        )
        runner = FlowRunner(engine=engine)
        run = runner.run(flow)
        assert run.status == "completed"
        assert engine.execute.call_count == 2
