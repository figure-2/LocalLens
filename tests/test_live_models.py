from __future__ import annotations

import os
from pathlib import Path

import pytest

from locallens.benchmarks.runner import run_benchmark
from locallens.core.config import Settings


pytestmark = pytest.mark.skipif(
    os.getenv("LOCALLENS_RUN_LIVE_MODEL_TESTS") != "1",
    reason="live model smoke tests are opt-in",
)


def test_live_text_backend_expanded_fixture_quality(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    source = root / "benchmarks" / "fixtures" / "corpus"
    golden = root / "benchmarks" / "fixtures" / "golden_quality_queries.json"
    settings = Settings(
        data_dir=tmp_path / "data",
        text_embedding_backend="sentence-transformers",
        vision_embedding_backend="hash",
    )

    report = run_benchmark(source, [], settings, golden_path=golden)

    assert report.text_dimension == 384
    assert report.evaluated_queries >= 18
    assert report.skipped_queries >= 6
    assert report.sync.failed == 0
    assert report.stale_vector_count == 0
    assert report.duplicate_vector_count == 0
    assert report.recall_at_5 >= 0.75
    assert report.recall_at_10 >= 0.80
    assert report.mrr_at_10 >= 0.55
    assert report.quality_slices["tag:korean"]["evaluated_queries"] >= 8
    assert report.quality_slices["tag:english"]["evaluated_queries"] >= 10


def test_live_vision_backend_expanded_fixture_quality(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    source = root / "benchmarks" / "fixtures" / "image_corpus"
    golden = root / "benchmarks" / "fixtures" / "golden_quality_queries.json"
    settings = Settings(
        data_dir=tmp_path / "data",
        text_embedding_backend="hash",
        vision_embedding_backend="transformers",
        vision_model_name="google/siglip-base-patch16-224",
    )

    report = run_benchmark(source, [], settings, golden_path=golden)

    assert report.vision_dimension == 768
    assert report.evaluated_queries >= 200
    assert report.skipped_queries == 34
    assert report.sync.failed == 0
    assert report.stale_vector_count == 0
    assert report.duplicate_vector_count == 0
    assert report.top1_accuracy >= 0.80
    assert report.recall_at_5 >= 0.90
    assert report.quality_slices["tag:image"]["evaluated_queries"] >= 200
    assert report.quality_slices["tag:synthetic"]["evaluated_queries"] >= 114
    assert report.quality_slices["tag:hard-negative"]["evaluated_queries"] >= 96
    assert report.quality_slices["tag:hard-negative"]["recall_at_5"] >= 0.50
