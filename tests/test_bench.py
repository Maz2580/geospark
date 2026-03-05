"""
Tests for GeoSpark Bench.

Tests the scorer, runner, report, and dataset loading.
All tests run with MockAdapter — no live LLM calls needed.
"""

from __future__ import annotations

import json
import pytest

from geospark.bench import (
    GeoSparkBench,
    BenchmarkName,
    BenchmarkResult,
    BenchQuestion,
    MockAdapter,
    PromptMode,
    load_dataset,
    list_benchmarks,
    report,
)
from geospark.bench.models import AnswerType, Difficulty
from geospark.bench.scorer import (
    parse_boolean,
    parse_numeric,
    parse_category,
    score_question,
    score_benchmark,
)
from geospark.bench.runner import BenchRunner
from geospark.engine.spatial_reasoner import SpatialReasoner


# ---------------------------------------------------------------------------
# Test: Answer Parsing
# ---------------------------------------------------------------------------

class TestParseBoolean:
    def test_yes(self):
        assert parse_boolean("Yes") is True

    def test_no(self):
        assert parse_boolean("No") is False

    def test_true(self):
        assert parse_boolean("True") is True

    def test_false(self):
        assert parse_boolean("False") is False

    def test_starts_with_yes(self):
        assert parse_boolean("Yes, the polygon contains the point.") is True

    def test_starts_with_no(self):
        assert parse_boolean("No, they are disjoint.") is False

    def test_the_answer_is(self):
        assert parse_boolean("The answer is true") is True

    def test_ambiguous(self):
        assert parse_boolean("I'm not sure about that") is None


class TestParseNumeric:
    def test_meters(self):
        assert parse_numeric("3172 meters") == 3172.0

    def test_kilometers(self):
        assert parse_numeric("5.5 km") == 5500.0

    def test_with_comma(self):
        assert parse_numeric("5,585,233 meters") == 5585233.0

    def test_just_number(self):
        assert parse_numeric("3172") == 3172.0

    def test_approximate(self):
        assert parse_numeric("approximately 3200") == 3200.0

    def test_no_number(self):
        assert parse_numeric("I don't know the distance") is None


class TestParseCategory:
    def test_exact_match(self):
        assert parse_category("deforestation", ["deforestation", "urban_expansion"]) == "deforestation"

    def test_in_sentence(self):
        assert parse_category(
            "The change type is urban_expansion due to rapid growth.",
            ["deforestation", "urban_expansion"]
        ) == "urban_expansion"

    def test_no_match(self):
        assert parse_category("volcanic activity", ["deforestation", "urban_expansion"]) is None


# ---------------------------------------------------------------------------
# Test: Dataset Loading
# ---------------------------------------------------------------------------

class TestDatasets:
    def test_list_benchmarks(self):
        benchmarks = list_benchmarks()
        assert len(benchmarks) >= 3
        names = {b["name"] for b in benchmarks}
        assert "geotopo" in names
        assert "geodistance" in names
        assert "geochanage" in names

    def test_load_geotopo(self):
        questions = load_dataset(BenchmarkName.GEOTOPO)
        assert len(questions) == 100
        assert all(q.benchmark == BenchmarkName.GEOTOPO for q in questions)
        assert all(q.answer_type == AnswerType.BOOLEAN for q in questions)

    def test_load_geodistance(self):
        questions = load_dataset(BenchmarkName.GEODISTANCE)
        assert len(questions) == 100
        assert all(q.benchmark == BenchmarkName.GEODISTANCE for q in questions)

    def test_load_geochanage(self):
        questions = load_dataset(BenchmarkName.GEOCHANAGE)
        assert len(questions) >= 30

    def test_questions_have_dual_prompts(self):
        """Every question must have both natural and structured prompts."""
        for bench_name in BenchmarkName:
            questions = load_dataset(bench_name)
            for q in questions:
                assert q.prompt_natural, f"{q.id} missing prompt_natural"
                assert q.prompt_structured, f"{q.id} missing prompt_structured"

    def test_questions_have_unique_ids(self):
        for bench_name in BenchmarkName:
            questions = load_dataset(bench_name)
            ids = [q.id for q in questions]
            assert len(ids) == len(set(ids)), f"Duplicate IDs in {bench_name.value}"

    def test_geotopo_has_hole_questions(self):
        """Dr. Chen's feedback: polygon-with-hole questions must exist."""
        questions = load_dataset(BenchmarkName.GEOTOPO)
        hole_qs = [q for q in questions if q.category == "contains_with_hole"]
        assert len(hole_qs) >= 5, "Need at least 5 polygon-with-hole questions"

    def test_geodistance_has_nearest_neighbor(self):
        questions = load_dataset(BenchmarkName.GEODISTANCE)
        nn_qs = [q for q in questions if q.category == "nearest_neighbor"]
        assert len(nn_qs) >= 5, "Need at least 5 nearest-neighbor questions"


# ---------------------------------------------------------------------------
# Test: Scorer
# ---------------------------------------------------------------------------

class TestScorer:
    def test_score_boolean_correct(self):
        q = BenchQuestion(
            id="test_001", benchmark=BenchmarkName.GEOTOPO,
            category="contains", difficulty=Difficulty.EASY,
            prompt_natural="test", prompt_structured="test",
            answer_type=AnswerType.BOOLEAN, ground_truth=True,
        )
        from geospark.bench.models import BenchAnswer
        a = BenchAnswer(
            question_id="test_001", model_id="mock",
            prompt_mode=PromptMode.NATURAL,
            raw_response="Yes", parsed_answer=True,
        )
        score = score_question(q, a)
        assert score.correct is True

    def test_score_boolean_wrong(self):
        q = BenchQuestion(
            id="test_002", benchmark=BenchmarkName.GEOTOPO,
            category="contains", difficulty=Difficulty.EASY,
            prompt_natural="test", prompt_structured="test",
            answer_type=AnswerType.BOOLEAN, ground_truth=True,
        )
        from geospark.bench.models import BenchAnswer
        a = BenchAnswer(
            question_id="test_002", model_id="mock",
            prompt_mode=PromptMode.NATURAL,
            raw_response="No", parsed_answer=False,
        )
        score = score_question(q, a)
        assert score.correct is False

    def test_score_numeric_within_tolerance(self):
        q = BenchQuestion(
            id="test_003", benchmark=BenchmarkName.GEODISTANCE,
            category="distance_absolute", difficulty=Difficulty.EASY,
            prompt_natural="test", prompt_structured="test",
            answer_type=AnswerType.NUMERIC, ground_truth=3172.0,
            ground_truth_meta={"tolerance_m": 500},
        )
        from geospark.bench.models import BenchAnswer
        a = BenchAnswer(
            question_id="test_003", model_id="mock",
            prompt_mode=PromptMode.NATURAL,
            raw_response="3200 meters", parsed_answer=3200.0,
        )
        score = score_question(q, a)
        assert score.correct is True

    def test_score_numeric_outside_tolerance(self):
        q = BenchQuestion(
            id="test_004", benchmark=BenchmarkName.GEODISTANCE,
            category="distance_absolute", difficulty=Difficulty.EASY,
            prompt_natural="test", prompt_structured="test",
            answer_type=AnswerType.NUMERIC, ground_truth=3172.0,
            ground_truth_meta={"tolerance_m": 500},
        )
        from geospark.bench.models import BenchAnswer
        a = BenchAnswer(
            question_id="test_004", model_id="mock",
            prompt_mode=PromptMode.NATURAL,
            raw_response="10000 meters", parsed_answer=10000.0,
        )
        score = score_question(q, a)
        assert score.correct is False


# ---------------------------------------------------------------------------
# Test: Runner
# ---------------------------------------------------------------------------

class TestRunner:
    def test_run_mock(self):
        runner = BenchRunner(adapter=MockAdapter(default="True"))
        result = runner.run(BenchmarkName.GEOTOPO, prompt_mode=PromptMode.NATURAL)
        assert isinstance(result, BenchmarkResult)
        assert result.total == 100
        assert 0 <= result.accuracy <= 1

    def test_run_with_sample(self):
        runner = BenchRunner(adapter=MockAdapter())
        result = runner.run(BenchmarkName.GEOTOPO, sample=0.1)
        assert result.total == 10  # 10% of 100

    def test_run_with_difficulty_filter(self):
        runner = BenchRunner(adapter=MockAdapter())
        result = runner.run(BenchmarkName.GEOTOPO, difficulty="hard")
        assert result.total > 0
        assert result.total < 100

    def test_run_with_category_filter(self):
        runner = BenchRunner(adapter=MockAdapter())
        result = runner.run(BenchmarkName.GEOTOPO, category="contains")
        assert result.total > 0
        assert all(
            s.question_id.startswith("geotopo_") for s in result.scores
        )

    def test_dry_run(self):
        runner = BenchRunner(adapter=MockAdapter())
        result = runner.run(BenchmarkName.GEOTOPO, dry_run=True)
        assert result.total == 100
        assert result.correct == 0
        assert len(result.scores) == 0


# ---------------------------------------------------------------------------
# Test: High-level API (GeoSparkBench)
# ---------------------------------------------------------------------------

class TestGeoSparkBench:
    def test_default_mock(self):
        bench = GeoSparkBench()
        results = bench.run(benchmarks=[BenchmarkName.GEOTOPO])
        assert len(results) == 1
        assert results[0].total == 100

    def test_model_string(self):
        bench = GeoSparkBench(model="mock")
        results = bench.run(benchmarks=["geotopo"])
        assert len(results) == 1

    def test_custom_adapter(self):
        adapter = MockAdapter(default="Yes")
        bench = GeoSparkBench(adapter=adapter)
        results = bench.run(benchmarks=[BenchmarkName.GEOTOPO])
        assert results[0].accuracy > 0

    def test_run_multiple_benchmarks(self):
        bench = GeoSparkBench()
        results = bench.run(benchmarks=[BenchmarkName.GEOTOPO, BenchmarkName.GEODISTANCE])
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Test: Report
# ---------------------------------------------------------------------------

class TestReport:
    def _get_result(self) -> BenchmarkResult:
        bench = GeoSparkBench(adapter=MockAdapter(default="True"))
        return bench.run(benchmarks=[BenchmarkName.GEOTOPO])[0]

    def test_console_output(self):
        output = report.to_console(self._get_result())
        assert "GEOTOPO" in output
        assert "mock" in output
        assert "Overall:" in output

    def test_markdown_output(self):
        output = report.to_markdown(self._get_result())
        assert "## GeoSpark Bench" in output
        assert "| Category |" in output

    def test_json_output(self):
        output = report.to_json(self._get_result())
        data = json.loads(output)
        assert data["benchmark"] == "geotopo"
        assert "accuracy" in data

    def test_diff(self):
        result_a = GeoSparkBench(adapter=MockAdapter(default="True")).run(
            benchmarks=[BenchmarkName.GEOTOPO]
        )[0]
        result_b = GeoSparkBench(adapter=MockAdapter(default="False")).run(
            benchmarks=[BenchmarkName.GEOTOPO]
        )[0]
        output = report.diff(result_a, result_b)
        assert "COMPARISON" in output
        assert "Delta" in output


# ---------------------------------------------------------------------------
# Test: Geodesic Distance (the fix we made)
# ---------------------------------------------------------------------------

class TestGeodesicDistance:
    def test_known_distance(self):
        """Eiffel Tower to Louvre: ~3.17 km."""
        d = SpatialReasoner.calculate_distance(
            {"type": "Point", "coordinates": [2.2945, 48.8584]},
            {"type": "Point", "coordinates": [2.3376, 48.8606]},
        )
        assert 3000 < d < 3500  # ~3,172m

    def test_intercontinental(self):
        """NYC to London: ~5,570 km."""
        d = SpatialReasoner.calculate_distance(
            {"type": "Point", "coordinates": [-74.006, 40.7128]},
            {"type": "Point", "coordinates": [-0.1278, 51.5074]},
        )
        assert 5500_000 < d < 5700_000

    def test_same_point(self):
        """Distance to self is 0."""
        d = SpatialReasoner.calculate_distance(
            {"type": "Point", "coordinates": [0, 0]},
            {"type": "Point", "coordinates": [0, 0]},
        )
        assert d == 0.0

    def test_polygon_to_point(self):
        """Distance from polygon to external point."""
        polygon = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        }
        point = {"type": "Point", "coordinates": [2, 0.5]}
        d = SpatialReasoner.calculate_distance(polygon, point)
        assert d > 0
