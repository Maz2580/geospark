"""
GeoSpark Bench Scorer.

Scores model answers against ground truth.
Supports boolean, numeric (with tolerance), category, and text matching.
Reports accuracy, F1, per-category breakdown, and 95% confidence intervals.
"""

from __future__ import annotations

import math
import re
from typing import Any

from geospark.bench.models import (
    AnswerType,
    BenchAnswer,
    BenchmarkName,
    BenchmarkResult,
    BenchQuestion,
    CategoryScore,
    PromptMode,
    QuestionScore,
)


def _wilson_ci(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for binomial proportion (95% CI by default)."""
    if total == 0:
        return 0.0, 1.0
    p = correct / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


def _f1_binary(scores: list[QuestionScore]) -> float:
    """Calculate binary F1 score (correct = positive class)."""
    tp = sum(1 for s in scores if s.correct)
    fp = 0  # We don't have false positives in this framing
    fn = sum(1 for s in scores if not s.correct)
    if tp == 0:
        return 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


# ---------------------------------------------------------------------------
# Answer Parsing — extract structured answers from free-text LLM responses
# ---------------------------------------------------------------------------

def parse_boolean(text: str) -> bool | None:
    """Extract a boolean answer from model response text."""
    text_lower = text.strip().lower()

    # Direct matches
    if text_lower in ("true", "yes", "correct", "it does", "yes, it does"):
        return True
    if text_lower in ("false", "no", "incorrect", "it does not", "no, it does not"):
        return False

    # Pattern: starts with yes/no
    if text_lower.startswith("yes"):
        return True
    if text_lower.startswith("no"):
        return False

    # Pattern: "the answer is true/false"
    match = re.search(r"the answer is\s+(true|false|yes|no)", text_lower)
    if match:
        return match.group(1) in ("true", "yes")

    return None


def parse_numeric(text: str) -> float | None:
    """Extract a numeric answer from model response text."""
    # Remove commas in numbers
    text_clean = text.replace(",", "")

    # Look for patterns like "3,172 meters", "3.17 km", "approximately 5585 km"
    patterns = [
        r"([\d.]+)\s*(?:meters|m\b)",          # meters
        r"([\d.]+)\s*(?:kilometers|km\b)",      # kilometers (convert)
        r"([\d.]+)\s*(?:miles|mi\b)",           # miles (convert)
        r"(?:approximately|about|roughly|~)\s*([\d.]+)",  # approximate
        r"(?:distance|result|answer)\s*(?:is|:)\s*([\d.]+)",  # "distance is X"
        r"^([\d.]+)$",  # Just a number
    ]

    for i, pattern in enumerate(patterns):
        match = re.search(pattern, text_clean, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            if i == 1:  # km -> meters
                value *= 1000
            elif i == 2:  # miles -> meters
                value *= 1609.34
            return value

    # Last resort: first number in text
    match = re.search(r"([\d]+\.?[\d]*)", text_clean)
    if match:
        return float(match.group(1))

    return None


def parse_category(text: str, valid_categories: list[str]) -> str | None:
    """Extract a category answer from model response text."""
    text_lower = text.strip().lower()
    for cat in valid_categories:
        if cat.lower() in text_lower:
            return cat
    return None


# ---------------------------------------------------------------------------
# Scoring Logic
# ---------------------------------------------------------------------------

def score_question(
    question: BenchQuestion,
    answer: BenchAnswer,
) -> QuestionScore:
    """Score a single question-answer pair."""

    expected = question.ground_truth
    got = answer.parsed_answer

    if question.answer_type == AnswerType.BOOLEAN:
        parsed = parse_boolean(str(got)) if not isinstance(got, bool) else got
        correct = parsed == expected
        within_tolerance = correct

    elif question.answer_type == AnswerType.NUMERIC:
        parsed = parse_numeric(str(got)) if not isinstance(got, (int, float)) else float(got)
        if parsed is None:
            correct = False
            within_tolerance = False
        else:
            tolerance = question.ground_truth_meta.get("tolerance_m", 500)  # Default 500m
            tolerance_pct = question.ground_truth_meta.get("tolerance_pct", 0.1)  # 10%
            abs_diff = abs(parsed - expected)
            correct = abs_diff <= tolerance
            within_tolerance = abs_diff <= abs(expected * tolerance_pct)

    elif question.answer_type == AnswerType.CATEGORY:
        correct = str(got).lower().strip() == str(expected).lower().strip()
        within_tolerance = correct

    else:  # TEXT — fuzzy matching for v0.1
        correct = str(expected).lower() in str(got).lower()
        within_tolerance = correct

    return QuestionScore(
        question_id=question.id,
        correct=correct,
        expected=expected,
        got=got,
        within_tolerance=within_tolerance,
    )


def score_benchmark(
    questions: list[BenchQuestion],
    answers: list[BenchAnswer],
    benchmark: BenchmarkName,
    model_id: str,
    prompt_mode: PromptMode,
    tool_augmented: bool = False,
) -> BenchmarkResult:
    """Score a full benchmark run and produce aggregated results."""

    # Build lookup
    q_map = {q.id: q for q in questions}
    scores: list[QuestionScore] = []

    total_latency = 0
    for ans in answers:
        q = q_map.get(ans.question_id)
        if q is None:
            continue
        scores.append(score_question(q, ans))
        total_latency += ans.latency_ms

    total = len(scores)
    correct = sum(1 for s in scores if s.correct)
    accuracy = correct / total if total > 0 else 0.0

    # Per-difficulty breakdown
    by_difficulty: dict[str, CategoryScore] = {}
    for diff_label in ("easy", "medium", "hard"):
        diff_scores = [s for s, q in zip(scores, (q_map[s.question_id] for s in scores))
                       if q.difficulty.value == diff_label]
        if diff_scores:
            d_correct = sum(1 for s in diff_scores if s.correct)
            d_total = len(diff_scores)
            ci_lo, ci_hi = _wilson_ci(d_correct, d_total)
            by_difficulty[diff_label] = CategoryScore(
                category=diff_label,
                total=d_total,
                correct=d_correct,
                accuracy=d_correct / d_total,
                ci_lower=ci_lo,
                ci_upper=ci_hi,
            )

    # Per-category breakdown
    by_category: dict[str, CategoryScore] = {}
    categories = {q_map[s.question_id].category for s in scores if s.question_id in q_map}
    for cat in sorted(categories):
        cat_scores = [s for s in scores
                      if s.question_id in q_map and q_map[s.question_id].category == cat]
        c_correct = sum(1 for s in cat_scores if s.correct)
        c_total = len(cat_scores)
        ci_lo, ci_hi = _wilson_ci(c_correct, c_total)
        by_category[cat] = CategoryScore(
            category=cat,
            total=c_total,
            correct=c_correct,
            accuracy=c_correct / c_total if c_total > 0 else 0.0,
            ci_lower=ci_lo,
            ci_upper=ci_hi,
        )

    ci_lo, ci_hi = _wilson_ci(correct, total)

    return BenchmarkResult(
        benchmark=benchmark,
        model_id=model_id,
        prompt_mode=prompt_mode,
        tool_augmented=tool_augmented,
        total=total,
        correct=correct,
        accuracy=accuracy,
        f1=_f1_binary(scores),
        by_difficulty=by_difficulty,
        by_category=by_category,
        scores=scores,
        total_latency_ms=total_latency,
        avg_latency_ms=total_latency / total if total > 0 else 0.0,
    )
