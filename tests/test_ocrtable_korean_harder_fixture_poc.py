from __future__ import annotations

import json
from pathlib import Path

from benchmarks import ocrtable_korean_harder_fixture_poc as poc


def _summary(
    *,
    evaluated: int = 75,
    recall: float = 0.8,
    mrr: float = 0.6,
    top1: float = 0.4,
    misses: int = 15,
    top1_failures: int = 45,
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
            "original_as_is": _summary(evaluated=25, recall=1.0, mrr=0.95, top1=0.9),
            "harder_as_is": _summary(),
            "alias_backfill": _summary(
                recall=0.84,
                mrr=0.66,
                top1=0.45,
                misses=12,
                top1_failures=41,
            ),
        },
        "harder_variant_summaries": {
            "compact_korean": {
                "harder_as_is": _summary(evaluated=25),
                "alias_backfill": _summary(evaluated=25),
            },
            "english_alias": {
                "harder_as_is": _summary(evaluated=25, recall=0.5, mrr=0.3),
                "alias_backfill": _summary(evaluated=25, recall=0.62, mrr=0.45),
            },
            "syllable_spaced": {
                "harder_as_is": _summary(evaluated=25),
                "alias_backfill": _summary(evaluated=25),
            },
        },
    }


def test_korean_harder_fixture_poc_records_benchmark_signal_without_raw_fields(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        poc,
        "_run_korean_harder_fixture",
        lambda **_kwargs: _run_report(),
    )

    report = poc.run_korean_harder_fixture_poc(pdf_dir=tmp_path)

    assert report["schema_version"] == "ocrtable-korean-harder-fixture-poc-v1"
    assert report["benchmark_only"] is True
    assert report["product_runtime_changed"] is False
    assert report["public_quality_claim_allowed"] is False
    assert report["corpus"]["original_korean_queries"] == 25
    assert report["corpus"]["harder_variant_queries"] == 75
    assert report["runtime"]["tessdata_dir_configured"] is False
    assert report["sync"]["ocr_succeeded"] == 25
    assert report["variant_counts"] == {
        "compact_korean": 25,
        "english_alias": 25,
        "syllable_spaced": 25,
    }
    assert report["improvement_vs_reference"]["recall_at_5_delta"] == 0.04
    assert report["improvement_vs_reference"]["mrr_at_10_delta"] == 0.06
    assert report["improvement_vs_reference"]["miss_at_5_count_delta"] == -3
    assert all(report["acceptance"].values())
    assert (
        report["decision"]
        == "benchmark-only-kocr-query-repair-signal-recorded"
    )
    assert (
        report["next_work_order"][0]["id"]
        == "LL-OCRTABLE-007-KOCR-QUERY-NORMALIZATION-DECIDE"
    )
    assert not poc._raw_report_key_findings(report, "kocr-harder-poc.json")
    serialized = json.dumps(report, ensure_ascii=False)
    assert "query_id" not in serialized
    assert "relative_path" not in serialized
    assert "target_document" not in serialized
    assert "tesseract.exe" not in serialized


def test_korean_harder_fixture_poc_holds_when_original_fixture_regresses(
    monkeypatch,
    tmp_path: Path,
):
    run = _run_report()
    run["candidate_summaries"]["original_as_is"] = _summary(
        evaluated=25,
        recall=0.72,
        mrr=0.5,
        top1=0.4,
    )
    monkeypatch.setattr(
        poc,
        "_run_korean_harder_fixture",
        lambda **_kwargs: run,
    )

    report = poc.run_korean_harder_fixture_poc(pdf_dir=tmp_path)

    assert report["acceptance"]["original_recall_at_5_non_regression"] is False
    assert report["decision"] == "hold-kocr-harder-fixture-poc"
    assert (
        report["next_work_order"][0]["id"]
        == "LL-OCRTABLE-007-KOCR-HARDER-FIXTURE-HOLD"
    )


def test_harder_items_generate_three_sanitized_variant_families():
    items = [
        {
            "query": "로컬 검색 승인 문서 보관함 이십칠",
            "relevant": [{"relative_path": "private.pdf"}],
        }
    ]

    harder = poc._harder_items(items)

    assert [item["variant_type"] for item in harder] == [
        "compact_korean",
        "syllable_spaced",
        "english_alias",
    ]
    assert harder[0]["query"] == "로컬검색승인문서보관함이십칠"
    assert harder[1]["query"].startswith("로 컬 검 색")
    assert harder[2]["query"] == "local search approval document archive 27"
    assert poc._alias_backfill_query("local search archive 27").endswith(
        "로컬 검색 보관함 이십칠"
    )
