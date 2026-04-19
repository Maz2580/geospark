"""Toolkit — automatic tool schema generation from Python function signatures.

Inspired by AgentScope's Toolkit (`src/agentscope/tool/_toolkit.py`).
Lightweight version: no Pydantic BaseModel generation, just JSON Schema
extracted via `inspect` + docstring parsing.
"""
from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, get_type_hints

# ---------------------------------------------------------------------------
# Type mapping (Python annotation -> JSON Schema type)
# ---------------------------------------------------------------------------

# Ordered (bool, int, float) so bool is checked before int (bool is an int subclass)
_TYPE_ORDER: tuple[tuple[type, str], ...] = (
    (bool, "boolean"),
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (list, "array"),
    (dict, "object"),
)


def _python_to_json_type(annotation: Any) -> str:
    """Convert a Python type annotation to a JSON Schema type string."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return "string"

    # Handle typing.Optional[X], typing.Union[X, None], X | None
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        args = getattr(annotation, "__args__", ())
        # Strip None from optional types
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _python_to_json_type(non_none[0])
        return "string"

    # Direct type mapping — order matters: bool must come before int
    if isinstance(annotation, type):
        for py_type, json_type in _TYPE_ORDER:
            if issubclass(annotation, py_type):
                return json_type

    return "string"


# ---------------------------------------------------------------------------
# Docstring parsing
# ---------------------------------------------------------------------------


_DOCSTRING_ARG_PATTERN = re.compile(
    r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\([^)]*\))?\s*:\s*(.+?)$",
    re.MULTILINE,
)


def _parse_docstring(docstring: str | None) -> tuple[str, dict[str, str]]:
    """Parse a docstring into (summary, arg_descriptions).

    Supports Google-style docstrings:
        Summary line.

        Args:
            arg_name: Description of the argument.
            other_arg: Another description.

    Returns:
        (summary, {arg_name: description, ...})
    """
    if not docstring:
        return "", {}

    lines = docstring.strip().split("\n")
    summary = lines[0].strip() if lines else ""

    # Find Args section
    arg_descriptions: dict[str, str] = {}
    in_args = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith(("Args:", "Arguments:", "Parameters:")):
            in_args = True
            continue
        if in_args and stripped.startswith(("Returns:", "Raises:", "Yields:", "Example:")):
            break
        if in_args:
            match = _DOCSTRING_ARG_PATTERN.match(line)
            if match:
                arg_descriptions[match.group(1)] = match.group(2).strip()

    return summary, arg_descriptions


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


@dataclass
class ToolSchema:
    """JSON-Schema-compatible representation of a registered tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object
    group: str = "default"

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI tool calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class RegisteredTool:
    """A registered tool — function + metadata."""

    func: Callable[..., Any]
    schema: ToolSchema
    is_async: bool = False


def _build_parameter_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON Schema `parameters` object from a function signature."""
    sig = inspect.signature(func)
    try:
        type_hints = get_type_hints(func)
    except (NameError, TypeError):
        type_hints = {}

    docstring = inspect.getdoc(func) or ""
    _, arg_descriptions = _parse_docstring(docstring)

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        annotation = type_hints.get(name, param.annotation)
        json_type = _python_to_json_type(annotation)

        prop: dict[str, Any] = {"type": json_type}
        if name in arg_descriptions:
            prop["description"] = arg_descriptions[name]
        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(name)

        properties[name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


# ---------------------------------------------------------------------------
# Toolkit
# ---------------------------------------------------------------------------


@dataclass
class Toolkit:
    """A registry of tools organized into groups.

    Tools are registered via `register()`. Each tool gets a JSON Schema
    built from its signature + docstring. Active groups control which
    tools are exposed in `list_schemas()`.
    """

    tools: dict[str, RegisteredTool] = field(default_factory=dict)
    active_groups: set[str] = field(default_factory=lambda: {"default"})

    def register(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        group: str = "default",
    ) -> RegisteredTool:
        """Register a function as a tool.

        Args:
            func: The function to register. Its signature + docstring drive schema.
            name: Override the tool name (defaults to func.__name__).
            description: Override the tool description (defaults to docstring summary).
            group: Organizational group name — toolkit can activate/deactivate groups.

        Returns:
            The RegisteredTool entry.
        """
        tool_name = name or func.__name__
        docstring = inspect.getdoc(func) or ""
        summary, _ = _parse_docstring(docstring)
        tool_desc = description or summary or f"Tool: {tool_name}"
        parameters = _build_parameter_schema(func)

        schema = ToolSchema(
            name=tool_name,
            description=tool_desc,
            parameters=parameters,
            group=group,
        )
        registered = RegisteredTool(
            func=func,
            schema=schema,
            is_async=inspect.iscoroutinefunction(func),
        )
        self.tools[tool_name] = registered
        return registered

    def unregister(self, name: str) -> bool:
        """Remove a tool from the registry. Returns True if found."""
        return self.tools.pop(name, None) is not None

    def activate_group(self, group: str) -> None:
        """Mark a group as active (its tools appear in schemas)."""
        self.active_groups.add(group)

    def deactivate_group(self, group: str) -> None:
        """Mark a group as inactive (its tools hidden from schemas)."""
        self.active_groups.discard(group)

    def list_schemas(self, all_groups: bool = False) -> list[ToolSchema]:
        """List tool schemas for active groups (or all if requested)."""
        return [
            t.schema
            for t in self.tools.values()
            if all_groups or t.schema.group in self.active_groups
        ]

    def list_openai_tools(self, all_groups: bool = False) -> list[dict[str, Any]]:
        """List tools in OpenAI function calling format."""
        return [s.to_openai_format() for s in self.list_schemas(all_groups)]

    def get(self, name: str) -> RegisteredTool | None:
        """Look up a registered tool by name."""
        return self.tools.get(name)

    def invoke(self, name: str, /, **kwargs: Any) -> Any:
        """Invoke a synchronous tool by name.

        The tool-name parameter is positional-only so registered tools can
        themselves accept a keyword argument named ``name`` without colliding.
        For async tools, use ``await invoke_async()`` instead.
        """
        tool = self.tools.get(name)
        if tool is None:
            raise KeyError(f"Tool not registered: {name}")
        if tool.is_async:
            raise RuntimeError(
                f"Tool '{name}' is async — use invoke_async() instead"
            )
        return tool.func(**kwargs)

    async def invoke_async(self, name: str, /, **kwargs: Any) -> Any:
        """Invoke a tool by name, awaiting if it's async.

        The tool-name parameter is positional-only; see ``invoke`` for the
        reason.
        """
        tool = self.tools.get(name)
        if tool is None:
            raise KeyError(f"Tool not registered: {name}")
        if tool.is_async:
            return await tool.func(**kwargs)
        return tool.func(**kwargs)

    def __len__(self) -> int:
        return len(self.tools)

    def __contains__(self, name: str) -> bool:
        return name in self.tools
