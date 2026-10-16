from __future__ import annotations

from locallens.core.types import SyncReport

from benchmarks.ocrtable_extractor_readthrough_live_eval import _aggregate_decision
from benchmarks.ocrtable_extractor_readthrough_live_eval import _mode_report
from benchmarks.ocrtable_extractor_readthrough_live_eval import _optional_signatures


def test_optional_signatures_ignore_non_optional_units_and_sort():
    records = [
        {"payload": {"unit_type": "chunk", "relative_path": "b.pdf"}},
        {
            "payload": {
                "unit_type": "pdf_table",
                "relative_path": "b.pdf",
                "page_no": 1,
                "table_no": 0,
                "bbox": [0, 0, 1, 1],
                "extractor_profile": "pdfplumber-local-table-v1",
                "text_preview": "B table",
                "has_text_vector": True,
                "mtime_ns": 123,
            }
        },
        {
            "payload": {
                "unit_type": "pdf_ocr_text",
                "relative_path": "a.pdf",
                "page_no": 1,
                "image_no": 0,
                "bbox": [0, 0, 1, 1],
                "extractor_profile": "tesseract-local-ocr-v1:eng:psm6",
                "text_preview": "A ocr",
                "has_text_vector": True,
                "mtime_ns": 456,
            }
        },
    ]

    signatures = _optional_signatures(records)

    assert [item["relative_path"] for item in signatures] == ["a.pdf", "b.pdf"]
    assert all("mtime_ns" not in item for item in signatures)


def test_mode_report_accepts_warm_hit_and_quality_match():
    cold = SyncReport(added=1, units=3, table_attempted=1, table_succeeded=1)
    warm = SyncReport(updated=1, units=3, cache_result_hits=1)
    cold_signatures = [{"relative_path": "a.pdf", "unit_type": "pdf_table"}]

    report = _mode_report(
        mode="table",
        docs=["a.pdf"],
        cold=cold,
        cold_latency_ms=100.0,
        cold_signatures=cold_signatures,
        warm_reports=[warm],
        warm_latencies=[5.0],
        warm_signature_matches=[True],
        manifest_cache_entries=1,
    )

    assert report["actual_extractor_used"] is True
    assert report["warm_cache_hit_rate"] == 1.0
    assert report["quality_non_regression"] is True
    assert report["cache_effect"]["extractor_attempts_skipped_on_warm"] is True


def test_aggregate_keeps_public_claim_on_hold_even_when_live_eval_passes():
    mode = {
        "actual_extractor_used": True,
        "failures_zero": True,
        "quality_non_regression": True,
        "cache_effect": {"warm_hit_rate_is_1": True},
        "documents": 5,
    }

    aggregate = _aggregate_decision({"table": mode, "ocr": mode})

    assert aggregate["live_eval_passed"] is True
    assert aggregate["public_evidence_decision"] == "hold"
    assert aggregate["public_performance_claim_allowed"] is False
    assert "corpus" in aggregate["hold_reasons"][0]
