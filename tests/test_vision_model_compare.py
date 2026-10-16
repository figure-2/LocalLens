from __future__ import annotations

from pathlib import Path

import benchmarks.vision_model_compare as compare
from locallens.core.config import Settings
from locallens.core.types import BenchmarkReport, SyncReport


def test_vision_model_compare_writes_model_specific_rows(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run_benchmark(corpus, queries, settings, golden_path=None):
        calls.append(settings.vision_model_name)
        return BenchmarkReport(
            files=2,
            units=2,
            indexing_seconds=1.0,
            files_per_second=2.0,
            units_per_second=2.0,
            search_latency_ms={"p50": 3.0, "p95": 4.0, "p99": 5.0},
            collection_name="locallens_units",
            text_embedding_profile="hash:64",
            vision_embedding_profile=f"transformers:{settings.vision_model_name}",
            text_dimension=64,
            vision_dimension=512,
            evaluated_queries=2,
            recall_at_5=1.0,
            recall_at_10=1.0,
            mrr_at_10=0.75,
            stale_vector_count=0,
            duplicate_vector_count=0,
            qdrant_disk_bytes=0,
            sync=SyncReport(added=2, units=2),
            skipped_queries=18,
            top1_accuracy=0.5,
            quality_slices={
                "tag:hard-negative": {
                    "evaluated_queries": 1,
                    "top1_accuracy": 0.0,
                    "recall_at_5": 1.0,
                    "mrr_at_10": 0.5,
                },
                "tag:synthetic": {
                    "evaluated_queries": 2,
                    "top1_accuracy": 0.5,
                    "recall_at_5": 1.0,
                    "mrr_at_10": 0.75,
                },
            },
            query_results=[
                {
                    "id": "image-office-blue-laptop-en-001",
                    "tags": ["image", "hard-negative"],
                    "expected_paths": ["office_blue_laptop.png"],
                    "first_hit_rank": 2,
                    "recall_at_5": 1.0,
                    "mrr_at_10": 0.5,
                    "top_results": [
                        {"rank": 1, "relative_path": "office_gray_laptop.png"},
                        {"rank": 2, "relative_path": "office_blue_laptop.png"},
                    ],
                }
            ],
        )

    monkeypatch.setattr(compare, "run_benchmark", fake_run_benchmark)

    report = compare.compare_vision_models(
        tmp_path / "corpus",
        tmp_path / "golden.json",
        ["clip-model", "siglip-model"],
    )

    assert calls == ["clip-model", "siglip-model"]
    assert [row["model"] for row in report["models"]] == ["clip-model", "siglip-model"]
    assert report["models"][0]["status"] == "ok"
    assert report["models"][0]["vision_embedding_profile"] == "transformers:clip-model"
    hard_negative = report["models"][0]["hard_negative_slices"]
    assert hard_negative["all"]["top1_accuracy"] == 0.0
    assert hard_negative["object:office"]["evaluated_queries"] == 1
    failure = hard_negative["color:blue"]["top1_failure_examples"][0]
    assert failure["expected_path"] == "office_blue_laptop.png"
    assert failure["expected_key"] == {
        "object": "office",
        "color": "blue",
        "context": "laptop",
    }
    assert failure["confusable_attribute"] == "color"
    assert failure["contrast_pair_id"] == "office:laptop"
    assert hard_negative["color:blue"]["failure_modes"] == {"color": 1}
    assert hard_negative["color:blue"]["slice_overlap_count"] == 0
    assert hard_negative["color:blue"]["overlap_with_synthetic"] == 0
    assert hard_negative["color:blue"]["top1_failure_count"] == 1
    assert hard_negative["color:blue"]["null_first_hit_count"] == 0
    assert hard_negative["color:blue"]["slice_definition"] == (
        "filename stem parsed as object_color_context"
    )
    assert report["models"][0]["hard_negative_repair_targets"][0]["slice"] == "color:blue"
    oracle = report["models"][0]["hard_negative_oracle_repair_experiment"]
    assert oracle["product_ranking_change"] is False
    assert oracle["non_regression_gate"]["passed"] is False
    assert oracle["all"]["top1_repairable_count"] == 1
    assert oracle["all"]["oracle_top1_accuracy"] == 1.0
    assert "selection_criteria" in report["models"][0]


def test_vision_model_compare_records_model_failure(monkeypatch, tmp_path: Path):
    def fake_run_benchmark(corpus, queries, settings, golden_path=None):
        raise ImportError("missing tokenizer dependency")

    monkeypatch.setattr(compare, "run_benchmark", fake_run_benchmark)

    report = compare.compare_vision_models(
        tmp_path / "corpus",
        tmp_path / "golden.json",
        ["candidate-model"],
    )

    assert report["models"] == [
        {
            "status": "failed",
            "model": "candidate-model",
            "error_type": "ImportError",
            "error": "missing tokenizer dependency",
        }
    ]


def test_vision_model_compare_preserves_release_loading_contract(
    monkeypatch, tmp_path: Path
):
    captured = []

    def fake_run_benchmark(corpus, queries, settings, golden_path=None):
        captured.append(settings)
        return BenchmarkReport(
            files=1,
            units=1,
            indexing_seconds=1.0,
            files_per_second=1.0,
            units_per_second=1.0,
            search_latency_ms={"p50": 3.0, "p95": 4.0, "p99": 5.0},
            collection_name="locallens_units",
            text_embedding_profile="hash:64",
            vision_embedding_profile=f"transformers:{settings.vision_model_name}",
            text_dimension=64,
            vision_dimension=512,
            evaluated_queries=1,
            recall_at_5=1.0,
            recall_at_10=1.0,
            mrr_at_10=1.0,
            stale_vector_count=0,
            duplicate_vector_count=0,
            qdrant_disk_bytes=0,
            sync=SyncReport(added=1, units=1),
            skipped_queries=0,
            top1_accuracy=1.0,
            quality_slices={},
        )

    monkeypatch.setattr(compare, "run_benchmark", fake_run_benchmark)
    base_settings = Settings(
        data_dir=tmp_path / "base",
        model_cache_dir="model-cache",
        model_local_files_only=True,
        release_evidence_mode=True,
        hf_hub_offline=True,
        transformers_offline=True,
    )

    compare.compare_vision_models(
        tmp_path / "corpus",
        tmp_path / "golden.json",
        ["clip-model"],
        settings=base_settings,
    )

    assert captured[0].release_evidence_mode is True
    assert captured[0].model_local_files_only is True
    assert captured[0].model_cache_dir == "model-cache"
    assert captured[0].hf_hub_offline is True
    assert captured[0].transformers_offline is True


def test_vision_model_compare_uses_sanitized_absolute_path_labels(
    monkeypatch, tmp_path: Path
):
    def fake_run_benchmark(corpus, queries, settings, golden_path=None):
        return BenchmarkReport(
            files=1,
            units=1,
            indexing_seconds=1.0,
            files_per_second=1.0,
            units_per_second=1.0,
            search_latency_ms={"p50": 3.0, "p95": 4.0, "p99": 5.0},
            collection_name="locallens_units",
            text_embedding_profile="hash:64",
            vision_embedding_profile=f"transformers:{settings.vision_model_name}",
            text_dimension=64,
            vision_dimension=512,
            evaluated_queries=1,
            recall_at_5=1.0,
            recall_at_10=1.0,
            mrr_at_10=1.0,
            stale_vector_count=0,
            duplicate_vector_count=0,
            qdrant_disk_bytes=0,
            sync=SyncReport(added=1, units=1),
            skipped_queries=0,
            top1_accuracy=1.0,
            quality_slices={},
        )

    monkeypatch.setattr(compare, "run_benchmark", fake_run_benchmark)

    report = compare.compare_vision_models(
        tmp_path / "corpus",
        tmp_path / "golden.json",
        ["clip-model"],
    )

    assert report["corpus"] == "<external>/corpus"
    assert report["golden"] == "<external>/golden.json"


def test_vision_model_compare_uses_golden_image_key_for_non_filename_slices(
    monkeypatch,
    tmp_path: Path,
):
    golden = tmp_path / "golden.json"
    golden.write_text(
        """
        {
          "queries": [
            {
              "id": "q",
              "query": "blue security badge",
              "modality": "image",
              "image_key": {
                "object": "badge",
                "color": "blue",
                "context": "security"
              },
              "tags": ["image", "hard-negative", "non-filename"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    def fake_run_benchmark(corpus, queries, settings, golden_path=None):
        return BenchmarkReport(
            files=1,
            units=1,
            indexing_seconds=1.0,
            files_per_second=1.0,
            units_per_second=1.0,
            search_latency_ms={"p50": 3.0, "p95": 4.0, "p99": 5.0},
            collection_name="locallens_units",
            text_embedding_profile="hash:64",
            vision_embedding_profile=f"transformers:{settings.vision_model_name}",
            text_dimension=64,
            vision_dimension=512,
            evaluated_queries=1,
            recall_at_5=1.0,
            recall_at_10=1.0,
            mrr_at_10=1.0,
            stale_vector_count=0,
            duplicate_vector_count=0,
            qdrant_disk_bytes=0,
            sync=SyncReport(added=1, units=1),
            skipped_queries=0,
            top1_accuracy=1.0,
            quality_slices={
                "tag:hard-negative": {
                    "evaluated_queries": 1,
                    "top1_accuracy": 1.0,
                    "recall_at_5": 1.0,
                    "mrr_at_10": 1.0,
                },
            },
            query_results=[
                {
                    "id": "q",
                    "tags": ["image", "hard-negative", "non-filename"],
                    "expected_paths": ["asset_0001.png"],
                    "first_hit_rank": 1,
                    "recall_at_5": 1.0,
                    "mrr_at_10": 1.0,
                    "top_results": [
                        {"rank": 1, "relative_path": "asset_0001.png"}
                    ],
                }
            ],
        )

    monkeypatch.setattr(compare, "run_benchmark", fake_run_benchmark)

    report = compare.compare_vision_models(
        tmp_path / "corpus",
        golden,
        ["siglip-model"],
    )
    row = report["models"][0]

    assert row["filename_independence"] == {
        "evaluated_queries": 1,
        "metadata_key_count": 1,
        "semantic_filename_count": 0,
        "attribute_source": "golden:image_key",
        "passed": True,
    }
    assert report["corpus_style"] == "metadata-keyed"
    assert report["attribute_source"] == "golden:image_key"
    assert row["hard_negative_slices"]["object:badge"]["metadata_key_count"] == 1
    assert row["hard_negative_slices"]["object:badge"]["slice_definition"] == (
        "golden image_key metadata; filename does not encode object_color_context"
    )


def test_vision_model_compare_cli_fails_on_model_failure(
    monkeypatch, tmp_path: Path, capsys
):
    def fake_run_benchmark(corpus, queries, settings, golden_path=None):
        raise ImportError("missing tokenizer dependency")

    monkeypatch.setattr(compare, "run_benchmark", fake_run_benchmark)
    output = tmp_path / "compare.json"

    exit_code = compare.main(["--model", "candidate-model", "--out", str(output)])

    assert exit_code == 1
    assert not output.exists()
    assert '"status": "failed"' in capsys.readouterr().out


def test_vision_model_compare_cli_can_allow_exploratory_failures(
    monkeypatch, tmp_path: Path
):
    def fake_run_benchmark(corpus, queries, settings, golden_path=None):
        raise ImportError("missing tokenizer dependency")

    monkeypatch.setattr(compare, "run_benchmark", fake_run_benchmark)
    output = tmp_path / "compare.json"

    exit_code = compare.main(
        ["--model", "candidate-model", "--allow-failures", "--out", str(output)]
    )

    assert exit_code == 0
    assert '"status": "failed"' in output.read_text(encoding="utf-8")
