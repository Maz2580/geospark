"""Tests for Phase 7C: Multi-Agent Coordinator, Toolkit, Messaging."""
from __future__ import annotations

import asyncio

import pytest

from geospark.agents.coordinator import (
    AgentCoordinator,
    CoordinationResult,
    ProgressEvent,
    classify_intent,
)
from geospark.agents.messaging import (
    AgentCard,
    AgentRegistry,
    MessageHub,
    Msg,
)
from geospark.agents.toolkit import (
    RegisteredTool,
    Toolkit,
    ToolSchema,
    _parse_docstring,
    _python_to_json_type,
)

# ======================================================================
# Toolkit tests
# ======================================================================


class TestTypeMapping:
    """Tests for Python -> JSON Schema type conversion."""

    def test_str_to_string(self) -> None:
        assert _python_to_json_type(str) == "string"

    def test_int_to_integer(self) -> None:
        assert _python_to_json_type(int) == "integer"

    def test_float_to_number(self) -> None:
        assert _python_to_json_type(float) == "number"

    def test_bool_to_boolean(self) -> None:
        assert _python_to_json_type(bool) == "boolean"

    def test_list_to_array(self) -> None:
        assert _python_to_json_type(list) == "array"

    def test_dict_to_object(self) -> None:
        assert _python_to_json_type(dict) == "object"

    def test_optional_int_modern(self) -> None:
        # Test the modern `int | None` syntax (types.UnionType)
        # Note: this path depends on runtime typing support
        from typing import Union

        assert _python_to_json_type(Union[int, None]) == "integer"  # noqa: UP007

    def test_union_with_none(self) -> None:
        from typing import Union

        assert _python_to_json_type(Union[str, None]) == "string"  # noqa: UP007

    def test_unknown_falls_back_to_string(self) -> None:
        class Custom:
            pass

        assert _python_to_json_type(Custom) == "string"


class TestDocstringParsing:
    """Tests for docstring summary + arg extraction."""

    def test_parse_empty(self) -> None:
        summary, args = _parse_docstring(None)
        assert summary == ""
        assert args == {}

    def test_parse_summary_only(self) -> None:
        summary, args = _parse_docstring("Does a thing.")
        assert summary == "Does a thing."
        assert args == {}

    def test_parse_google_style_args(self) -> None:
        doc = """Compute geodesic distance.

        Args:
            lat_a: Latitude of point A.
            lon_a: Longitude of point A.
            radius: Search radius in meters.

        Returns:
            Distance in meters.
        """
        summary, args = _parse_docstring(doc)
        assert summary == "Compute geodesic distance."
        assert args["lat_a"] == "Latitude of point A."
        assert args["lon_a"] == "Longitude of point A."
        assert args["radius"] == "Search radius in meters."

    def test_parse_stops_at_returns(self) -> None:
        doc = """Summary.

        Args:
            x: Input.

        Returns:
            y: Output value that looks like an arg.
        """
        _, args = _parse_docstring(doc)
        assert "x" in args
        assert "y" not in args  # Returns section shouldn't pollute args


class TestToolkit:
    """Tests for the Toolkit class."""

    def test_register_simple(self) -> None:
        def add(a: int, b: int) -> int:
            """Add two integers."""
            return a + b

        kit = Toolkit()
        registered = kit.register(add)
        assert isinstance(registered, RegisteredTool)
        assert "add" in kit
        assert len(kit) == 1

    def test_schema_extraction(self) -> None:
        def geocode(query: str, limit: int = 5) -> dict:
            """Geocode a place name.

            Args:
                query: Address or place name.
                limit: Maximum results.
            """
            return {}

        kit = Toolkit()
        kit.register(geocode)
        schema = kit.get("geocode").schema
        assert schema.name == "geocode"
        assert schema.description == "Geocode a place name."
        assert schema.parameters["type"] == "object"
        assert "query" in schema.parameters["properties"]
        assert schema.parameters["properties"]["query"]["type"] == "string"
        assert schema.parameters["properties"]["query"]["description"] == "Address or place name."
        assert "query" in schema.parameters["required"]
        assert "limit" not in schema.parameters["required"]  # Has default

    def test_override_name_and_description(self) -> None:
        def f() -> None:
            """Original."""

        kit = Toolkit()
        kit.register(f, name="custom", description="Custom desc")
        tool = kit.get("custom")
        assert tool.schema.name == "custom"
        assert tool.schema.description == "Custom desc"

    def test_unregister(self) -> None:
        def f() -> None:
            """Doc."""

        kit = Toolkit()
        kit.register(f)
        assert kit.unregister("f") is True
        assert len(kit) == 0
        assert kit.unregister("missing") is False

    def test_groups(self) -> None:
        def a() -> None:
            """A"""

        def b() -> None:
            """B"""

        kit = Toolkit()
        kit.register(a, group="default")
        kit.register(b, group="advanced")

        # Only default active
        schemas = kit.list_schemas()
        assert len(schemas) == 1
        assert schemas[0].name == "a"

        # Activate advanced
        kit.activate_group("advanced")
        schemas = kit.list_schemas()
        assert len(schemas) == 2

        # Deactivate default
        kit.deactivate_group("default")
        schemas = kit.list_schemas()
        assert len(schemas) == 1
        assert schemas[0].name == "b"

    def test_list_all_groups(self) -> None:
        def a() -> None:
            """A"""

        kit = Toolkit()
        kit.register(a, group="hidden")
        # Not in default active groups
        assert len(kit.list_schemas()) == 0
        # But all_groups=True reveals it
        assert len(kit.list_schemas(all_groups=True)) == 1

    def test_openai_format(self) -> None:
        def f(x: str) -> str:
            """Echo x."""
            return x

        kit = Toolkit()
        kit.register(f)
        tools = kit.list_openai_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "f"
        assert tools[0]["function"]["description"] == "Echo x."

    def test_invoke_sync(self) -> None:
        def add(a: int, b: int) -> int:
            """Add."""
            return a + b

        kit = Toolkit()
        kit.register(add)
        result = kit.invoke("add", a=2, b=3)
        assert result == 5

    def test_invoke_missing_raises(self) -> None:
        kit = Toolkit()
        with pytest.raises(KeyError, match="not registered"):
            kit.invoke("ghost")

    def test_invoke_async_on_sync_tool(self) -> None:
        def sync_f() -> int:
            """Sync."""
            return 42

        kit = Toolkit()
        kit.register(sync_f)
        assert asyncio.run(kit.invoke_async("sync_f")) == 42

    def test_invoke_async_tool(self) -> None:
        async def async_f(x: int) -> int:
            """Async."""
            return x * 2

        kit = Toolkit()
        kit.register(async_f)
        tool = kit.get("async_f")
        assert tool.is_async is True
        assert asyncio.run(kit.invoke_async("async_f", x=21)) == 42

    def test_invoke_async_tool_with_sync_raises(self) -> None:
        async def async_f() -> int:
            """Async."""
            return 1

        kit = Toolkit()
        kit.register(async_f)
        with pytest.raises(RuntimeError, match="async"):
            kit.invoke("async_f")


class TestToolSchema:
    """Tests for the ToolSchema dataclass."""

    def test_to_openai_format(self) -> None:
        schema = ToolSchema(
            name="test",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
        )
        fmt = schema.to_openai_format()
        assert fmt["type"] == "function"
        assert fmt["function"]["name"] == "test"


# ======================================================================
# Messaging tests
# ======================================================================


class TestMsg:
    """Tests for the Msg model."""

    def test_create_minimal(self) -> None:
        m = Msg()
        assert m.id
        assert m.role == "user"
        assert m.content == ""

    def test_create_full(self) -> None:
        m = Msg(
            role="assistant",
            sender="geo_agent",
            receiver="user",
            content="Found 3 hospitals nearby",
            metadata={"count": 3},
        )
        assert m.sender == "geo_agent"
        assert m.metadata["count"] == 3

    def test_to_dict(self) -> None:
        m = Msg(content="hello", sender="alice")
        d = m.to_dict()
        assert d["content"] == "hello"
        assert d["sender"] == "alice"
        assert "id" in d


class TestAgentCard:
    """Tests for the AgentCard model."""

    def test_create_minimal(self) -> None:
        card = AgentCard(name="test_agent")
        assert card.name == "test_agent"
        assert card.capabilities == []

    def test_matches_intent_exact(self) -> None:
        card = AgentCard(
            name="geocoder",
            keywords=["geocode", "address", "place"],
        )
        assert card.matches_intent("geocode this address") > 0

    def test_matches_intent_no_overlap(self) -> None:
        card = AgentCard(name="geocoder", keywords=["address"])
        assert card.matches_intent("tell me about fires") == 0.0

    def test_matches_intent_empty_keywords(self) -> None:
        card = AgentCard(name="x", keywords=[])
        assert card.matches_intent("anything") == 0.0


class TestAgentRegistry:
    """Tests for the AgentRegistry."""

    def test_register_and_get(self) -> None:
        reg = AgentRegistry()
        card = AgentCard(name="test", keywords=["test"])
        reg.register(card, lambda msg: msg)
        assert "test" in reg
        assert len(reg) == 1
        found = reg.get("test")
        assert found is not None
        assert found[1].name == "test"

    def test_unregister(self) -> None:
        reg = AgentRegistry()
        reg.register(AgentCard(name="x"), lambda m: m)
        assert reg.unregister("x") is True
        assert len(reg) == 0
        assert reg.unregister("ghost") is False

    def test_list_cards(self) -> None:
        reg = AgentRegistry()
        reg.register(AgentCard(name="a"), lambda m: m)
        reg.register(AgentCard(name="b"), lambda m: m)
        cards = reg.list_cards()
        assert len(cards) == 2

    def test_find_by_intent(self) -> None:
        reg = AgentRegistry()
        reg.register(
            AgentCard(name="site_selector", keywords=["best place", "location"]),
            lambda m: m,
        )
        reg.register(
            AgentCard(name="weather", keywords=["temperature", "rain"]),
            lambda m: m,
        )

        results = reg.find_by_intent("where is the best place to open a cafe")
        assert len(results) >= 1
        assert results[0][0].name == "site_selector"

    def test_find_by_capability(self) -> None:
        reg = AgentRegistry()
        reg.register(
            AgentCard(name="a", capabilities=["geocoding"]),
            lambda m: m,
        )
        reg.register(
            AgentCard(name="b", capabilities=["geocoding", "routing"]),
            lambda m: m,
        )

        geocoders = reg.find_by_capability("geocoding")
        assert len(geocoders) == 2

        routers = reg.find_by_capability("routing")
        assert len(routers) == 1
        assert routers[0].name == "b"

    def test_clear(self) -> None:
        reg = AgentRegistry()
        reg.register(AgentCard(name="x"), lambda m: m)
        reg.clear()
        assert len(reg) == 0


class TestMessageHub:
    """Tests for MessageHub pub-sub broker."""

    def test_post_and_log(self) -> None:
        hub = MessageHub()
        msg = Msg(content="hello", sender="alice")
        hub.post(msg)
        assert len(hub) == 1
        assert hub.log[0].content == "hello"

    def test_invocation_id_auto_assigned(self) -> None:
        hub = MessageHub()
        msg = Msg(content="x")
        hub.post(msg)
        assert msg.invocation_id == hub.invocation_id

    def test_subscribe(self) -> None:
        hub = MessageHub()
        received = []

        def sub(msg: Msg) -> None:
            received.append(msg.content)

        hub.subscribe(sub)
        hub.post(Msg(content="one"))
        hub.post(Msg(content="two"))
        assert received == ["one", "two"]

    def test_unsubscribe(self) -> None:
        hub = MessageHub()
        received = []

        def cb(m: Msg) -> None:
            received.append(m.content)

        hub.subscribe(cb)
        hub.post(Msg(content="before"))
        hub.unsubscribe(cb)
        hub.post(Msg(content="after"))
        assert received == ["before"]

    def test_subscriber_exception_does_not_break_hub(self) -> None:
        hub = MessageHub()

        def bad_sub(msg: Msg) -> None:
            raise RuntimeError("oops")

        hub.subscribe(bad_sub)
        # Should not raise
        hub.post(Msg(content="still works"))
        assert len(hub) == 1

    def test_messages_from(self) -> None:
        hub = MessageHub()
        hub.post(Msg(sender="alice", content="a"))
        hub.post(Msg(sender="bob", content="b"))
        hub.post(Msg(sender="alice", content="c"))
        alice_msgs = hub.messages_from("alice")
        assert len(alice_msgs) == 2

    def test_messages_to(self) -> None:
        hub = MessageHub()
        hub.post(Msg(sender="alice", receiver="agent1", content="a"))
        hub.post(Msg(sender="alice", receiver="agent2", content="b"))
        to_agent1 = hub.messages_to("agent1")
        assert len(to_agent1) == 1

    def test_last(self) -> None:
        hub = MessageHub()
        for i in range(5):
            hub.post(Msg(content=str(i)))
        assert len(hub.last(3)) == 3
        assert hub.last(3)[-1].content == "4"

    def test_clear(self) -> None:
        hub = MessageHub()
        hub.post(Msg(content="x"))
        hub.clear()
        assert len(hub) == 0


# ======================================================================
# Coordinator tests
# ======================================================================


class TestIntentClassification:
    """Tests for intent classification."""

    def _empty_registry(self) -> AgentRegistry:
        return AgentRegistry()

    def test_empty_registry_no_match(self) -> None:
        reg = self._empty_registry()
        c = classify_intent("find best restaurant location", reg)
        assert c.matched_agent == ""

    def test_site_selection_pattern(self) -> None:
        reg = AgentRegistry()
        reg.register(AgentCard(name="site_selector"), lambda m: m)
        c = classify_intent(
            "Find the best location for a new cafe in Melbourne", reg
        )
        assert c.matched_agent == "site_selector"
        assert c.score >= 0.9

    def test_report_pattern(self) -> None:
        reg = AgentRegistry()
        reg.register(AgentCard(name="spatial_report"), lambda m: m)
        c = classify_intent("Analyze this location for me", reg)
        assert c.matched_agent == "spatial_report"

    def test_fallback_to_geo_agent(self) -> None:
        reg = AgentRegistry()
        reg.register(AgentCard(name="geo_agent"), lambda m: m)
        c = classify_intent("Do something unusual and uncategorized", reg)
        assert c.matched_agent == "geo_agent"
        assert c.score == 0.5
        assert "Fallback" in c.reason

    def test_keyword_matching(self) -> None:
        reg = AgentRegistry()
        reg.register(
            AgentCard(
                name="weather_agent",
                keywords=["temperature", "weather", "rain", "forecast"],
            ),
            lambda m: m,
        )
        c = classify_intent("What is the weather forecast for Tokyo", reg)
        assert c.matched_agent == "weather_agent"
        assert c.score > 0


class TestAgentCoordinator:
    """Tests for the multi-agent coordinator."""

    def test_auto_register_defaults(self) -> None:
        coord = AgentCoordinator()
        names = [c.name for c in coord.list_agents()]
        # At least one specialist should register
        assert len(names) >= 1

    def test_no_auto_register(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)
        assert len(coord.list_agents()) == 0

    def test_register_custom_agent(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)

        def my_fn(msg: Msg) -> Msg:
            return Msg(
                role="assistant",
                sender="my_agent",
                content=f"Handled: {msg.content}",
            )

        card = AgentCard(
            name="my_agent",
            description="Custom agent",
            keywords=["custom", "my"],
        )
        coord.register_agent(card, my_fn)
        assert "my_agent" in coord.registry

    def test_run_dispatches_to_registered_agent(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)

        def echo(msg: Msg) -> Msg:
            return Msg(
                role="assistant",
                sender="echo",
                content=f"ECHO: {msg.content}",
            )

        coord.register_agent(
            AgentCard(name="echo", keywords=["echo", "repeat"]),
            echo,
        )

        result = coord.run("Please echo this message")
        assert isinstance(result, CoordinationResult)
        assert result.agent_used == "echo"
        assert "ECHO" in result.summary
        assert result.error is None

    def test_run_with_parameters(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)
        received_params = {}

        def capture(msg: Msg) -> Msg:
            received_params.update(msg.metadata.get("parameters", {}))
            return Msg(role="assistant", sender="capture", content="ok")

        coord.register_agent(
            AgentCard(name="capture", keywords=["test"]),
            capture,
        )
        coord.run("test this", parameters={"radius": 1000})
        assert received_params == {"radius": 1000}

    def test_run_no_matching_agent(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)
        result = coord.run("Something nothing matches")
        assert result.error is not None
        assert "No matching agent" in result.error

    def test_run_handles_agent_exception(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)

        def bad_agent(msg: Msg) -> Msg:
            raise ValueError("intentional")

        coord.register_agent(
            AgentCard(name="bad", keywords=["bad"]),
            bad_agent,
        )
        result = coord.run("do something bad")
        assert result.error is not None
        assert "ValueError" in result.error
        assert "intentional" in result.error

    def test_run_returns_conversation_log(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)
        coord.register_agent(
            AgentCard(name="chatty", keywords=["talk"]),
            lambda m: Msg(
                role="assistant", sender="chatty", content="I talked"
            ),
        )
        result = coord.run("talk to me please")
        # Should contain user message + assistant message
        assert len(result.conversation) >= 2

    def test_run_accepts_non_msg_reply(self) -> None:
        """Coordinator should wrap string returns in a Msg."""
        coord = AgentCoordinator(auto_register_defaults=False)
        coord.register_agent(
            AgentCard(name="str_agent", keywords=["test"]),
            lambda m: "just a string",
        )
        result = coord.run("test test")
        assert result.summary == "just a string"
        assert result.error is None

    def test_describe(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)
        coord.register_agent(
            AgentCard(name="x", description="X agent", capabilities=["a", "b"]),
            lambda m: m,
        )
        info = coord.describe()
        assert len(info["registered_agents"]) == 1
        assert info["registered_agents"][0]["name"] == "x"

    def test_stream_events(self) -> None:
        """stream() should yield progress events in order."""
        coord = AgentCoordinator(auto_register_defaults=False)
        coord.register_agent(
            AgentCard(name="streamer", keywords=["stream"]),
            lambda m: Msg(role="assistant", sender="streamer", content="done"),
        )

        async def collect():
            events = []
            async for ev in coord.stream("please stream this"):
                events.append(ev)
            return events

        events = asyncio.run(collect())
        event_types = [e.event_type for e in events]
        assert "classify" in event_types
        assert "dispatch" in event_types
        assert "agent_start" in event_types
        assert "agent_done" in event_types
        assert "complete" in event_types

    def test_stream_error(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)

        def bad(msg: Msg) -> Msg:
            raise RuntimeError("boom")

        coord.register_agent(
            AgentCard(name="bad", keywords=["fail"]),
            bad,
        )

        async def collect():
            events = []
            async for ev in coord.stream("please fail now"):
                events.append(ev)
            return events

        events = asyncio.run(collect())
        assert any(e.event_type == "error" for e in events)

    def test_stream_no_match(self) -> None:
        coord = AgentCoordinator(auto_register_defaults=False)

        async def collect():
            events = []
            async for ev in coord.stream("no match here"):
                events.append(ev)
            return events

        events = asyncio.run(collect())
        assert any(e.event_type == "error" for e in events)


class TestProgressEvent:
    """Tests for ProgressEvent model."""

    def test_create(self) -> None:
        ev = ProgressEvent(event_type="test", message="hello")
        assert ev.event_type == "test"
        assert ev.timestamp > 0


class TestCoordinationResult:
    """Tests for CoordinationResult model."""

    def test_defaults(self) -> None:
        r = CoordinationResult(goal="x")
        assert r.error is None
        assert r.agent_used == ""
