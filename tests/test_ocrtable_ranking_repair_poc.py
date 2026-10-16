from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_ranking_repair_poc as poc


def _summary(
    *,
    evaluated: int,
    passed: int,
    target_hit: int,
    target_deep: int,
    negative_top1: int = 0,
    negative_before: int = 0,
):
    return {
        "evaluated_queries": evaluated,
        "passed_queries": passed,
        "pass_rate": round(passed / evaluated, 6),
        "target_hit_top_k_count": target_hit,
        "target_hit_top_k_rate": round(target_hit / evaluated, 6),
        "target_hit_deep_k_count": target_deep,
        "target_hit_deep_k_rate": round(target_deep / evaluated, 6),
        "target_within_max_rank_count": passed,
        "negative_top1_count": negative_top1,
        "negative_before_target_count": negative_before,
        "failure_bucket_counts": {"pass": passed},
    }


def test_repair_poc_reports_sanitized_same_fixture_improvement(
    monkeypatch,
    tmp_path: Path,
):
    baseline = _summary(
        evaluated=18,
        passed=3,
        target_hit=3,
        target_deep=11,
        negative_before=5,
    )
    candidate = _summary(
        evaluated=18,
        passed=9,
        target_hit=11,
        target_deep=11,
        negative_before=3,
    )

    monkeypatch.setattr(
        poc,
        "run_ranking_diagnostic",
        lambda **_kwargs: {
            "corpus": {
                "pdf_files": 120,
                "hard_negative_queries": 18,
            },
            "aggregate": {
                "candidate_summaries": {
                    "baseline": baseline,
                    "combined_product_available": candidate,
                },
            },
            "modes": {
                "table": {
                    "summary": {
                        "baseline": baseline,
                        "combined_product_available": candidate,
                    }
                }
            },
        },
    )

    report = poc.run_ranking_repair_poc(pdf_dir=tmp_path)

    assert report["benchmark_only"] is True
    assert report["product_runtime_changed"] is False
    assert report["stable_document_identifier_recorded"] is False
    assert report["improvement"]["pass_rate_delta"] == 0.333333
    assert report["improvement"]["target_hit_top_k_rate_delta"] == 0.444444
    assert report["acceptance"]["same_fixture_metric_improved"] is True
    assert report["acceptance"]["negative_top1_non_regression"] is True
    assert report["decision"] == "benchmark-only-improved-but-product-blocked"
    assert not poc._raw_report_key_findings(report, "repair.json")
    assert "query_id" not in str(report)
    assert "relative_path" not in str(report)
    assert "tesseract.exe" not in str(report)


def test_repair_poc_holds_when_candidate_regresses_negative_top1(
    monkeypatch,
    tmp_path: Path,
):
    baseline = _summary(evaluated=2, passed=1, target_hit=1, target_deep=2)
    candidate = _summary(
        evaluated=2,
        passed=2,
        target_hit=2,
        target_deep=2,
        negative_top1=1,
    )

    monkeypatch.setattr(
        poc,
        "run_ranking_diagnostic",
        lambda **_kwargs: {
            "corpus": {
                "pdf_files": 2,
                "hard_negative_queries": 2,
            },
            "aggregate": {
                "candidate_summaries": {
                    "baseline": baseline,
                    "combined_product_available": candidate,
                },
            },
            "modes": {},
        },
    )

    report = poc.run_ranking_repair_poc(pdf_dir=tmp_path)

    assert report["acceptance"]["negative_top1_non_regression"] is False
    assert report["decision"] == "hold-repair"
