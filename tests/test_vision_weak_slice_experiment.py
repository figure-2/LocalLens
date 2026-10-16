from __future__ import annotations

import json
from pathlib import Path

import benchmarks.vision_weak_slice_experiment as experiment
from locallens.core.config import Settings
from locallens.core.types import BenchmarkReport, SyncReport


def _report(rows):
    return BenchmarkReport(
        files=3,
        units=3,
        indexing_seconds=1.0,
        files_per_second=3.0,
        units_per_second=3.0,
        search_latency_ms={"p50": 1.0, "p95": 2.0, "p99": 3.0},
        collection_name="locallens_units",
        text_embedding_profile="hash:64",
        vision_embedding_profile="transformers:test",
        text_dimension=64,
        vision_dimension=512,
        evaluated_queries=len(rows),
        recall_at_5=1.0,
        recall_at_10=1.0,
        mrr_at_10=1.0,
        stale_vector_count=0,
        duplicate_vector_count=0,
        qdrant_disk_bytes=0,
        sync=SyncReport(added=3, units=3),
        top1_accuracy=1.0,
        query_results=rows,
    )


def _row(query_id, expected, top_results, *, tags=None, first_hit_rank=None):
    return {
        "id": query_id,
        "modality": "image",
        "tags": tags or ["image", "hard-negative"],
        "expected_paths": [expected],
        "first_hit_rank": first_hit_rank,
        "hit_at_1": first_hit_rank == 1,
        "recall_at_5": 1.0 if first_hit_rank and first_hit_rank <= 5 else 0.0,
        "mrr_at_10": (1.0 / first_hit_rank) if first_hit_rank else 0.0,
        "top_results": [
            {"rank": index, "relative_path": path, "unit_type": "image", "score": 1.0}
            for index, path in enumerate(top_results, start=1)
        ],
    }


def test_attribute_rerank_improves_candidate_targeted_slice(monkeypatch, tmp_path: Path):
    golden = tmp_path / "golden.json"
    golden.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "id": "printer-query",
                        "query": "red printer contract paper image",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    candidate_rows = [
        _row(
            "printer-query",
            "printer_red_contract.png",
            ["printer_blue_contract.png", "printer_red_contract.png"],
            first_hit_rank=2,
        )
    ]
    selected_rows = [
        _row(
            "printer-query",
            "printer_red_contract.png",
            ["printer_red_contract.png", "printer_blue_contract.png"],
            first_hit_rank=1,
        )
    ]

    def fake_run_benchmark(corpus, queries, settings, golden_path=None):
        if settings.vision_model_name == "clip-model":
            return _report(candidate_rows)
        return _report(selected_rows)

    monkeypatch.setattr(experiment, "run_benchmark", fake_run_benchmark)

    report = experiment.run_experiment(
        corpus=tmp_path / "corpus",
        golden=golden,
        selected_model="siglip-model",
        candidate_model="clip-model",
        settings=Settings(data_dir=tmp_path / "data"),
    )

    clip_row = next(row for row in report["models"] if row["model"] == "clip-model")
    assert report["overall_decision"] == "candidate-improved-hold-for-product"
    assert clip_row["targeted_weak_slices"]["delta"]["top1_accuracy"] > 0.0
    assert clip_row["rerank_examples"][0]["reranked_first_hit_rank"] == 1
    assert report["product_runtime_change"] is False


def test_metadata_keyed_alias_fixture_reranks_without_filename_terms(
    monkeypatch,
    tmp_path: Path,
):
    golden = tmp_path / "golden.json"
    golden.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "id": "printer-query",
                        "query": "red printer contract paper image",
                        "relevant": [{"relative_path": "asset_0001.png"}],
                        "image_key": {
                            "object": "printer",
                            "color": "red",
                            "context": "contract",
                        },
                        "tags": ["image", "hard-negative", "non-filename"],
                    },
                    {
                        "id": "blue-printer-query",
                        "query": "blue printer contract paper image",
                        "relevant": [{"relative_path": "asset_0002.png"}],
                        "image_key": {
                            "object": "printer",
                            "color": "blue",
                            "context": "contract",
                        },
                        "tags": ["image", "hard-negative", "non-filename"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    candidate_rows = [
        _row(
            "printer-query",
            "asset_0001.png",
            ["asset_0002.png", "asset_0001.png"],
            first_hit_rank=2,
        )
    ]
    selected_rows = [
        _row(
            "printer-query",
            "asset_0001.png",
            ["asset_0001.png", "asset_0002.png"],
            first_hit_rank=1,
        )
    ]

    def fake_run_benchmark(corpus, queries, settings, golden_path=None):
        if settings.vision_model_name == "clip-model":
            return _report(candidate_rows)
        return _report(selected_rows)

    monkeypatch.setattr(experiment, "run_benchmark", fake_run_benchmark)

    report = experiment.run_experiment(
        corpus=tmp_path / "corpus",
        golden=golden,
        selected_model="siglip-model",
        candidate_model="clip-model",
        settings=Settings(data_dir=tmp_path / "data"),
    )

    clip_row = next(row for row in report["models"] if row["model"] == "clip-model")
    assert report["corpus_style"] == "metadata-keyed"
    assert report["attribute_source"] == "golden:image_key"
    assert report["diagnostic_fixture"]["semantic_filename_match_count"] == 0
    assert report["diagnostic_fixture"]["filename_independence_gate"] is True
    assert "benchmark image_key metadata" in report["candidate_reranker"]["input"]
    assert clip_row["targeted_weak_slices"]["delta"]["top1_accuracy"] > 0.0
    assert clip_row["rerank_examples"][0]["reranked_top1"] == "asset_0001.png"
    assert report["product_runtime_change"] is False


def test_attribute_rerank_preserves_selected_model_non_regression(monkeypatch, tmp_path: Path):
    golden = tmp_path / "golden.json"
    golden.write_text(
        json.dumps({"queries": [{"id": "q", "query": "blue laptop office"}]}),
        encoding="utf-8",
    )
    rows = [
        _row(
            "q",
            "office_blue_laptop.png",
            ["office_blue_laptop.png", "office_gray_laptop.png"],
            first_hit_rank=1,
        )
    ]

    monkeypatch.setattr(
        experiment,
        "run_benchmark",
        lambda corpus, queries, settings, golden_path=None: _report(rows),
    )

    report = experiment.run_experiment(
        corpus=tmp_path / "corpus",
        golden=golden,
        selected_model="siglip-model",
        candidate_model="clip-model",
        settings=Settings(data_dir=tmp_path / "data"),
    )

    siglip_row = next(row for row in report["models"] if row["model"] == "siglip-model")
    assert siglip_row["non_regression_gate"]["passed"] is True
    assert siglip_row["aggregate"]["delta"]["top1_accuracy"] == 0.0


def test_cli_writes_sanitized_experiment_report(monkeypatch, tmp_path: Path):
    golden = tmp_path / "golden.json"
    golden.write_text(
        json.dumps({"queries": [{"id": "q", "query": "red printer contract"}]}),
        encoding="utf-8",
    )
    rows = [
        _row(
            "q",
            "printer_red_contract.png",
            ["printer_blue_contract.png", "printer_red_contract.png"],
            first_hit_rank=2,
        )
    ]

    monkeypatch.setattr(
        experiment,
        "run_benchmark",
        lambda corpus, queries, settings, golden_path=None: _report(rows),
    )
    output = tmp_path / "vision_weak_slice_experiment.json"

    exit_code = experiment.main(
        [
            "--corpus",
            str(tmp_path / "corpus"),
            "--golden",
            str(golden),
            "--selected-model",
            "siglip-model",
            "--candidate-model",
            "clip-model",
            "--out",
            str(output),
        ]
    )

    assert exit_code == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["corpus"] == "<external>/corpus"
    assert written["golden"] == "<external>/golden.json"
    assert written["candidate_reranker"]["label_usage"].startswith("golden labels")
