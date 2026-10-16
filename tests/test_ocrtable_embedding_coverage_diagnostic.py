from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_embedding_coverage_diagnostic as diagnostic
from locallens.core.types import SearchResult


def _result(path: str, unit_type: str = "pdf_table", score: float = 1.0):
    return SearchResult(
        score=score,
        modality="text",
        relative_path=path,
        page_no=1,
        snippet="sanitized",
        unit_type=unit_type,
        payload={"table_no": 0} if unit_type == "pdf_table" else {},
    )


def test_expanded_query_uses_global_unit_intent_terms_only():
    expanded, added = diagnostic._expanded_query(
        "unit_intent_expansion",
        "budget review table",
        max_extra_terms=4,
    )

    assert expanded.startswith("budget review table")
    assert "row" in added
    assert "column" in added
    assert "cache" not in added
    assert len(added) <= 4


def test_bilingual_alias_expansion_can_recover_without_target_label():
    item = {
        "query": "로컬 검색 승인 문서",
        "top_k": 10,
        "negative_paths": ["distractor_notes_01.pdf"],
    }
    target = {
        "relative_path": "table_budget_review_01.pdf",
        "unit_type": "pdf_table",
        "table_no": 0,
        "max_rank": 5,
    }

    def searcher(query: str, top_k: int):
        if "local" in query and "approval" in query:
            return [_result("table_budget_review_01.pdf")]
        return [_result("distractor_notes_01.pdf", "document")]

    row = diagnostic._evaluate_expansion_candidate(
        "bilingual_alias_expansion",
        item,
        target=target,
        searcher=searcher,
        top_k=10,
        deep_top_k=50,
        max_extra_terms=8,
    )

    assert row["target_hit_deep_k"] is True
    assert row["negative_top1"] is False
    assert row["label_aware"] is False
    assert row["product_runtime_eligible"] is False


def test_diagnose_query_keeps_raw_query_and_body_out_of_report():
    item = {
        "query_id": "coverage-miss",
        "query": "budget review table metric",
        "top_k": 10,
        "negative_paths": ["distractor_notes_01.pdf"],
        "relevant": [
            {
                "relative_path": "table_budget_review_01.pdf",
                "unit_type": "pdf_table",
                "table_no": 0,
                "max_rank": 5,
            }
        ],
    }
    payloads = [
        {
            "relative_path": "table_budget_review_01.pdf",
            "unit_type": "pdf_table",
            "table_no": 0,
            "text_preview": "budget review table metric evidence",
        }
    ]

    row = diagnostic._diagnose_query(
        1,
        item,
        payloads=payloads,
        searcher=lambda query, top_k: [_result("distractor_notes_01.pdf", "document")],
        top_k=10,
        deep_top_k=50,
        max_extra_terms=8,
    )

    assert row["case_ordinal"] == 1
    assert row["included_in_coverage_diagnostic"] is True
    assert "query_id" not in row
    assert "target_document" not in row
    assert "query" not in row
    assert "body" not in row
    assert "text" not in row
    assert row["candidates"]["baseline"]["target_hit_deep_k"] is False


def test_summary_reports_deep_miss_reduction_quantitatively():
    rows = [
        {
            "deep_miss_classification": "embedding_coverage",
            "deep_miss_primary_reason": "target_lexically_strong_but_vector_missed",
            "candidates": {
                "baseline": {
                    "target_hit_top_k": False,
                    "target_hit_deep_k": False,
                    "passed": False,
                    "negative_top1": False,
                    "negative_before_target_count": 0,
                    "added_term_count": 0,
                },
                "normalized_query": {
                    "target_hit_top_k": False,
                    "target_hit_deep_k": False,
                    "passed": False,
                    "negative_top1": False,
                    "negative_before_target_count": 0,
                    "added_term_count": 2,
                },
                "unit_intent_expansion": {
                    "target_hit_top_k": True,
                    "target_hit_deep_k": True,
                    "passed": True,
                    "negative_top1": False,
                    "negative_before_target_count": 0,
                    "added_term_count": 2,
                },
                "bilingual_alias_expansion": {
                    "target_hit_top_k": False,
                    "target_hit_deep_k": True,
                    "passed": False,
                    "negative_top1": False,
                    "negative_before_target_count": 0,
                    "added_term_count": 3,
                },
                "combined_query_family_expansion": {
                    "target_hit_top_k": True,
                    "target_hit_deep_k": True,
                    "passed": True,
                    "negative_top1": False,
                    "negative_before_target_count": 0,
                    "added_term_count": 4,
                },
            },
        }
    ]

    summary = diagnostic._summarize_queries(rows)
    aggregate = diagnostic._aggregate_modes(
        {"table": {"summary": summary, "coverage_queries": rows}}
    )

    assert summary["baseline"]["deep_miss_remaining_count"] == 1
    assert summary["unit_intent_expansion"]["target_hit_deep_k_rate"] == 1.0
    assert aggregate["deep_miss_reduction_from_baseline"] == 1
    assert aggregate["max_deep_miss_reduction_from_baseline"] == 1
    assert aggregate["best_candidate"] == "unit_intent_expansion"
    assert aggregate["best_deep_recovery_candidate"] == "unit_intent_expansion"
    assert aggregate["negative_top1_regressed"] is False


def test_candidate_contracts_disallow_target_derived_expansion():
    assert all("target" not in candidate for candidate in diagnostic.CANDIDATES)
    assert all(
        not contract["uses_target_label"]
        and not contract["uses_target_content_signal"]
        and not contract["product_runtime_eligible"]
        for contract in diagnostic._candidate_contracts().values()
    )


def test_main_rejects_raw_report_keys(tmp_path: Path):
    report = {"rows": [{"raw_query": "unsafe"}]}

    findings = diagnostic._raw_report_key_findings(
        report,
        str(tmp_path / "report.json"),
    )

    assert findings
