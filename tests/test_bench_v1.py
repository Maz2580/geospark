"""
Tests for GeoSpark Bench v1.0.

Tests the new GEOREASON and GEOMULTIMODAL benchmarks, expanded datasets,
and verifies backward compatibility with existing benchmarks.
"""

from __future__ import annotations

from geospark.bench import (
    BenchmarkName,
    BenchmarkResult,
    BenchQuestion,
    GeoSparkBench,
    MockAdapter,
    PromptMode,
    list_benchmarks,
    load_dataset,
)
from geospark.bench.models import AnswerType, BenchAnswer, Difficulty
from geospark.bench.runner import BenchRunner
from geospark.bench.scorer import (
    score_question,
)

# ---------------------------------------------------------------------------
# Test: New BenchmarkName enum values
# ---------------------------------------------------------------------------

class TestNewBenchmarkNames:
    def test_georeason_exists(self):
        assert BenchmarkName.GEOREASON.value == "georeason"

    def test_geomultimodal_exists(self):
        assert BenchmarkName.GEOMULTIMODAL.value == "geomultimodal"

    def test_all_benchmarks_count(self):
        """v1.0 should have 5 benchmark suites."""
        assert len(BenchmarkName) == 5

    def test_enum_values(self):
        expected = {"geotopo", "geodistance", "geochanage", "georeason", "geomultimodal"}
        actual = {b.value for b in BenchmarkName}
        assert actual == expected


# ---------------------------------------------------------------------------
# Test: Expanded datasets (200+ questions for geotopo and geodistance)
# ---------------------------------------------------------------------------

class TestExpandedDatasets:
    def test_geotopo_has_200_plus(self):
        questions = load_dataset(BenchmarkName.GEOTOPO)
        assert len(questions) >= 200, f"GeoTopo has {len(questions)} questions, expected 200+"

    def test_geodistance_has_200_plus(self):
        questions = load_dataset(BenchmarkName.GEODISTANCE)
        assert len(questions) >= 200, f"GeoDistance has {len(questions)} questions, expected 200+"

    def test_geotopo_has_all_categories(self):
        questions = load_dataset(BenchmarkName.GEOTOPO)
        categories = {q.category for q in questions}
        expected = {"contains", "intersects", "disjoint", "within", "contains_with_hole", "touches"}
        assert expected.issubset(categories), f"Missing categories: {expected - categories}"

    def test_geodistance_has_all_categories(self):
        questions = load_dataset(BenchmarkName.GEODISTANCE)
        categories = {q.category for q in questions}
        expected = {"distance_absolute", "proximity_threshold", "nearest_neighbor"}
        assert expected.issubset(categories), f"Missing categories: {expected - categories}"

    def test_expanded_geotopo_unique_ids(self):
        questions = load_dataset(BenchmarkName.GEOTOPO)
        ids = [q.id for q in questions]
        assert len(ids) == len(set(ids)), "Duplicate IDs in expanded GeoTopo"

    def test_expanded_geodistance_unique_ids(self):
        questions = load_dataset(BenchmarkName.GEODISTANCE)
        ids = [q.id for q in questions]
        assert len(ids) == len(set(ids)), "Duplicate IDs in expanded GeoDistance"

    def test_geotopo_has_hole_questions(self):
        """Dr. Chen's feedback: polygon-with-hole questions must exist."""
        questions = load_dataset(BenchmarkName.GEOTOPO)
        hole_qs = [q for q in questions if q.category == "contains_with_hole"]
        assert len(hole_qs) >= 5, f"Need at least 5 polygon-with-hole questions, got {len(hole_qs)}"

    def test_geodistance_has_nearest_neighbor(self):
        questions = load_dataset(BenchmarkName.GEODISTANCE)
        nn_qs = [q for q in questions if q.category == "nearest_neighbor"]
        assert len(nn_qs) >= 5, f"Need at least 5 nearest-neighbor questions, got {len(nn_qs)}"


# ---------------------------------------------------------------------------
# Test: GeoReason benchmark (new)
# ---------------------------------------------------------------------------

class TestGeoReasonDataset:
    def test_load_georeason(self):
        questions = load_dataset(BenchmarkName.GEOREASON)
        assert len(questions) >= 50, f"GeoReason has {len(questions)} questions, expected 50+"

    def test_georeason_benchmark_field(self):
        questions = load_dataset(BenchmarkName.GEOREASON)
        assert all(q.benchmark == BenchmarkName.GEOREASON for q in questions)

    def test_georeason_has_categories(self):
        questions = load_dataset(BenchmarkName.GEOREASON)
        categories = {q.category for q in questions}
        expected = {"distance_chain", "transitivity", "buffer_intersection", "comparative"}
        assert expected.issubset(categories), f"Missing categories: {expected - categories}"

    def test_georeason_has_dual_prompts(self):
        questions = load_dataset(BenchmarkName.GEOREASON)
        for q in questions:
            assert q.prompt_natural, f"{q.id} missing prompt_natural"
            assert q.prompt_structured, f"{q.id} missing prompt_structured"

    def test_georeason_unique_ids(self):
        questions = load_dataset(BenchmarkName.GEOREASON)
        ids = [q.id for q in questions]
        assert len(ids) == len(set(ids)), "Duplicate IDs in GeoReason"

    def test_georeason_answer_types(self):
        """GeoReason uses mixed answer types (numeric, boolean, category)."""
        questions = load_dataset(BenchmarkName.GEOREASON)
        answer_types = {q.answer_type for q in questions}
        # Should have at least boolean and numeric
        assert AnswerType.BOOLEAN in answer_types, "GeoReason should have boolean questions"
        assert len(answer_types) >= 2, "GeoReason should have multiple answer types"

    def test_georeason_has_reasoning_steps_meta(self):
        """Multi-step questions should note how many steps are needed."""
        questions = load_dataset(BenchmarkName.GEOREASON)
        questions_with_steps = [
            q for q in questions
            if "reasoning_steps" in q.ground_truth_meta
        ]
        assert len(questions_with_steps) >= 10, (
            f"Expected at least 10 questions with reasoning_steps metadata, got {len(questions_with_steps)}"
        )

    def test_georeason_distance_chain_has_numeric(self):
        """Distance chain questions should require numeric answers."""
        questions = load_dataset(BenchmarkName.GEOREASON)
        chain_qs = [q for q in questions if q.category == "distance_chain"]
        assert len(chain_qs) >= 5, f"Expected at least 5 distance_chain questions, got {len(chain_qs)}"
        assert all(q.answer_type == AnswerType.NUMERIC for q in chain_qs)

    def test_georeason_transitivity_has_boolean(self):
        """Transitivity questions should require boolean answers."""
        questions = load_dataset(BenchmarkName.GEOREASON)
        trans_qs = [q for q in questions if q.category == "transitivity"]
        assert len(trans_qs) >= 5, f"Expected at least 5 transitivity questions, got {len(trans_qs)}"
        assert all(q.answer_type == AnswerType.BOOLEAN for q in trans_qs)


# ---------------------------------------------------------------------------
# Test: GeoMultimodal benchmark (new)
# ---------------------------------------------------------------------------

class TestGeoMultimodalDataset:
    def test_load_geomultimodal(self):
        questions = load_dataset(BenchmarkName.GEOMULTIMODAL)
        assert len(questions) >= 20, f"GeoMultimodal has {len(questions)} questions, expected 20+"

    def test_geomultimodal_benchmark_field(self):
        questions = load_dataset(BenchmarkName.GEOMULTIMODAL)
        assert all(q.benchmark == BenchmarkName.GEOMULTIMODAL for q in questions)

    def test_geomultimodal_has_categories(self):
        questions = load_dataset(BenchmarkName.GEOMULTIMODAL)
        categories = {q.category for q in questions}
        # Should have at least vegetation_health and elevation_climate
        assert "vegetation_health" in categories
        assert "elevation_climate" in categories

    def test_geomultimodal_has_dual_prompts(self):
        questions = load_dataset(BenchmarkName.GEOMULTIMODAL)
        for q in questions:
            assert q.prompt_natural, f"{q.id} missing prompt_natural"
            assert q.prompt_structured, f"{q.id} missing prompt_structured"

    def test_geomultimodal_unique_ids(self):
        questions = load_dataset(BenchmarkName.GEOMULTIMODAL)
        ids = [q.id for q in questions]
        assert len(ids) == len(set(ids)), "Duplicate IDs in GeoMultimodal"

    def test_geomultimodal_all_boolean(self):
        """All multimodal questions in v1.0 are boolean (True/False)."""
        questions = load_dataset(BenchmarkName.GEOMULTIMODAL)
        assert all(q.answer_type == AnswerType.BOOLEAN for q in questions)

    def test_geomultimodal_has_data_types_meta(self):
        """Multimodal questions should specify what data types they combine."""
        questions = load_dataset(BenchmarkName.GEOMULTIMODAL)
        questions_with_types = [
            q for q in questions
            if "data_types" in q.ground_truth_meta
        ]
        assert len(questions_with_types) >= 10, (
            f"Expected at least 10 questions with data_types metadata, got {len(questions_with_types)}"
        )


# ---------------------------------------------------------------------------
# Test: Runner with new benchmarks
# ---------------------------------------------------------------------------

class TestRunnerNewBenchmarks:
    def test_run_georeason_mock(self):
        runner = BenchRunner(adapter=MockAdapter(default="True"))
        result = runner.run(BenchmarkName.GEOREASON, prompt_mode=PromptMode.NATURAL)
        assert isinstance(result, BenchmarkResult)
        assert result.total >= 50
        assert 0 <= result.accuracy <= 1

    def test_run_geomultimodal_mock(self):
        runner = BenchRunner(adapter=MockAdapter(default="True"))
        result = runner.run(BenchmarkName.GEOMULTIMODAL, prompt_mode=PromptMode.NATURAL)
        assert isinstance(result, BenchmarkResult)
        assert result.total >= 20
        assert 0 <= result.accuracy <= 1

    def test_run_georeason_dry_run(self):
        runner = BenchRunner(adapter=MockAdapter())
        result = runner.run(BenchmarkName.GEOREASON, dry_run=True)
        assert result.total >= 50
        assert result.correct == 0
        assert len(result.scores) == 0

    def test_run_geomultimodal_dry_run(self):
        runner = BenchRunner(adapter=MockAdapter())
        result = runner.run(BenchmarkName.GEOMULTIMODAL, dry_run=True)
        assert result.total >= 20
        assert result.correct == 0

    def test_run_georeason_with_sample(self):
        runner = BenchRunner(adapter=MockAdapter())
        result = runner.run(BenchmarkName.GEOREASON, sample=0.5)
        full = runner.run(BenchmarkName.GEOREASON, dry_run=True)
        assert result.total < full.total

    def test_run_georeason_with_category_filter(self):
        runner = BenchRunner(adapter=MockAdapter(default="True"))
        result = runner.run(BenchmarkName.GEOREASON, category="transitivity")
        assert result.total > 0
        assert result.total < 50  # Should be filtered subset


# ---------------------------------------------------------------------------
# Test: Scorer with multi-step and multimodal answers
# ---------------------------------------------------------------------------

class TestScorerNewTypes:
    def test_score_georeason_boolean(self):
        """Score a transitivity (boolean) question from GeoReason."""
        q = BenchQuestion(
            id="georeason_test_001",
            benchmark=BenchmarkName.GEOREASON,
            category="transitivity",
            difficulty=Difficulty.MEDIUM,
            prompt_natural="Is point A within the outer region?",
            prompt_structured="...",
            answer_type=AnswerType.BOOLEAN,
            ground_truth=True,
            ground_truth_meta={"reasoning_type": "spatial_transitivity", "reasoning_steps": 2},
        )
        a = BenchAnswer(
            question_id="georeason_test_001",
            model_id="mock",
            prompt_mode=PromptMode.NATURAL,
            raw_response="Yes, by transitivity",
            parsed_answer=True,
        )
        score = score_question(q, a)
        assert score.correct is True

    def test_score_georeason_numeric(self):
        """Score a distance chain (numeric) question from GeoReason."""
        q = BenchQuestion(
            id="georeason_test_002",
            benchmark=BenchmarkName.GEOREASON,
            category="distance_chain",
            difficulty=Difficulty.MEDIUM,
            prompt_natural="How far is the destination from start?",
            prompt_structured="...",
            answer_type=AnswerType.NUMERIC,
            ground_truth=7000.0,
            ground_truth_meta={"tolerance_m": 1000, "tolerance_pct": 0.10, "reasoning_steps": 2},
        )
        a = BenchAnswer(
            question_id="georeason_test_002",
            model_id="mock",
            prompt_mode=PromptMode.NATURAL,
            raw_response="approximately 7200 meters",
            parsed_answer=7200.0,
        )
        score = score_question(q, a)
        assert score.correct is True  # within 1000m tolerance

    def test_score_georeason_numeric_wrong(self):
        """Wrong numeric answer outside tolerance."""
        q = BenchQuestion(
            id="georeason_test_003",
            benchmark=BenchmarkName.GEOREASON,
            category="distance_chain",
            difficulty=Difficulty.HARD,
            prompt_natural="How far?",
            prompt_structured="...",
            answer_type=AnswerType.NUMERIC,
            ground_truth=7000.0,
            ground_truth_meta={"tolerance_m": 500, "tolerance_pct": 0.05},
        )
        a = BenchAnswer(
            question_id="georeason_test_003",
            model_id="mock",
            prompt_mode=PromptMode.NATURAL,
            raw_response="about 12000 meters",
            parsed_answer=12000.0,
        )
        score = score_question(q, a)
        assert score.correct is False

    def test_score_geomultimodal_boolean(self):
        """Score a multimodal boolean question."""
        q = BenchQuestion(
            id="geomultimodal_test_001",
            benchmark=BenchmarkName.GEOMULTIMODAL,
            category="vegetation_health",
            difficulty=Difficulty.EASY,
            prompt_natural="Is vegetation healthy?",
            prompt_structured="...",
            answer_type=AnswerType.BOOLEAN,
            ground_truth=True,
            ground_truth_meta={"explanation": "NDVI > 0.6 is healthy", "data_types": ["ndvi"]},
        )
        a = BenchAnswer(
            question_id="geomultimodal_test_001",
            model_id="mock",
            prompt_mode=PromptMode.NATURAL,
            raw_response="Yes, healthy vegetation",
            parsed_answer=True,
        )
        score = score_question(q, a)
        assert score.correct is True

    def test_score_georeason_comparative(self):
        """Score a comparative (category) question."""
        q = BenchQuestion(
            id="georeason_test_004",
            benchmark=BenchmarkName.GEOREASON,
            category="comparative",
            difficulty=Difficulty.HARD,
            prompt_natural="Is the Eiffel Tower closer to the Louvre or Big Ben?",
            prompt_structured="...",
            answer_type=AnswerType.CATEGORY,
            ground_truth="Louvre Museum",
            ground_truth_meta={"valid_categories": ["Louvre Museum", "Big Ben"]},
        )
        a = BenchAnswer(
            question_id="georeason_test_004",
            model_id="mock",
            prompt_mode=PromptMode.NATURAL,
            raw_response="The Louvre Museum is closer",
            parsed_answer="Louvre Museum",
        )
        score = score_question(q, a)
        assert score.correct is True


# ---------------------------------------------------------------------------
# Test: list_benchmarks includes new ones
# ---------------------------------------------------------------------------

class TestListBenchmarks:
    def test_list_includes_new_benchmarks(self):
        benchmarks = list_benchmarks()
        names = {b["name"] for b in benchmarks}
        assert "georeason" in names, "GeoReason not in benchmark list"
        assert "geomultimodal" in names, "GeoMultimodal not in benchmark list"

    def test_list_has_five_benchmarks(self):
        benchmarks = list_benchmarks()
        assert len(benchmarks) == 5


# ---------------------------------------------------------------------------
# Test: GeoSparkBench high-level API with new benchmarks
# ---------------------------------------------------------------------------

class TestGeoSparkBenchV1:
    def test_run_georeason(self):
        bench = GeoSparkBench()
        results = bench.run(benchmarks=[BenchmarkName.GEOREASON])
        assert len(results) == 1
        assert results[0].total >= 50

    def test_run_geomultimodal(self):
        bench = GeoSparkBench()
        results = bench.run(benchmarks=[BenchmarkName.GEOMULTIMODAL])
        assert len(results) == 1
        assert results[0].total >= 20

    def test_run_all_five_benchmarks(self):
        bench = GeoSparkBench()
        results = bench.run()  # defaults to all benchmarks
        assert len(results) == 5

    def test_run_by_string_name(self):
        bench = GeoSparkBench()
        results = bench.run(benchmarks=["georeason"])
        assert len(results) == 1
        assert results[0].benchmark == BenchmarkName.GEOREASON

    def test_run_geomultimodal_by_string(self):
        bench = GeoSparkBench()
        results = bench.run(benchmarks=["geomultimodal"])
        assert len(results) == 1
        assert results[0].benchmark == BenchmarkName.GEOMULTIMODAL
