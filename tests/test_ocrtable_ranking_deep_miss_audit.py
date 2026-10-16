from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_ranking_deep_miss_audit as audit


def _raw_report():
    return {
        "corpus": {
            "pdf_files": 2,
            "hard_negative_queries": 2,
        },
        "aggregate": {
            "evaluated_queries": 2,
        },
        "modes": {
            "table": {
                "deep_miss_queries": [
                    {
                        "query_id": "should-not-leak",
                        "mode": "table",
                        "target_document": "table_target.pdf",
                        "target_unit_type": "pdf_table",
                        "target_payload_count": 1,
                        "target_preview_term_count": 12,
                        "query_term_count": 6,
                        "target_filename_overlap_ratio": 0.5,
                        "target_preview_overlap_ratio": 1.0,
                        "negative_preview_overlap_ratio": 0.2,
                        "negative_seen_deep_k": False,
                        "classification": "embedding_coverage",
                        "primary_reason": "target_lexically_strong_but_vector_missed",
                    }
                ]
            },
            "ocr": {
                "deep_miss_queries": [
                    {
                        "query_id": "also-should-not-leak",
                        "mode": "ocr",
                        "target_document": "ocr_target.pdf",
                        "target_unit_type": "pdf_ocr_text",
                        "target_payload_count": 1,
                        "target_preview_term_count": 3,
                        "query_term_count": 8,
                        "target_filename_overlap_ratio": 0.25,
                        "target_preview_overlap_ratio": 0.375,
                        "negative_preview_overlap_ratio": 0.25,
                        "negative_seen_deep_k": False,
                        "classification": "query_contract",
                        "primary_reason": "target_preview_sparse",
                    }
                ]
            },
        },
    }


def test_deep_miss_audit_outputs_ordinal_only_cases(monkeypatch, tmp_path: Path):
    (tmp_path / "table_target.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "ocr_target.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(audit, "run_deep_miss_audit", lambda **_kwargs: _raw_report())

    report = audit.run_ranking_deep_miss_audit(pdf_dir=tmp_path)

    assert report["schema_version"] == "ocrtable-ranking-deep-miss-audit-v1"
    assert report["case_identifier_policy"] == "ordinal-only"
    assert report["stable_document_identifier_recorded"] is False
    assert report["aggregate"]["deep_miss_count"] == 2
    assert report["aggregate"]["cause_family_counts"] == {
        "embedding": 1,
        "extractor_contract": 1,
    }
    assert report["acceptance"]["ordinal_only_cases"] is True
    assert report["acceptance"]["query_body_absent"] is True
    assert not audit._raw_report_key_findings(report, "deep-miss.json")
    serialized = str(report)
    assert "query_id" not in serialized
    assert "should-not-leak" not in serialized
    assert "target_document" not in serialized
    assert "table_target.pdf" not in serialized
    assert "ocr_target.pdf" not in serialized


def test_cause_family_separates_fixture_extractor_embedding_and_query():
    assert (
        audit._cause_family(
            {"target_payload_count": 0, "primary_reason": "target_payload_missing"},
            target_document_exists=False,
        )
        == "fixture_contract"
    )
    assert (
        audit._cause_family(
            {"target_payload_count": 0, "primary_reason": "target_payload_missing"},
            target_document_exists=True,
        )
        == "extractor_contract"
    )
    assert (
        audit._cause_family(
            {"target_payload_count": 1, "primary_reason": "target_preview_sparse"},
            target_document_exists=True,
        )
        == "extractor_contract"
    )
    assert (
        audit._cause_family(
            {
                "target_payload_count": 1,
                "primary_reason": "negative_lexical_signal_stronger",
            },
            target_document_exists=True,
        )
        == "query_contract"
    )
    assert (
        audit._cause_family(
            {
                "target_payload_count": 1,
                "primary_reason": "target_lexically_strong_but_vector_missed",
            },
            target_document_exists=True,
        )
        == "embedding"
    )
