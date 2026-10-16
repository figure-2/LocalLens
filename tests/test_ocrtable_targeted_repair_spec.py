from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_targeted_repair_spec as spec


def _remaining_blocker_report():
    return {
        "corpus": {
            "pdf_files": 120,
            "hard_negative_queries": 18,
        },
        "baseline_deep_miss_count": 7,
        "remaining_blocker_count": 4,
        "blocker_family_counts": {
            "extractor_contract": 1,
            "mixed_query_embedding": 1,
            "unrecovered_embedding": 2,
        },
        "recommended_repair_track_counts": {
            "extractor_preview_or_ocr_profile_repair": 1,
            "query_expansion_or_embedding_profile_repair": 2,
            "separate_query_contract_from_embedding_coverage": 1,
        },
        "cases": [
            {
                "case_ordinal": 1,
                "mode": "ocr",
                "target_unit_type": "pdf_ocr_text",
                "blocker_family": "extractor_contract",
                "primary_reason": "target_preview_sparse",
                "target_preview_term_count": 3,
                "target_preview_overlap_ratio": 0.375,
                "negative_seen_deep_k": False,
                "selected_candidate": "not_applicable",
                "recommended_repair_track": (
                    "extractor_preview_or_ocr_profile_repair"
                ),
            },
            {
                "case_ordinal": 2,
                "mode": "ocr",
                "target_unit_type": "pdf_ocr_text",
                "blocker_family": "mixed_query_embedding",
                "primary_reason": "negative_present_and_target_missing",
                "target_preview_term_count": 6,
                "target_preview_overlap_ratio": 0.0,
                "negative_seen_deep_k": True,
                "selected_candidate": "not_applicable",
                "recommended_repair_track": (
                    "separate_query_contract_from_embedding_coverage"
                ),
            },
            {
                "case_ordinal": 3,
                "mode": "table",
                "target_unit_type": "pdf_table",
                "blocker_family": "unrecovered_embedding",
                "primary_reason": "target_and_negative_absent_from_deep_k",
                "target_preview_term_count": 8,
                "target_preview_overlap_ratio": 1.0,
                "negative_seen_deep_k": False,
                "selected_candidate": "normalized_query",
                "recommended_repair_track": (
                    "query_expansion_or_embedding_profile_repair"
                ),
            },
            {
                "case_ordinal": 4,
                "mode": "table",
                "target_unit_type": "pdf_table",
                "blocker_family": "unrecovered_embedding",
                "primary_reason": "target_lexically_strong_but_vector_missed",
                "target_preview_term_count": 9,
                "target_preview_overlap_ratio": 1.0,
                "negative_seen_deep_k": False,
                "selected_candidate": "normalized_query",
                "recommended_repair_track": (
                    "query_expansion_or_embedding_profile_repair"
                ),
            },
        ],
    }


def test_targeted_repair_spec_splits_extractor_and_embedding_tracks(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        spec,
        "run_remaining_blocker_audit",
        lambda **_kwargs: _remaining_blocker_report(),
    )

    report = spec.run_targeted_repair_spec(pdf_dir=tmp_path)

    assert report["schema_version"] == "ocrtable-targeted-repair-spec-v1"
    assert report["benchmark_only"] is True
    assert report["product_runtime_changed"] is False
    assert report["case_identifier_policy"] == "ordinal-only"
    assert report["case_identifier_values_recorded"] is False
    assert report["repair_specs"]["extractor_preview_repair"]["case_count"] == 1
    assert report["repair_specs"]["query_embedding_repair"]["case_count"] == 3
    assert report["aggregate"]["remaining_cases_covered_by_specs"] == 4
    assert report["acceptance"]["default_off"] is True
    assert report["decision"] == "targeted-repair-spec-ready-benchmark-poc-required"
    assert not spec._raw_report_key_findings(report, "targeted-spec.json")
    serialized = str(report)
    assert "query_id" not in serialized
    assert "relative_path" not in serialized
    assert "target_document" not in serialized
    assert "tesseract.exe" not in serialized


def test_targeted_repair_spec_holds_when_no_targeted_specs(monkeypatch, tmp_path: Path):
    empty_report = _remaining_blocker_report()
    empty_report["remaining_blocker_count"] = 0
    empty_report["blocker_family_counts"] = {}
    empty_report["recommended_repair_track_counts"] = {}
    empty_report["cases"] = []
    monkeypatch.setattr(
        spec,
        "run_remaining_blocker_audit",
        lambda **_kwargs: empty_report,
    )

    report = spec.run_targeted_repair_spec(pdf_dir=tmp_path)

    assert report["aggregate"]["specified_spec_count"] == 0
    assert report["acceptance"]["at_least_one_targeted_spec"] is False
    assert report["decision"] == "hold-targeted-repair-spec"
