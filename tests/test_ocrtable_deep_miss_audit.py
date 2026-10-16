from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_deep_miss_audit as audit
from locallens.core.types import SearchResult


def _result(path: str, unit_type: str = "pdf_table"):
    return SearchResult(
        score=1.0,
        modality="text",
        relative_path=path,
        page_no=1,
        snippet="sanitized",
        unit_type=unit_type,
        payload={"table_no": 0} if unit_type == "pdf_table" else {},
    )


def test_classify_embedding_coverage_when_target_lexically_strong():
    row = audit._classify_deep_miss(
        target_rank=0,
        target_payload_count=1,
        target_preview_term_count=12,
        target_payload_overlap=0.75,
        target_filename_overlap=0.25,
        negative_payload_overlap=0.1,
        negative_filename_overlap=0.1,
        negative_ranks=[],
    )

    assert row["classification"] == "embedding_coverage"
    assert row["primary_reason"] == "target_lexically_strong_but_vector_missed"


def test_classify_query_contract_when_negative_signal_is_stronger():
    row = audit._classify_deep_miss(
        target_rank=0,
        target_payload_count=1,
        target_preview_term_count=12,
        target_payload_overlap=0.2,
        target_filename_overlap=0.1,
        negative_payload_overlap=0.7,
        negative_filename_overlap=0.2,
        negative_ranks=[3],
    )

    assert row["classification"] == "query_contract"
    assert row["primary_reason"] == "negative_lexical_signal_stronger"


def test_audit_query_outputs_sanitized_deep_miss_features():
    item = {
        "query_id": "deep-miss",
        "query": "budget review table metric",
        "negative_paths": ["distractor_notes_01.pdf"],
        "relevant": [
            {
                "relative_path": "table_budget_review_01.pdf",
                "unit_type": "pdf_table",
                "table_no": 0,
            }
        ],
    }
    payloads = [
        {
            "relative_path": "table_budget_review_01.pdf",
            "unit_type": "pdf_table",
            "table_no": 0,
            "text_preview": "budget review table metric evidence",
        },
        {
            "relative_path": "distractor_notes_01.pdf",
            "unit_type": "document",
            "text_preview": "planning note",
        },
    ]

    row = audit._audit_query(
        item,
        payloads=payloads,
        searcher=lambda query, top_k: [_result("distractor_notes_01.pdf", "document")],
        deep_top_k=50,
    )

    assert row["query_id"] == "deep-miss"
    assert row["target_rank_deep_k"] == 0
    assert row["target_payload_count"] == 1
    assert row["target_preview_overlap_ratio"] > 0
    assert row["classification"] == "embedding_coverage"
    assert "query" not in row
    assert "body" not in row
    assert "text" not in row


def test_summary_counts_are_quantitative():
    rows = [
        {
            "classification": "embedding_coverage",
            "primary_reason": "target_lexically_strong_but_vector_missed",
            "recommended_repair_track": "embedding_profile_or_query_embedding_audit",
            "negative_seen_deep_k": False,
        },
        {
            "classification": "query_contract",
            "primary_reason": "negative_lexical_signal_stronger",
            "recommended_repair_track": "query_contract_or_distractor_contract_review",
            "negative_seen_deep_k": True,
        },
    ]

    summary = audit._summarize_deep_misses(rows, evaluated_queries=8)
    aggregate = audit._aggregate_modes({"table": {"summary": summary}})

    assert summary["deep_miss_count"] == 2
    assert summary["deep_miss_rate"] == 0.25
    assert aggregate["classification_counts"] == {
        "embedding_coverage": 1,
        "query_contract": 1,
    }
    assert aggregate["product_repair_approved"] is False


def test_main_rejects_raw_report_keys(tmp_path: Path):
    report = {"rows": [{"raw_query": "unsafe"}]}

    findings = audit._raw_report_key_findings(
        report,
        str(tmp_path / "report.json"),
    )

    assert findings
