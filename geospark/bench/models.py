"""
Data models for GeoSpark Bench.

Defines the schema for benchmark questions, answers, and results.
All benchmark datasets use these models for validation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums (no raw strings — Jordan's feedback)
# ---------------------------------------------------------------------------

class BenchmarkName(str, Enum):
    """Available benchmark suites."""
    GEOTOPO = "geotopo"
    GEODISTANCE = "geodistance"
    GEOCHANAGE = "geochanage"


class Difficulty(str, Enum):
    """Question difficulty (author-labeled for v0.1, IRT-calibrated in v1.0)."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class PromptMode(str, Enum):
    """How questions are presented to the model."""
    NATURAL = "natural"       # Plain English with coordinates in text
    STRUCTURED = "structured"  # Includes GeoJSON geometries as data


class AnswerType(str, Enum):
    """Type of expected answer."""
    BOOLEAN = "boolean"     # True/False (topology, proximity threshold)
    NUMERIC = "numeric"     # A number (distance in meters, area)
    CATEGORY = "category"   # One of N categories (relationship type)
    TEXT = "text"           # Free-text description (change detection)


# ---------------------------------------------------------------------------
# Benchmark Question Schema
# ---------------------------------------------------------------------------

class BenchQuestion(BaseModel):
    """A single benchmark question with dual prompts and ground truth."""

    id: str = Field(description="Unique question identifier, e.g. 'geotopo_001'")
    benchmark: BenchmarkName
    category: str = Field(description="Sub-category, e.g. 'contains', 'intersects', 'distance_absolute'")
    difficulty: Difficulty

    # Dual prompts (the killer feature — no other spatial benchmark does this)
    prompt_natural: str = Field(description="Natural language question with coordinates in text")
    prompt_structured: str = Field(description="Question with GeoJSON geometries as structured data")

    # Ground truth
    answer_type: AnswerType
    ground_truth: Any = Field(description="Expected answer (bool, float, str)")
    ground_truth_meta: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra context: tolerance_m for distance, geometry sources, etc.",
    )

    # Geometries (for programmatic access, not in prompt)
    geometry_a: dict[str, Any] | None = None
    geometry_b: dict[str, Any] | None = None

    # Provenance
    source: str = Field(default="generated", description="Where the question came from")


class BenchAnswer(BaseModel):
    """A model's answer to a benchmark question."""

    question_id: str
    model_id: str
    prompt_mode: PromptMode
    raw_response: str = Field(description="Full model response text")
    parsed_answer: Any = Field(description="Extracted answer (bool, float, str)")
    confidence: float | None = Field(default=None, description="Model's self-reported confidence 0-1")
    latency_ms: int = Field(default=0, description="Time to get response")
    tool_augmented: bool = Field(default=False, description="Whether GeoSpark tools were available")


# ---------------------------------------------------------------------------
# Scoring Results
# ---------------------------------------------------------------------------

class QuestionScore(BaseModel):
    """Score for a single question."""

    question_id: str
    correct: bool
    expected: Any
    got: Any
    within_tolerance: bool = Field(default=False, description="For numeric: within acceptable margin")


class CategoryScore(BaseModel):
    """Aggregated score for a category (e.g., 'contains', 'intersects')."""

    category: str
    total: int
    correct: int
    accuracy: float
    ci_lower: float = Field(default=0.0, description="95% CI lower bound")
    ci_upper: float = Field(default=1.0, description="95% CI upper bound")


class BenchmarkResult(BaseModel):
    """Complete result for a benchmark run."""

    benchmark: BenchmarkName
    model_id: str
    prompt_mode: PromptMode
    tool_augmented: bool

    # Overall metrics
    total: int
    correct: int
    accuracy: float
    f1: float = Field(default=0.0)

    # Per-difficulty
    by_difficulty: dict[str, CategoryScore] = Field(default_factory=dict)

    # Per-category
    by_category: dict[str, CategoryScore] = Field(default_factory=dict)

    # Per-question detail
    scores: list[QuestionScore] = Field(default_factory=list)

    # Run metadata
    total_latency_ms: int = Field(default=0)
    avg_latency_ms: float = Field(default=0.0)


# ---------------------------------------------------------------------------
# Model Adapter Protocol (Jordan's feedback — provider-agnostic)
# ---------------------------------------------------------------------------

@runtime_checkable
class ModelAdapter(Protocol):
    """
    Protocol for plugging any LLM into the bench.

    Implement this to evaluate your own model. GeoSpark ships adapters
    for OpenRouter, OpenAI, Anthropic, and a mock for testing.
    """

    @property
    def model_id(self) -> str:
        """Unique identifier for this model (e.g., 'gpt-4o', 'llama-3.3-70b')."""
        ...

    def complete(self, prompt: str) -> str:
        """Send a prompt and return the model's text response."""
        ...


class MockAdapter:
    """Mock adapter for testing — returns configurable responses."""

    def __init__(self, responses: dict[str, str] | None = None, default: str = "I don't know"):
        self._responses = responses or {}
        self._default = default

    @property
    def model_id(self) -> str:
        return "mock"

    def complete(self, prompt: str) -> str:
        for key, response in self._responses.items():
            if key in prompt:
                return response
        return self._default
