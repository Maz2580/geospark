"""
GeoSpark Bench - Evaluation framework for spatial reasoning.

Usage:
    from geospark.bench import GeoSparkBench, BenchmarkName, PromptMode

    bench = GeoSparkBench(model="mock")
    results = bench.run(benchmarks=[BenchmarkName.GEOTOPO])
    print(results[0].accuracy)
"""

from __future__ import annotations

from geospark.bench.models import (
    BenchmarkName,
    BenchmarkResult,
    BenchQuestion,
    Difficulty,
    ModelAdapter,
    MockAdapter,
    PromptMode,
)
from geospark.bench.runner import BenchRunner, load_dataset, list_benchmarks
from geospark.bench.scorer import score_benchmark
from geospark.bench import report


class GeoSparkBench:
    """
    High-level API for running GeoSpark benchmarks.

    Matches the Architecture doc usage:
        bench = GeoSparkBench(model="gpt-4", tools=engine.tools)
        results = bench.run(benchmarks=["geotopo", "geodistance"])
        results[0].report()

    For provider-agnostic use, pass an adapter:
        bench = GeoSparkBench(adapter=MyCustomAdapter())
    """

    def __init__(
        self,
        adapter: ModelAdapter | None = None,
        model: str | None = None,
        tools: list | None = None,
    ):
        if adapter is not None:
            self._adapter = adapter
        elif model is not None:
            self._adapter = self._resolve_model(model)
        else:
            self._adapter = MockAdapter()

        self._tools = tools or []
        self._runner = BenchRunner(adapter=self._adapter)

    def run(
        self,
        benchmarks: list[BenchmarkName | str] | None = None,
        prompt_mode: PromptMode = PromptMode.NATURAL,
        sample: float | None = None,
    ) -> list[BenchmarkResult]:
        """Run one or more benchmarks and return results."""
        if benchmarks is None:
            benchmarks = list(BenchmarkName)

        results = []
        for b in benchmarks:
            name = BenchmarkName(b) if isinstance(b, str) else b
            result = self._runner.run(name, prompt_mode=prompt_mode, sample=sample)
            results.append(result)

        return results

    @staticmethod
    def _resolve_model(model: str) -> ModelAdapter:
        """Resolve a model string to an adapter."""
        if model == "mock":
            return MockAdapter()
        # Future: OpenAI, Anthropic, Ollama adapters
        return MockAdapter()


__all__ = [
    "GeoSparkBench",
    "BenchmarkName",
    "BenchmarkResult",
    "BenchQuestion",
    "BenchRunner",
    "Difficulty",
    "ModelAdapter",
    "MockAdapter",
    "PromptMode",
    "load_dataset",
    "list_benchmarks",
    "report",
    "score_benchmark",
]
