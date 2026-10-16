from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_ranking_diagnostic as diagnostic
from locallens.core.types import SearchResult


def _result(path: str, score: float, snippet: str, unit_type: str = "pdf_table"):
    return SearchResult(
        score=score,
        modality="text",
        relative_path=path,
        page_no=1,
        snippet=snippet,
        unit_type=unit_type,
        payload={"table_no": 0} if unit_type == "pdf_table" else {},
    )


def test_contract_features_do_not_emit_raw_query_or_body_fields():
    target = {
        "relative_path": "table_budget_review_01.pdf",
        "unit_type": "pdf_table",
        "table_no": 0,
    }
    results = [
        _result("distractor_notes_01.pdf", 1.0, "budget planning note"),
        _result("table_budget_review_01.pdf", 0.9, "budget table metric"),
    ]

    row = diagnostic._diagnose_query(
        {
            "query_id": "cache-hard-negative-table",
            "query": "budget review table metric",
            "top_k": 10,
            "negative_paths": ["distractor_notes_01.pdf"],
            "relevant": [target],
        },
        mode="table",
        top_k=10,
        deep_top_k=50,
        searcher=lambda query, top_k: results,
    )

    serialized = row.keys() | row["contract_features"].keys()
    assert "query" not in row
    assert "body" not in row
    assert "text" not in serialized
    assert row["query_term_count"] == 4
    assert row["contract_features"]["target_present_in_deep_k"] is True
    assert row["baseline"]["negative_before_target_count"] == 1


def test_filename_overlap_candidate_can_improve_without_target_labels():
    target = {
        "relative_path": "table_budget_review_01.pdf",
        "unit_type": "pdf_table",
        "table_no": 0,
        "max_rank": 1,
    }
    results = [
        _result("distractor_notes_01.pdf", 1.0, "planning note"),
        _result("table_budget_review_01.pdf", 0.95, "metric"),
    ]

    baseline = diagnostic._evaluate_candidate(
        results,
        target=target,
        negative_paths=["distractor_notes_01.pdf"],
        top_k=10,
        max_rank=1,
    )
    reranked = diagnostic._rerank_candidate(
        "filename_overlap",
        "budget review table",
        results,
    )
    repaired = diagnostic._evaluate_candidate(
        reranked,
        target=target,
        negative_paths=["distractor_notes_01.pdf"],
        top_k=10,
        max_rank=1,
    )

    assert baseline["passed"] is False
    assert repaired["target_rank_top_k"] == 1
    assert repaired["negative_top1"] is False


def test_aggregate_recommends_benchmark_only_when_candidate_improves():
    mode = {
        "summary": {
            "baseline": {
                "evaluated_queries": 2,
                "passed_queries": 0,
                "pass_rate": 0.0,
                "target_hit_top_k_count": 1,
                "target_hit_top_k_rate": 0.5,
                "target_hit_deep_k_count": 2,
                "target_hit_deep_k_rate": 1.0,
                "target_within_max_rank_count": 0,
                "negative_top1_count": 0,
                "negative_before_target_count": 1,
                "failure_bucket_counts": {"negative_before_target": 1},
            },
            "unit_intent": {
                "evaluated_queries": 2,
                "passed_queries": 1,
                "pass_rate": 0.5,
                "target_hit_top_k_count": 2,
                "target_hit_top_k_rate": 1.0,
                "target_hit_deep_k_count": 2,
                "target_hit_deep_k_rate": 1.0,
                "target_within_max_rank_count": 1,
                "negative_top1_count": 0,
                "negative_before_target_count": 0,
                "failure_bucket_counts": {"pass": 1},
            },
            "filename_overlap": {
                "evaluated_queries": 2,
                "passed_queries": 0,
                "pass_rate": 0.0,
                "target_hit_top_k_count": 1,
                "target_hit_top_k_rate": 0.5,
                "target_hit_deep_k_count": 2,
                "target_hit_deep_k_rate": 1.0,
                "target_within_max_rank_count": 0,
                "negative_top1_count": 0,
                "negative_before_target_count": 1,
                "failure_bucket_counts": {"negative_before_target": 1},
            },
            "snippet_overlap": {
                "evaluated_queries": 2,
                "passed_queries": 0,
                "pass_rate": 0.0,
                "target_hit_top_k_count": 1,
                "target_hit_top_k_rate": 0.5,
                "target_hit_deep_k_count": 2,
                "target_hit_deep_k_rate": 1.0,
                "target_within_max_rank_count": 0,
                "negative_top1_count": 0,
                "negative_before_target_count": 1,
                "failure_bucket_counts": {"negative_before_target": 1},
            },
            "combined_product_available": {
                "evaluated_queries": 2,
                "passed_queries": 0,
                "pass_rate": 0.0,
                "target_hit_top_k_count": 1,
                "target_hit_top_k_rate": 0.5,
                "target_hit_deep_k_count": 2,
                "target_hit_deep_k_rate": 1.0,
                "target_within_max_rank_count": 0,
                "negative_top1_count": 0,
                "negative_before_target_count": 1,
                "failure_bucket_counts": {"negative_before_target": 1},
            },
        }
    }

    aggregate = diagnostic._aggregate_modes({"table": mode})

    assert aggregate["best_candidate"] == "unit_intent"
    assert aggregate["target_hit_top_k_delta"] == 0.5
    assert aggregate["negative_top1_regressed"] is False
    assert "benchmark-only" in aggregate["recommended_next"]


def test_main_rejects_raw_report_keys(tmp_path: Path):
    report = {"rows": [{"raw_query": "unsafe"}]}

    findings = diagnostic._raw_report_key_findings(
        report,
        str(tmp_path / "report.json"),
    )

    assert findings
