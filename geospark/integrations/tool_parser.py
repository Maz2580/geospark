"""Shared fallback tool-call parser.

Recovers tool calls that small / free LLMs emit as plain text instead of as
structured tool-call JSON. The v2 paper evaluation (9 models, 3 conditions,
535 questions) showed that Llama 3.1 8B, Mistral 7B, Gemma 2 9B, and Phi-3.5
frequently emit calls in plain-text form, and the Ollama path silently
dropped them — explaining a large fraction of the open-weight augmented-cell
scores.

Variants handled (each documented with the v2 model that emitted it):

  1. ``name("arg")`` — single positional string-arg.        (Qwen 2.5 7B)
  2. ``name("a", "b", ...)`` — positional multi-arg.         (Llama 3.1 8B)
  3. ``name(k1="v1", k2="v2", ...)`` — keyword multi-arg.    (Llama, Gemma)
  4. ``{"name": "...", "arguments": {...}}`` — JSON literal. (Mistral 7B)
  5. ``name("a"; mode=x)`` — semicolon arg separator.        (Llama variant)
  6. Inline-code wrap: ``\\`name("a")\\``` or **name**(...).  (CoT mode, most)
  7. Triple-backtick code fences enclosing any of the above. (CoT mode, most)
"""
from __future__ import annotations

import json
import re
from typing import Any


def parse_fallback_tool_calls(
    text: str,
    tool_specs: list[dict] | None = None,
) -> list[dict] | None:
    """Parse tool calls from a plain-text model response.

    Returns a list of synthetic tool_call dicts compatible with the OpenAI /
    Ollama / OpenRouter tool-call shape, or ``None`` if nothing parsed.

    Args:
        text: The model's free-form text content.
        tool_specs: List of MCP tool definitions (each with ``name`` and
            ``inputSchema``). Defaults to the canonical ``MCP_TOOLS`` from
            ``geospark.integrations.mcp_server``.

    The synthetic call shape matches what the openai_tools / ollama_tools
    loops expect, so callers can splice the result directly into the
    ``tool_calls`` list and continue iterating.
    """
    if not text:
        return None

    if tool_specs is None:
        from geospark.integrations.mcp_server import MCP_TOOLS
        tool_specs = MCP_TOOLS

    tool_names = {t["name"] for t in tool_specs}
    if not tool_names:
        return None

    normalized = _normalize_markup(text)
    normalized = _normalize_semicolons_in_parens(normalized)

    tool_alt = "|".join(re.escape(n) for n in sorted(tool_names, key=len, reverse=True))
    calls: list[dict] = []
    seen: set[tuple[str, str]] = set()

    # Pattern 1 — single positional string-arg: name("foo") or name('foo')
    single_arg_pattern = re.compile(
        rf'\b({tool_alt})\s*\(\s*["\']([^"\']+)["\']\s*\)'
    )
    for match in single_arg_pattern.finditer(normalized):
        name, arg = match.group(1), match.group(2)
        args = _bind_positional_args(name, [arg], tool_specs)
        if args is None:
            continue
        _append_call(calls, seen, name, args, "parsed from plain text (single-arg)")

    # Pattern 2 — keyword multi-arg: name(k1="v1", k2="v2", ...)
    kwarg_pattern = re.compile(
        rf'\b({tool_alt})\s*\(\s*((?:\w+\s*=\s*[^,()]+?(?:,\s*)?)+)\s*\)'
    )
    for match in kwarg_pattern.finditer(normalized):
        name, body = match.group(1), match.group(2)
        kwargs = _parse_kwargs(body)
        if not kwargs:
            continue
        kwargs.setdefault("explanation", "parsed from plain text (kwargs)")
        _append_call(calls, seen, name, kwargs, kwargs["explanation"])

    # Pattern 3 — positional multi-arg: name("a", "b", "c")
    multi_arg_pattern = re.compile(
        rf'\b({tool_alt})\s*\(\s*((?:["\'][^"\']+["\'](?:\s*,\s*)?){{2,}})\s*\)'
    )
    for match in multi_arg_pattern.finditer(normalized):
        name, body = match.group(1), match.group(2)
        positional = re.findall(r'["\']([^"\']+)["\']', body)
        if len(positional) < 2:
            continue
        args = _bind_positional_args(name, positional, tool_specs)
        if args is None:
            continue
        _append_call(calls, seen, name, args, "parsed from plain text (multi-arg)")

    # Pattern 4 — JSON literal in prose:
    # {"name": "geocode", "arguments": {"query": "Paris"}}
    json_pattern = re.compile(
        r'\{[^{}]*"name"\s*:\s*"(\w+)"[^{}]*"arguments"\s*:\s*(\{[^{}]*\})[^{}]*\}'
    )
    for match in json_pattern.finditer(normalized):
        name = match.group(1)
        if name not in tool_names:
            continue
        try:
            args = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
        if not isinstance(args, dict):
            continue
        args.setdefault("explanation", "parsed from JSON in text")
        _append_call(calls, seen, name, args, args["explanation"])

    return calls if calls else None


# ---- helpers ------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"```[\w+-]*\s*\n?(.*?)\n?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_MD_BOLD_RE = re.compile(r"\*\*([A-Za-z_][\w]*)\*\*")


def _normalize_markup(text: str) -> str:
    """Strip Markdown code-fences / inline-code / bold around tool names so the
    arg-extraction patterns below see the raw call form.

    We deliberately keep the content WITHIN code fences (so ``calculate_distance(...)``
    inside a python block is still parseable); we only strip the fences themselves.
    """
    text = _CODE_FENCE_RE.sub(lambda m: m.group(1), text)
    text = _INLINE_CODE_RE.sub(lambda m: m.group(1), text)
    text = _MD_BOLD_RE.sub(lambda m: m.group(1), text)
    return text


def _normalize_semicolons_in_parens(text: str) -> str:
    """Replace ``;`` with ``,`` inside parenthesised expressions only.

    Some Llama 3.1 8B transcripts emit ``geocode("Eiffel Tower"; mode=normal)``;
    treating ``;`` as ``,`` lets the kwarg pattern recover it. We restrict the
    substitution to ``(...)`` regions so prose semicolons elsewhere are left
    alone.
    """
    def repl(match: re.Match[str]) -> str:
        return match.group(0).replace(";", ",")

    return re.sub(r"\([^()]*\)", repl, text)


def _parse_kwargs(body: str) -> dict[str, Any]:
    """Parse a ``k1="v1", k2=v2, k3='v3'`` body into a dict.

    Values may be quoted strings, bare numbers, or unquoted single tokens.
    Returns ``{}`` if nothing could be parsed.
    """
    out: dict[str, Any] = {}
    for kv in re.finditer(
        r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^,()\s]+))',
        body,
    ):
        key = kv.group(1)
        raw = kv.group(2) if kv.group(2) is not None else (
            kv.group(3) if kv.group(3) is not None else kv.group(4)
        )
        if raw is None:
            continue
        out[key] = _coerce_scalar(raw)
    return out


def _coerce_scalar(raw: str) -> Any:
    """Coerce a bare token to int/float/bool/None where unambiguous."""
    s = raw.strip()
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("none", "null"):
        return None
    try:
        if "." in s or "e" in low:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _bind_positional_args(
    name: str,
    values: list[str],
    tool_specs: list[dict],
) -> dict[str, Any] | None:
    """Map positional values onto a tool's required params (excluding
    ``explanation``).

    For tools with one non-explanation required param, the first value goes
    into that slot. For multi-param tools, values are bound left-to-right.
    Returns ``None`` if there are more values than slots — we'd rather drop
    an ambiguous call than synthesise a wrong one.
    """
    tool_def = next((t for t in tool_specs if t["name"] == name), None)
    if tool_def is None:
        return None

    schema = tool_def.get("inputSchema", {})
    required = [p for p in schema.get("required", []) if p != "explanation"]
    if not required:
        required = ["query"]

    if len(values) > len(required):
        return None

    bound: dict[str, Any] = {}
    for slot, raw in zip(required, values):
        bound[slot] = _coerce_scalar(raw)
    bound["explanation"] = "parsed from plain text (positional)"
    return bound


def _append_call(
    calls: list[dict],
    seen: set[tuple[str, str]],
    name: str,
    args: dict[str, Any],
    explanation: str,
) -> None:
    """Append a synthetic tool_call dict; dedupe on (name, sorted args)."""
    args.setdefault("explanation", explanation)
    key = (name, json.dumps(args, sort_keys=True, default=str))
    if key in seen:
        return
    seen.add(key)
    calls.append({
        "id": f"fallback_{name}_{len(calls)}",
        "function": {"name": name, "arguments": args},
    })
