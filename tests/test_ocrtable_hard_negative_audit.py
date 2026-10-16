from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_hard_negative_audit as audit
from locallens.core.types import SearchResult


def test_failure_bucket_prefers_indexing_gap_before_ranking_gap():
    assert (
        audit._failure_bucket(
            target_document_exists=True,
            target_unit_count=0,
            target_rank_top_k=0,
            target_rank_deep=0,
            max_rank=5,
            negative_before_target=0,
        )
        == "target_unit_not_indexed"
    )


def test_failure_bucket_splits_negative_before_target_from_deep_miss():
    assert (
        audit._failure_bucket(
            target_document_exists=True,
            target_unit_count=1,
            target_rank_top_k=0,
            target_rank_deep=0,
            max_rank=5,
            negative_before_target=1,
        )
        == "negative_before_target"
    )
    assert (
        audit._failure_bucket(
            target_document_exists=True,
            target_unit_count=1,
            target_rank_top_k=0,
            target_rank_deep=0,
            max_rank=5,
            negative_before_target=0,
        )
        == "target_not_in_deep_top_k"
    )


def test_audit_query_records_ranks_without_raw_query_fields():
    item = {
        "query_id": "cache-hard-negative-table",
        "query": "do not record this query body",
        "scenario": "hard-negative",
        "top_k": 10,
        "negative_paths": ["distractor_notes_01.pdf"],
        "relevant": [
            {
                "relative_path": "table_budget_review_01.pdf",
                "unit_type": "pdf_table",
                "max_rank": 5,
                "table_no": 0,
            }
        ],
    }
    payloads = [
        {
            "relative_path": "table_budget_review_01.pdf",
            "unit_type": "pdf_table",
            "table_no": 0,
        }
    ]

    def searcher(query: str, top_k: int):
        assert query == "do not record this query body"
        return [
            SearchResult(
                score=1.0,
                modality="text",
                relative_path="distractor_notes_01.pdf",
                page_no=1,
                snippet="sanitized",
                unit_type="document",
                payload={},
            ),
            SearchResult(
                score=0.9,
                modality="text",
                relative_path="table_budget_review_01.pdf",
                page_no=1,
                snippet="sanitized",
                unit_type="pdf_table",
                payload={"table_no": 0},
            ),
        ]

    row = audit._audit_query(
        item,
        payloads=payloads,
        source_docs={"table_budget_review_01.pdf", "distractor_notes_01.pdf"},
        searcher=searcher,
        deep_top_k=50,
    )

    assert row["query_id"] == "cache-hard-negative-table"
    assert row["target_unit_count"] == 1
    assert row["target_rank_top_k"] == 2
    assert row["negative_best_rank_top_k"] == 1
    assert row["negative_before_target_count"] == 1
    assert row["failure_bucket"] == "negative_before_target"
    assert "query" not in row
    assert "body" not in row


def test_mode_summary_and_aggregate_are_quantitative():
    details = [
        {
            "passed": True,
            "failure_bucket": "pass",
            "target_unit_count": 1,
            "target_rank_top_k": 1,
            "target_rank_deep_k": 1,
            "target_max_rank": 5,
            "negative_top1": False,
            "negative_before_target_count": 0,
        },
        {
            "passed": False,
            "failure_bucket": "target_not_in_deep_top_k",
            "target_unit_count": 1,
            "target_rank_top_k": 0,
            "target_rank_deep_k": 0,
            "target_max_rank": 5,
            "negative_top1": False,
            "negative_before_target_count": 0,
        },
    ]

    summary = audit._mode_summary(details)
    aggregate = audit._aggregate_audit({"table": {"summary": summary}})

    assert summary["evaluated_queries"] == 2
    assert summary["pass_rate"] == 0.5
    assert summary["target_unit_indexed_rate"] == 1.0
    assert aggregate["target_hit_deep_k_rate"] == 0.5
    assert aggregate["failure_bucket_counts"] == {
        "pass": 1,
        "target_not_in_deep_top_k": 1,
    }
    assert aggregate["public_quality_claim_allowed"] is False


def test_audit_main_rejects_raw_report_keys(tmp_path: Path):
    report = {
        "queries": [
            {
                "query_id": "safe",
                "raw_query": "unsafe",
            }
        ]
    }

    findings = audit._raw_report_key_findings(report, str(tmp_path / "report.json"))

    assert findings
