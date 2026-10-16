from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_sparse_target_contract_audit as audit
from locallens.core.types import SearchResult


def _result(path: str, unit_type: str = "pdf_ocr_text"):
    return SearchResult(
        score=1.0,
        modality="text",
        relative_path=path,
        page_no=1,
        snippet="sanitized",
        unit_type=unit_type,
        payload={"image_no": 0} if unit_type == "pdf_ocr_text" else {},
    )


def test_sparse_query_report_is_ordinal_only_and_sanitized():
    item = {
        "query_id": "sparse-target-case",
        "query": "receipt total approved amount record",
        "negative_paths": ["distractor_notes_02.pdf"],
        "relevant": [
            {
                "relative_path": "ocr_receipt_total_01.pdf",
                "unit_type": "pdf_ocr_text",
                "image_no": 0,
                "max_rank": 5,
            }
        ],
    }
    payloads = [
        {
            "relative_path": "ocr_receipt_total_01.pdf",
            "unit_type": "pdf_ocr_text",
            "image_no": 0,
            "text_preview": "receipt",
        },
        {
            "relative_path": "distractor_notes_02.pdf",
            "unit_type": "document",
            "text_preview": "summary memo amount approved",
        },
    ]

    row = audit._audit_sparse_query(
        1,
        item,
        payloads=payloads,
        searcher=lambda query, top_k: [_result("distractor_notes_02.pdf", "document")],
        deep_top_k=50,
        min_preview_terms=4,
    )

    assert row["case_ordinal"] == 1
    assert row["included_in_sparse_target_contract_audit"] is True
    assert row["deep_miss_primary_reason"] == audit.SPARSE_REASON
    assert row["target_preview_term_count"] == 1
    assert row["target_preview_missing_query_term_count"] == 4
    assert row["contract_decision"] == "target_preview_partial_but_below_contract"
    assert "query_id" not in row
    assert "target_document" not in row
    assert "relative_path" not in row
    assert "negative_paths" not in row
    assert "query" not in row
    assert "text" not in row


def test_non_sparse_embedding_coverage_row_is_excluded():
    item = {
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
            "text_preview": "budget review table metric evidence owner variance",
        }
    ]

    row = audit._audit_sparse_query(
        2,
        item,
        payloads=payloads,
        searcher=lambda query, top_k: [_result("distractor_notes_01.pdf", "document")],
        deep_top_k=50,
        min_preview_terms=4,
    )

    assert row["included_in_sparse_target_contract_audit"] is False
    assert row["deep_miss_classification"] == "embedding_coverage"


def test_contract_decision_prefers_fixture_or_extractor_hold_for_zero_overlap():
    decision = audit._contract_decision(
        target_payload_count=1,
        target_preview_term_count=1,
        target_preview_overlap_ratio=0.0,
        target_filename_overlap_ratio=0.0,
        negative_preview_overlap_ratio=0.25,
        negative_filename_overlap_ratio=0.0,
        min_preview_terms=4,
    )

    assert decision == "fixture_or_extractor_target_preview_too_sparse"
    assert (
        audit._recommended_repair_track(decision)
        == "fixture_or_extractor_contract_repair_before_product_change"
    )


def test_summary_and_aggregate_keep_004e2_blocked_when_sparse_case_remains():
    rows = [
        {
            "contract_decision": "target_preview_partial_but_below_contract",
            "recommended_repair_track": "fixture_or_extractor_contract_repair_before_product_change",
            "preview_density_bucket": "very_sparse",
            "preview_query_match_bucket": "low",
            "target_preview_missing_query_term_count": 4,
            "target_preview_term_count": 1,
            "target_preview_overlap_ratio": 0.2,
            "negative_preview_overlap_ratio": 0.6,
        }
    ]

    summary = audit._summarize_sparse_queries(rows, evaluated_queries=10)
    aggregate = audit._aggregate_modes({"ocr": {"summary": summary}})

    assert summary["sparse_target_queries"] == 1
    assert summary["sparse_target_rate"] == 0.1
    assert aggregate["sparse_target_queries"] == 1
    assert aggregate["ll_corpus_004e2_approval_allowed"] is False
    assert aggregate["public_quality_claim_allowed"] is False


def test_sparse_report_key_guard_rejects_stable_identifiers(tmp_path: Path):
    report = {
        "rows": [
            {
                "query_id": "unsafe",
                "target_document": "unsafe.pdf",
                "source": "unsafe",
            }
        ]
    }

    findings = audit._sparse_report_key_findings(
        report,
        str(tmp_path / "report.json"),
    )

    assert len(findings) >= 3


def test_sparse_report_key_guard_allows_sanitized_metrics(tmp_path: Path):
    report = {
        "rows": [
            {
                "case_ordinal": 1,
                "mode": "ocr",
                "query_term_count": 5,
                "target_preview_term_count": 1,
                "target_preview_overlap_ratio": 0.2,
                "contract_decision": "target_preview_partial_but_below_contract",
            }
        ]
    }

    findings = audit._sparse_report_key_findings(
        report,
        str(tmp_path / "report.json"),
    )

    assert findings == []
