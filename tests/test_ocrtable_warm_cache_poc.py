from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.ocrtable_warm_cache_poc import run_warm_cache_poc


def test_warm_cache_poc_preserves_metrics_and_hits(tmp_path: Path):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "table.pdf").write_bytes(b"%PDF-1.7\nsynthetic table\n")
    cold_report = tmp_path / "cold.json"
    cold_report.write_text(
        json.dumps(_cold_report(documents_detail=[_detail("q1", "table.pdf")])),
        encoding="utf-8",
    )
    cache_out = tmp_path / "cache.json"

    report = run_warm_cache_poc(
        cold_report_path=cold_report,
        pdf_dir=pdf_dir,
        cache_out=cache_out,
    )

    assert report["warm_cache_hit_rate"] == 1.0
    assert report["cache_entries_written"] == 1
    assert report["metrics_non_regression"] is True
    assert report["warm_metrics"] == report["cold_metrics"]
    assert report["warm_latency_ms"]["read_p95"] <= 1500.0
    assert report["claim_boundary"]["product_cache_claim_allowed"] is False
    assert cache_out.exists()
    assert str(pdf_dir) not in json.dumps(report)
    assert str(pdf_dir) not in cache_out.read_text(encoding="utf-8")


def test_warm_cache_poc_requires_document_details(tmp_path: Path):
    cold_report = tmp_path / "cold.json"
    cold_report.write_text(
        json.dumps(_cold_report(documents_detail="omitted")),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="document details"):
        run_warm_cache_poc(
            cold_report_path=cold_report,
            pdf_dir=tmp_path,
        )


def test_warm_cache_poc_rejects_non_ok_candidate(tmp_path: Path):
    cold = _cold_report(documents_detail=[_detail("q1", "table.pdf")])
    cold["candidates"][0]["status"] = "no-results"
    cold_report = tmp_path / "cold.json"
    cold_report.write_text(json.dumps(cold), encoding="utf-8")

    with pytest.raises(ValueError, match="status"):
        run_warm_cache_poc(
            cold_report_path=cold_report,
            pdf_dir=tmp_path,
        )


def _cold_report(*, documents_detail):
    return {
        "candidates": [
            {
                "candidate": "paddleocr-structure",
                "status": "ok",
                "det_model": "PP-OCRv5_mobile_det",
                "rec_model": "en_PP-OCRv5_mobile_rec",
                "model_cache_fingerprint": "cache-fingerprint",
                "runtime_options": {
                    "enable_mkldnn": False,
                    "cpu_threads": 0,
                    "render_scale": 0.75,
                },
                "recognition_min_score": 0.3,
                "locality": {"verification": "measured-runtime-guard"},
                "p50_latency_ms": 1400.0,
                "p95_latency_ms": 1800.0,
                "documents_detail": documents_detail,
            }
        ]
    }


def _detail(query_id: str, relative_path: str):
    return {
        "query_id": query_id,
        "relative_path": relative_path,
        "structured_output_term_recall": 0.75,
        "structured_cell_term_recall": 1.0,
        "table_context_term_recall": 1.0,
        "row_f1": 1.0,
        "cell_f1": 1.0,
        "mean_cell_text_f1": 1.0,
        "row_count": 3,
        "predicted_cell_count": 9,
    }
