from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_remaining_blocker_audit as audit


def _deep_miss_report():
    return {
        "corpus": {
            "pdf_files": 120,
            "hard_negative_queries": 18,
        },
        "aggregate": {
            "deep_miss_count": 3,
        },
        "cases": [
            {
                "case_ordinal": 1,
                "mode": "ocr",
                "target_unit_type": "pdf_ocr_text",
                "cause_family": "extractor_contract",
                "primary_reason": "target_preview_sparse",
                "target_preview_term_count": 3,
                "target_preview_overlap_ratio": 0.375,
                "negative_preview_overlap_ratio": 0.25,
                "negative_seen_deep_k": False,
            },
            {
                "case_ordinal": 2,
                "mode": "ocr",
                "target_unit_type": "pdf_ocr_text",
                "cause_family": "mixed_query_embedding",
                "primary_reason": "negative_present_and_target_missing",
                "target_preview_term_count": 6,
                "target_preview_overlap_ratio": 0.0,
                "negative_preview_overlap_ratio": 0.0,
                "negative_seen_deep_k": True,
            },
            {
                "case_ordinal": 3,
                "mode": "table",
                "target_unit_type": "pdf_table",
                "cause_family": "embedding",
                "primary_reason": "target_lexically_strong_but_vector_missed",
                "target_preview_term_count": 12,
                "target_preview_overlap_ratio": 1.0,
                "negative_preview_overlap_ratio": 0.2,
                "negative_seen_deep_k": False,
            },
        ],
    }


def _coverage_report():
    return {
        "aggregate": {
            "best_deep_recovery_candidate": "normalized_query",
        },
        "modes": {
            "table": {
                "coverage_queries": [
                    {
                        "case_ordinal": 1,
                        "mode": "table",
                        "target_unit_type": "pdf_table",
                        "deep_miss_primary_reason": (
                            "target_lexically_strong_but_vector_missed"
                        ),
                        "target_preview_term_count": 12,
                        "target_preview_overlap_ratio": 1.0,
                        "negative_preview_overlap_ratio": 0.2,
                        "candidates": {
                            "normalized_query": {
                                "target_hit_deep_k": False,
                                "negative_top1": False,
                                "negative_before_target_count": 0,
                            }
                        },
                    }
                ]
            }
        },
    }


def test_remaining_blocker_audit_splits_repair_tracks(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        audit,
        "run_ranking_deep_miss_audit",
        lambda **_kwargs: _deep_miss_report(),
    )
    monkeypatch.setattr(
        audit,
        "run_embedding_coverage_diagnostic",
        lambda **_kwargs: _coverage_report(),
    )

    report = audit.run_remaining_blocker_audit(pdf_dir=tmp_path)

    assert report["schema_version"] == "ocrtable-remaining-blocker-audit-v1"
    assert report["remaining_blocker_count"] == 3
    assert report["blocker_family_counts"] == {
        "extractor_contract": 1,
        "mixed_query_embedding": 1,
        "unrecovered_embedding": 1,
    }
    assert report["acceptance"]["ordinal_only_cases"] is True
    assert report["acceptance"]["query_body_absent"] is True
    assert report["acceptance"]["repair_paths_separated"] is True
    assert report["decision"] == "targeted-repair-plan-required-before-product-poc"
    assert not audit._raw_report_key_findings(report, "remaining.json")
    serialized = str(report)
    assert "query_id" not in serialized
    assert "relative_path" not in serialized
    assert "target_document" not in serialized
    assert "tesseract.exe" not in serialized


def test_remaining_blocker_audit_records_hold_when_no_cases():
    report = {
        "cases": [],
    }

    assert audit._acceptance(report["cases"])["remaining_blockers_recorded"] is False
    assert audit._decision(report["cases"]) == "hold-remaining-blocker-audit"
