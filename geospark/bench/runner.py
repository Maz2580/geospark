"""
GeoSpark Bench Runner.

Loads benchmark datasets, runs them against a model adapter,
and produces scored results. Supports sampling, filtering, caching,
and both LLM-only and tool-augmented modes.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

from geospark.bench.models import (
    BenchAnswer,
    BenchmarkName,
    BenchQuestion,
    ModelAdapter,
    PromptMode,
)
from geospark.bench.scorer import BenchmarkResult, score_benchmark

DATASETS_DIR = Path(__file__).parent / "datasets"


def load_dataset(benchmark: BenchmarkName) -> list[BenchQuestion]:
    """Load a benchmark dataset from JSON."""
    path = DATASETS_DIR / f"{benchmark.value}.json"
    if not path.exists():
        raise FileNotFoundError(f"Benchmark dataset not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    return [BenchQuestion(**q) for q in data["questions"]]


def list_benchmarks() -> list[dict[str, Any]]:
    """List available benchmark datasets with metadata."""
    benchmarks = []
    for name in BenchmarkName:
        path = DATASETS_DIR / f"{name.value}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            benchmarks.append({
                "name": name.value,
                "description": data.get("description", ""),
                "version": data.get("version", "0.1.0"),
                "total_questions": len(data.get("questions", [])),
            })
    return benchmarks


class BenchRunner:
    """
    Runs benchmark evaluations against a model.

    Usage:
        runner = BenchRunner(adapter=OpenRouterAdapter("llama-3.3-70b"))
        result = runner.run(BenchmarkName.GEOTOPO, prompt_mode=PromptMode.NATURAL)
        result.accuracy  # 0.42
    """

    def __init__(
        self,
        adapter: ModelAdapter,
        seed: int = 42,
    ):
        self.adapter = adapter
        self.seed = seed

    def run(
        self,
        benchmark: BenchmarkName,
        prompt_mode: PromptMode = PromptMode.NATURAL,
        sample: float | None = None,
        difficulty: str | None = None,
        category: str | None = None,
        dry_run: bool = False,
    ) -> BenchmarkResult:
        """
        Run a benchmark evaluation.

        Args:
            benchmark: Which benchmark to run
            prompt_mode: Natural language or structured (GeoJSON) prompts
            sample: Fraction of questions to run (0.0-1.0), None for all
            difficulty: Filter to specific difficulty level
            category: Filter to specific category
            dry_run: If True, return questions without calling the model
        """
        questions = load_dataset(benchmark)

        # Apply filters
        if difficulty:
            questions = [q for q in questions if q.difficulty.value == difficulty]
        if category:
            questions = [q for q in questions if q.category == category]

        # Apply sampling
        if sample is not None and 0 < sample < 1:
            rng = random.Random(self.seed)
            n = max(1, int(len(questions) * sample))
            questions = rng.sample(questions, n)

        if dry_run:
            # Return empty result with question count
            return BenchmarkResult(
                benchmark=benchmark,
                model_id=self.adapter.model_id,
                prompt_mode=prompt_mode,
                tool_augmented=False,
                total=len(questions),
                correct=0,
                accuracy=0.0,
            )

        # Run evaluation
        answers = []
        for question in questions:
            prompt = (
                question.prompt_natural
                if prompt_mode == PromptMode.NATURAL
                else question.prompt_structured
            )

            start = time.monotonic()
            raw_response = self.adapter.complete(prompt)
            latency_ms = int((time.monotonic() - start) * 1000)

            # Parse the response based on answer type
            parsed = self._parse_response(raw_response, question)

            answers.append(BenchAnswer(
                question_id=question.id,
                model_id=self.adapter.model_id,
                prompt_mode=prompt_mode,
                raw_response=raw_response,
                parsed_answer=parsed,
                latency_ms=latency_ms,
            ))

        return score_benchmark(
            questions=questions,
            answers=answers,
            benchmark=benchmark,
            model_id=self.adapter.model_id,
            prompt_mode=prompt_mode,
        )

    def _parse_response(self, response: str, question: BenchQuestion) -> Any:
        """Extract a structured answer from the model's free-text response."""
        from geospark.bench.models import AnswerType
        from geospark.bench.scorer import parse_boolean, parse_category, parse_numeric

        if question.answer_type == AnswerType.BOOLEAN:
            return parse_boolean(response)
        elif question.answer_type == AnswerType.NUMERIC:
            return parse_numeric(response)
        elif question.answer_type == AnswerType.CATEGORY:
            valid = question.ground_truth_meta.get("valid_categories", [])
            return parse_category(response, valid)
        else:
            return response.strip()

    def run_comparison(
        self,
        benchmark: BenchmarkName,
        prompt_mode: PromptMode = PromptMode.NATURAL,
        sample: float | None = None,
    ) -> dict[str, BenchmarkResult]:
        """
        Run both natural and structured modes for comparison.

        Returns dict with keys 'natural' and 'structured'.
        """
        results = {}
        for mode in PromptMode:
            results[mode.value] = self.run(benchmark, prompt_mode=mode, sample=sample)
        return results
