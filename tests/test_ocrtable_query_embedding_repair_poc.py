from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_query_embedding_repair_poc as poc


def _run_report():
    return {
        "corpus": {
            "pdf_files": 120,
            "hard_negative_queries": 10,
        },
        "targeted_case_count": 3,
        "targeted_case_family_counts": {
            "mixed_query_embedding": 1,
            "unrecovered_embedding": 2,
        },
        "candidate_summaries": {
            "baseline": {
                "evaluated_cases": 3,
                "target_hit_top_k_count": 0,
                "target_hit_top_k_rate": 0.0,
                "target_hit_deep_k_count": 0,
                "target_hit_deep_k_rate": 0.0,
                "remaining_blocker_count": 3,
                "passed_cases": 0,
                "pass_rate": 0.0,
                "negative_top1_count": 0,
                "negative_before_target_count": 1,
                "total_added_terms": 0,
            },
            "normalized_query": {
                "evaluated_cases": 3,
                "target_hit_top_k_count": 0,
                "target_hit_top_k_rate": 0.0,
                "target_hit_deep_k_count": 0,
                "target_hit_deep_k_rate": 0.0,
                "remaining_blocker_count": 3,
                "passed_cases": 0,
                "pass_rate": 0.0,
                "negative_top1_count": 0,
                "negative_before_target_count": 1,
                "total_added_terms": 0,
            },
            "ocr_profile_expansion_v2": {
                "evaluated_cases": 3,
                "target_hit_top_k_count": 1,
                "target_hit_top_k_rate": 0.333333,
                "target_hit_deep_k_count": 1,
                "target_hit_deep_k_rate": 0.333333,
                "remaining_blocker_count": 2,
                "passed_cases": 1,
                "pass_rate": 0.333333,
                "negative_top1_count": 0,
                "negative_before_target_count": 0,
                "total_added_terms": 4,
            },
        },
    }


def test_query_embedding_repair_poc_reports_targeted_reduction(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(poc, "_run_targeted_candidates", lambda **_kwargs: _run_report())

    report = poc.run_query_embedding_repair_poc(pdf_dir=tmp_path)

    assert report["schema_version"] == "ocrtable-query-embedding-repair-poc-v1"
    assert report["benchmark_only"] is True
    assert report["product_runtime_changed"] is False
    assert report["selected_candidate"] == "ocr_profile_expansion_v2"
    assert report["improvement_vs_reference"]["remaining_blocker_count_delta"] == -1
    assert report["acceptance"]["remaining_blockers_decrease"] is True
    assert (
        report["decision"]
        == "benchmark-only-query-embedding-improved-product-still-blocked"
    )
    assert not poc._raw_report_key_findings(report, "query-embedding-poc.json")
    serialized = str(report)
    assert "query_id" not in serialized
    assert "relative_path" not in serialized
    assert "target_document" not in serialized
    assert "tesseract.exe" not in serialized


def test_query_embedding_repair_poc_holds_when_no_candidate_beats_reference(
    monkeypatch,
    tmp_path: Path,
):
    run = _run_report()
    run["candidate_summaries"]["ocr_profile_expansion_v2"] = dict(
        run["candidate_summaries"]["normalized_query"]
    )
    monkeypatch.setattr(poc, "_run_targeted_candidates", lambda **_kwargs: run)

    report = poc.run_query_embedding_repair_poc(pdf_dir=tmp_path)

    assert report["selected_candidate"] == "normalized_query"
    assert report["acceptance"]["remaining_blockers_decrease"] is False
    assert report["decision"] == "hold-query-embedding-repair-poc"
