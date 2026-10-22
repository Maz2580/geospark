"""GeoSpark Bench must be reproducible: regenerating gives the published datasets exactly.

The benchmark backs published accuracy numbers, so any change to the generator or to the
geometry engine that alters a question or a ground-truth answer has to be deliberate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import geospark.bench.generate_datasets as gen

PUBLISHED = Path(gen.__file__).parent / "datasets"
NAMES = ["geotopo", "geodistance", "georeason", "geochange", "geomultimodal"]


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bench")
    original = gen.DATASETS_DIR
    gen.DATASETS_DIR = out
    try:
        gen.generate_all()
    finally:
        gen.DATASETS_DIR = original
    return out


@pytest.mark.parametrize("name", NAMES)
def test_regenerated_dataset_matches_published(regenerated: Path, name: str) -> None:
    published = json.loads((PUBLISHED / f"{name}.json").read_text())
    fresh = json.loads((regenerated / f"{name}.json").read_text())
    assert fresh == published


def test_total_question_count(regenerated: Path) -> None:
    total = sum(len(json.loads((regenerated / f"{n}.json").read_text())["questions"]) for n in NAMES)
    assert total == 535
