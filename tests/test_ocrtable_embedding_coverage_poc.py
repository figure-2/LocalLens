from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_embedding_coverage_poc as poc


def _deep_miss_report():
    return {
        "corpus": {
            "pdf_files": 120,
            "hard_negative_queries": 18,
        },
        "aggregate": {
            "evaluated_queries": 18,
            "deep_miss_count": 7,
            "deep_miss_rate": 0.388889,
            "cause_family_counts": {
                "embedding": 3,
                "embedding_or_query_embedding": 2,
                "extractor_contract": 1,
                "mixed_query_embedding": 1,
            },
        },
    }


def _coverage_report():
    return {
        "aggregate": {
            "evaluated_embedding_coverage_queries": 5,
            "best_deep_recovery_candidate": "normalized_query",
            "max_deep_miss_reduction_from_baseline": 3,
            "max_target_hit_deep_k_delta": 0.6,
            "negative_top1_regressed": False,
            "classification_counts": {"embedding_coverage": 5},
            "primary_reason_counts": {
                "target_lexically_strong_but_vector_missed": 3,
                "target_and_negative_absent_from_deep_k": 2,
            },
            "candidate_summaries": {
                "baseline": {
                    "deep_miss_remaining_count": 5,
                    "negative_top1_count": 0,
                    "negative_before_target_count": 2,
                },
                "normalized_query": {
                    "deep_miss_remaining_count": 2,
                    "negative_top1_count": 0,
                    "negative_before_target_count": 1,
                },
            },
        }
    }


def test_embedding_coverage_poc_reports_reduction_without_product_change(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        poc,
        "run_ranking_deep_miss_audit",
        lambda **_kwargs: _deep_miss_report(),
    )
    monkeypatch.setattr(
        poc,
        "run_embedding_coverage_diagnostic",
        lambda **_kwargs: _coverage_report(),
    )

    report = poc.run_embedding_coverage_poc(pdf_dir=tmp_path)

    assert report["schema_version"] == "ocrtable-embedding-coverage-poc-v1"
    assert report["benchmark_only"] is True
    assert report["product_runtime_changed"] is False
    assert report["stable_document_identifier_recorded"] is False
    assert report["poc_result"]["selected_candidate"] == "normalized_query"
    assert report["poc_result"]["embedding_deep_miss_reduction"] == 3
    assert report["poc_result"]["projected_total_deep_miss_remaining"] == 4
    assert report["poc_result"]["negative_top1_delta"] == 0
    assert report["acceptance"]["deep_miss_count_decreases"] is True
    assert report["acceptance"]["negative_top1_non_regression"] is True
    assert (
        report["decision"]
        == "benchmark-only-coverage-improved-product-still-blocked"
    )
    assert not poc._raw_report_key_findings(report, "coverage-poc.json")
    serialized = str(report)
    assert "query_id" not in serialized
    assert "relative_path" not in serialized
    assert "target_document" not in serialized
    assert "tesseract.exe" not in serialized


def test_embedding_coverage_poc_holds_when_negative_top1_regresses(
    monkeypatch,
    tmp_path: Path,
):
    coverage = _coverage_report()
    coverage["aggregate"]["candidate_summaries"]["normalized_query"][
        "negative_top1_count"
    ] = 1
    monkeypatch.setattr(
        poc,
        "run_ranking_deep_miss_audit",
        lambda **_kwargs: _deep_miss_report(),
    )
    monkeypatch.setattr(
        poc,
        "run_embedding_coverage_diagnostic",
        lambda **_kwargs: coverage,
    )

    report = poc.run_embedding_coverage_poc(pdf_dir=tmp_path)

    assert report["acceptance"]["negative_top1_non_regression"] is False
    assert report["decision"] == "hold-embedding-coverage-poc"
