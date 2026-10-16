from __future__ import annotations

import json
from pathlib import Path

from benchmarks import ocrtable_korean_query_normalization_poc as poc


def _summary(
    *,
    evaluated: int = 75,
    recall: float = 0.82,
    mrr: float = 0.8,
    top1: float = 0.79,
    misses: int = 13,
    top1_failures: int = 16,
) -> dict:
    return {
        "evaluated_queries": evaluated,
        "recall_at_5": recall,
        "mrr_at_10": mrr,
        "top1_accuracy": top1,
        "top1_failures": top1_failures,
        "miss_at_5_count": misses,
        "search_latency_ms": {"p50": 1.0, "p95": 2.0},
    }


def _run_report() -> dict:
    return {
        "corpus": {
            "pdf_files": 120,
            "original_korean_queries": 25,
            "harder_variant_queries": 75,
        },
        "runtime": {"text_embedding_profile": "sentence-transformers:test"},
        "indexed_units": 120,
        "manifest_units": 120,
        "sync": {
            "added": 120,
            "updated": 0,
            "deleted": 0,
            "skipped": 0,
            "failed": 0,
            "ocr_attempted": 25,
            "ocr_succeeded": 25,
            "ocr_empty": 0,
            "cache_result_hits": 0,
            "cache_result_misses": 25,
            "cache_entries_written": 25,
        },
        "index_latency_ms": 100.0,
        "variant_counts": {
            "compact_korean": 25,
            "english_alias": 25,
            "syllable_spaced": 25,
        },
        "candidate_summaries": {
            "product_off": {
                "original": _summary(evaluated=25, recall=1.0, mrr=0.95, top1=0.9),
                "harder": _summary(),
            },
            "product_alias_backfill": {
                "original": _summary(evaluated=25, recall=1.0, mrr=0.97, top1=0.92),
                "harder": _summary(
                    recall=0.96,
                    mrr=0.88,
                    top1=0.86,
                    misses=3,
                    top1_failures=10,
                ),
            },
        },
    }


def test_kocr_query_normalization_poc_records_product_path_signal_without_raw_fields(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(poc, "_run_product_path_poc", lambda **_kwargs: _run_report())

    report = poc.run_korean_query_normalization_poc(pdf_dir=tmp_path)

    assert report["schema_version"] == "ocrtable-korean-query-normalization-poc-v1"
    assert report["product_path_poc"] is True
    assert report["benchmark_only"] is False
    assert report["default_enabled"] is False
    assert report["product_default_changed"] is False
    assert report["public_quality_claim_allowed"] is False
    assert report["runtime"]["normalizer_scope"] == (
        "text-search-embedding-and-text-lexical-rerank-only"
    )
    assert report["candidate_summaries"]["product_alias_backfill"]["harder"][
        "recall_at_5"
    ] == 0.96
    assert report["improvement_vs_product_off"]["harder"]["miss_at_5_count_delta"] == -10
    assert all(report["acceptance"].values())
    assert (
        report["decision"]
        == "default-off-kocr-query-normalization-candidate-ready-private"
    )
    assert (
        report["next_work_order"][0]["id"]
        == "LL-OCRTABLE-007-KOCR-QUERY-NORMALIZATION-COMMIT"
    )
    assert not poc._raw_report_key_findings(report, "kocr-normalization-poc.json")
    serialized = json.dumps(report, ensure_ascii=False)
    assert "query_id" not in serialized
    assert "relative_path" not in serialized
    assert "target_document" not in serialized
    assert "tesseract.exe" not in serialized


def test_kocr_query_normalization_poc_holds_when_product_gate_fails(
    monkeypatch,
    tmp_path: Path,
):
    run = _run_report()
    run["candidate_summaries"]["product_alias_backfill"]["harder"] = _summary(
        recall=0.84,
        mrr=0.7,
        top1=0.65,
    )
    monkeypatch.setattr(poc, "_run_product_path_poc", lambda **_kwargs: run)

    report = poc.run_korean_query_normalization_poc(pdf_dir=tmp_path)

    assert report["acceptance"]["harder_recall_at_5_gate"] is False
    assert report["decision"] == "hold-default-off-kocr-query-normalization-poc"
    assert (
        report["next_work_order"][0]["id"]
        == "LL-OCRTABLE-007-KOCR-QUERY-NORMALIZATION-HOLD"
    )
