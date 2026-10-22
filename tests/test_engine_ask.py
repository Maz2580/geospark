"""Engine.ask provider routing: local Ollama first, OpenRouter only as a configured fallback."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from geospark.engine.core import Engine
from geospark.protocol.schema import SpatialContext, SpatialResult


def ok(source: str) -> SpatialResult:
    return SpatialResult(spatial_context=SpatialContext(summary="answer"), sources=[source])


def failed(message: str) -> SpatialResult:
    return SpatialResult(errors=[message])


@pytest.fixture
def engine() -> Engine:
    return Engine()


def test_local_model_answers_first(engine, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    with patch.object(Engine, "_ask_ollama", return_value=ok("ollama:qwen2.5:7b")) as ollama, \
         patch.object(Engine, "_ask_openrouter") as openrouter:
        result = engine.ask("How far is Paris from London?")
    assert result.sources == ["ollama:qwen2.5:7b"]
    ollama.assert_called_once()
    openrouter.assert_not_called()


def test_falls_back_to_openrouter_when_local_fails_and_key_set(engine, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    with patch.object(Engine, "_ask_ollama", return_value=failed("Ollama down")), \
         patch.object(Engine, "_ask_openrouter", return_value=ok("openrouter:free")) as openrouter:
        result = engine.ask("q", model="best")
    assert result.sources == ["openrouter:free"]
    assert openrouter.call_args.args[1] == "best"  # the (allowlisted) model is passed through


def test_no_fallback_without_openrouter_key(engine, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch.object(Engine, "_ask_ollama", return_value=failed("Ollama down")), \
         patch.object(Engine, "_ask_openrouter") as openrouter:
        result = engine.ask("q")
    assert result.errors == ["Ollama down"]
    openrouter.assert_not_called()


@pytest.mark.parametrize(("provider", "called"), [("ollama", "_ask_ollama"), ("openrouter", "_ask_openrouter")])
def test_explicit_provider(engine, provider, called) -> None:
    with patch.object(Engine, "_ask_ollama", return_value=ok("o")) as o, \
         patch.object(Engine, "_ask_openrouter", return_value=ok("r")) as r:
        engine.ask("q", provider=provider)
    mocks = {"_ask_ollama": o, "_ask_openrouter": r}
    mocks[called].assert_called_once()
    other = next(m for name, m in mocks.items() if name != called)
    other.assert_not_called()


def test_ollama_failure_becomes_an_error_result(engine, monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")  # nothing listens here
    result = engine._ask_ollama("q", None, None, [])
    assert result.errors and "Ollama call failed" in result.errors[0]


def test_openrouter_without_key_is_an_error(engine, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = engine._ask_openrouter("q", None, None, [])
    assert result.errors and "OPENROUTER_API_KEY" in result.errors[0]
