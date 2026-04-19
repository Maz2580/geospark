"""Tests for the Phase 8B chat-to-flow builder."""

from __future__ import annotations

import json
from typing import Any

import pytest

from geospark.flows.chat_builder import (
    ChatFlowSession,
    _validate_flow_dag,
    build_system_prompt,
)
from geospark.flows.flow_builder import FlowBuilder
from geospark.flows.flow_runner import FlowRunner
from geospark.flows.flow_schema import FlowRoute, FlowStep


# ---------------------------------------------------------------------------
# Fake LLM helpers
# ---------------------------------------------------------------------------


def _scripted_llm(script: list[list[dict[str, Any]]]):
    """Return a ChatFn that replays a fixed sequence of tool-call batches.

    Each element of `script` is the `tool_calls` list for that turn. After
    the script is exhausted, subsequent turns return no tool_calls (which
    signals the session to stop).
    """

    state = {"turn": 0}

    def _chat(messages, tools):
        turn = state["turn"]
        state["turn"] += 1
        if turn < len(script):
            return {"content": "", "tool_calls": script[turn]}
        return {"content": "done", "tool_calls": []}

    return _chat


def _call(_tool: str, /, **args: Any) -> dict[str, Any]:
    """Build a single tool-call dict with JSON-string arguments.

    First argument is positional-only so keyword args like `name=...`
    bound for the tool's signature don't collide with it.
    """
    return {
        "id": f"tc_{_tool}",
        "function": {"name": _tool, "arguments": json.dumps(args)},
    }


# ---------------------------------------------------------------------------
# Validator unit tests
# ---------------------------------------------------------------------------


class TestValidator:
    def test_empty_flow_rejected(self):
        errors = _validate_flow_dag(FlowBuilder())
        assert errors and "no steps" in errors[0]

    def test_single_step_ok(self):
        b = FlowBuilder().add_step("Geocode", step_id="geocode", tool="geocoder", operation="geocode")
        assert _validate_flow_dag(b) == []

    def test_orphan_depends_on_caught(self):
        b = FlowBuilder().add_step("X", step_id="x", depends_on=["ghost"])
        errors = _validate_flow_dag(b)
        assert any("ghost" in e for e in errors)

    def test_orphan_route_target_caught(self):
        # Bypass FlowBuilder.add_route's source check by injecting the route directly
        b = FlowBuilder().add_step("A", step_id="a")
        b._steps[0].routes.append(FlowRoute(condition="always", target_step_id="phantom"))
        errors = _validate_flow_dag(b)
        assert any("phantom" in e for e in errors)

    def test_cycle_detected(self):
        b = FlowBuilder()
        # Manually create a cyclic pair of steps via internal state, since
        # add_step cannot normally produce a cycle on its own.
        b._steps.extend([
            FlowStep(id="a", name="A", depends_on=["b"]),
            FlowStep(id="b", name="B", depends_on=["a"]),
        ])
        b._step_ids.update({"a", "b"})
        errors = _validate_flow_dag(b)
        assert any("cycle" in e for e in errors)


# ---------------------------------------------------------------------------
# Tool function tests via ChatFlowSession
# ---------------------------------------------------------------------------


class TestAddStepTool:
    def setup_method(self):
        self.session = ChatFlowSession(llm_fn=_scripted_llm([]))

    def test_happy_path(self):
        out = self.session._add_step_tool(
            step_id="geocode", name="Geocode",
            tool="geocoder", operation="geocode",
            parameters_json='{"address": "Paris"}',
        )
        assert out.startswith("OK")
        assert self.session.builder._steps[0].id == "geocode"

    def test_duplicate_id_surfaces_error(self):
        self.session._add_step_tool(step_id="x", name="X")
        out = self.session._add_step_tool(step_id="x", name="X2")
        assert out.startswith("ERROR")

    def test_bad_json_params_surfaces_error(self):
        out = self.session._add_step_tool(
            step_id="x", name="X", parameters_json="not-json",
        )
        assert "not valid JSON" in out

    def test_non_object_params_rejected(self):
        out = self.session._add_step_tool(
            step_id="x", name="X", parameters_json="[1, 2]",
        )
        assert "must encode a JSON object" in out

    def test_depends_on_csv_parsed(self):
        self.session._add_step_tool(step_id="a", name="A")
        self.session._add_step_tool(step_id="b", name="B")
        self.session._add_step_tool(
            step_id="c", name="C", depends_on_csv="a, b",
        )
        step_c = next(s for s in self.session.builder._steps if s.id == "c")
        assert step_c.depends_on == ["a", "b"]


class TestAddRouteTool:
    def test_missing_source_surfaces_error_not_exception(self):
        session = ChatFlowSession(llm_fn=_scripted_llm([]))
        out = session._add_route_tool(
            from_step="ghost", to_step="also_ghost", condition="always",
        )
        assert out.startswith("ERROR")

    def test_happy_path(self):
        session = ChatFlowSession(llm_fn=_scripted_llm([]))
        session._add_step_tool(step_id="a", name="A")
        out = session._add_route_tool(
            from_step="a", to_step="b", condition="if x > 1",
        )
        assert out.startswith("OK")


class TestSetTriggerTool:
    def test_invalid_trigger_type_rejected(self):
        session = ChatFlowSession(llm_fn=_scripted_llm([]))
        out = session._set_trigger_tool(trigger_type="bogus")
        assert out.startswith("ERROR")

    def test_schedule_trigger(self):
        session = ChatFlowSession(llm_fn=_scripted_llm([]))
        out = session._set_trigger_tool(
            trigger_type="schedule", schedule="0 * * * *",
        )
        assert out.startswith("OK")
        assert session.builder._trigger.trigger_type == "schedule"


class TestFinishFlowTool:
    def test_blocks_on_empty_flow(self):
        session = ChatFlowSession(llm_fn=_scripted_llm([]))
        out = session._finish_flow_tool(name="Empty")
        assert out.startswith("VALIDATION_ERROR")
        assert session._finished is None

    def test_happy_path(self):
        session = ChatFlowSession(llm_fn=_scripted_llm([]))
        session._add_step_tool(
            step_id="a", name="A", tool="geocoder", operation="geocode",
            parameters_json='{"address": "Paris"}',
        )
        out = session._finish_flow_tool(name="Trivial", description="one step")
        assert out.startswith("DONE")
        assert session._finished is not None
        assert session._finished.name == "Trivial"
        assert len(session._finished.steps) == 1


# ---------------------------------------------------------------------------
# End-to-end run loop with scripted LLM
# ---------------------------------------------------------------------------


class TestSessionRunLoop:
    def test_end_to_end_produces_runnable_flow(self):
        script = [
            [_call("add_step",
                   step_id="geocode", name="Geocode Area",
                   tool="geocoder", operation="geocode",
                   parameters_json='{"address": "Valencia, Spain"}')],
            [_call("add_step",
                   step_id="elevation", name="Check Elevation",
                   tool="terrain", operation="elevation",
                   parameters_json='{"geometry_ref": "{geocode.geometry}"}',
                   depends_on_csv="geocode")],
            [_call("finish_flow",
                   name="Elevation Probe",
                   description="Geocode then look up elevation")],
        ]
        session = ChatFlowSession(llm_fn=_scripted_llm(script))
        result = session.run("Find the elevation of Valencia, Spain")

        assert result.error is None
        assert result.flow is not None
        assert result.flow.name == "Elevation Probe"
        assert [s.id for s in result.flow.steps] == ["geocode", "elevation"]
        assert result.turns == 3
        assert all(rec.ok for rec in result.tool_calls)

    def test_error_recovery_round_trips_through_llm(self):
        # The LLM first tries to route from a non-existent step, sees ERROR,
        # then corrects by adding the source, the target, and the route.
        script = [
            [_call("add_route", from_step="ghost", to_step="alert",
                   condition="always")],  # -> ERROR surfaced to LLM
            [_call("add_step", step_id="a", name="A")],
            [_call("add_step", step_id="b", name="B", depends_on_csv="a")],
            [_call("add_route", from_step="a", to_step="b", condition="always")],
            [_call("finish_flow", name="Fixed", description="")],
        ]
        session = ChatFlowSession(llm_fn=_scripted_llm(script))
        result = session.run("build something")

        assert result.flow is not None
        # First tool call should have failed and been recorded as such.
        assert result.tool_calls[0].ok is False
        assert result.tool_calls[0].result.startswith("ERROR")
        # Final call succeeded.
        assert result.tool_calls[-1].ok is True

    def test_max_turns_without_finish_returns_error(self):
        # LLM endlessly adds useless no-tool steps; never calls finish_flow.
        script = [
            [_call("add_step", step_id=f"s{i}", name=f"Step {i}")]
            for i in range(30)
        ]
        session = ChatFlowSession(llm_fn=_scripted_llm(script))
        result = session.run("go", max_turns=5)
        assert result.flow is None
        assert result.error is not None
        assert "Max turns" in result.error
        assert result.turns == 5

    def test_stop_without_finish_returns_error(self):
        # LLM returns empty tool_calls on the very first turn.
        session = ChatFlowSession(llm_fn=_scripted_llm([]))
        result = session.run("go")
        assert result.flow is None
        assert result.error is not None
        assert "without calling finish_flow" in result.error

    def test_generated_flow_runs_through_flowrunner(self):
        # Full pipeline: chat -> Flow -> FlowRunner. Uses a pure-LLM step so
        # no external tools are needed (runner just passes through).
        script = [
            [_call("add_step",
                   step_id="interpret", name="Interpret",
                   agent_instructions="Explain the result to the user.")],
            [_call("finish_flow", name="Trivial", description="")],
        ]
        session = ChatFlowSession(llm_fn=_scripted_llm(script))
        result = session.run("just narrate")
        assert result.flow is not None

        runner = FlowRunner()
        run = runner.run(result.flow)
        assert run.status == "completed"
        assert run.step_results["interpret"]["status"] == "success"


class TestSystemPrompt:
    def test_prompt_contains_tool_catalog_and_rules(self):
        prompt = build_system_prompt()
        assert "geocoder" in prompt
        assert "spatial_reasoner" in prompt
        assert "finish_flow" in prompt
        assert "snake_case" in prompt


@pytest.mark.skipif(True, reason="live-only: requires local Ollama with qwen2.5:7b")
class TestLiveOllama:
    """Marked live-only; run manually with `-m live` after removing the skip."""

    def test_vegetation_monitor_flow(self):
        from geospark.flows.chat_builder import make_ollama_chat_fn

        session = ChatFlowSession(llm_fn=make_ollama_chat_fn("qwen2.5:7b"))
        result = session.run(
            "Monitor NDVI in Valencia; alert if the vegetation index drops "
            "below 0.3.",
            max_turns=15,
        )
        assert result.flow is not None, result.error
        assert len(result.flow.steps) >= 2
