from __future__ import annotations

from pathlib import Path

from benchmarks import ocrtable_extractor_preview_repair_poc as poc


def _profile_result(
    *,
    profile: str,
    baseline: bool,
    extractor_count: int,
    deep_count: int,
    negative_top1: int = 0,
    pass_rate: float = 0.25,
):
    return {
        "profile": profile,
        "profile_ordinal": 6 if profile == "psm6" else 11,
        "baseline": baseline,
        "corpus": {
            "pdf_files": 120,
            "hard_negative_queries": 11,
        },
        "indexed_units": 100,
        "manifest_units": 100,
        "sync": {
            "added": 120,
            "updated": 0,
            "deleted": 0,
            "skipped": 0,
            "failed": 0,
            "ocr_attempted": 120,
            "ocr_succeeded": 120,
            "ocr_empty": 0,
            "cache_result_hits": 0,
            "cache_result_misses": 0,
            "cache_entries_written": 0,
        },
        "index_latency_ms": 10.0,
        "ranking": {
            "evaluated_queries": 11,
            "passed_queries": 3,
            "pass_rate": pass_rate,
            "target_unit_indexed_count": 11,
            "target_hit_top_k_count": 3,
            "target_hit_deep_k_count": 7,
            "negative_top1_count": negative_top1,
            "negative_before_target_count": 0,
            "failure_bucket_counts": {"target_not_in_deep_top_k": deep_count},
        },
        "deep_miss": {
            "deep_miss_count": deep_count,
            "deep_miss_rate": round(deep_count / 11, 6),
            "extractor_contract_count": extractor_count,
            "non_extractor_deep_miss_count": deep_count - extractor_count,
            "cause_family_counts": {"extractor_contract": extractor_count},
            "primary_reason_counts": {"target_preview_sparse": extractor_count},
        },
    }


def test_extractor_preview_poc_selects_profile_that_reduces_extractor_blocker(
    monkeypatch,
    tmp_path: Path,
):
    def fake_run(**kwargs):
        if kwargs["baseline"]:
            return _profile_result(
                profile="psm6",
                baseline=True,
                extractor_count=1,
                deep_count=4,
                pass_rate=0.25,
            )
        return _profile_result(
            profile="psm11",
            baseline=False,
            extractor_count=0,
            deep_count=3,
            pass_rate=0.35,
        )

    monkeypatch.setattr(poc, "_run_profile_candidate", fake_run)

    report = poc.run_extractor_preview_repair_poc(
        pdf_dir=tmp_path,
        profiles=("11",),
    )

    assert report["schema_version"] == "ocrtable-extractor-preview-repair-poc-v1"
    assert report["benchmark_only"] is True
    assert report["product_runtime_changed"] is False
    assert report["selected_profile"]["profile"] == "psm11"
    assert (
        report["selected_profile"]["improvement_vs_baseline"][
            "extractor_contract_reduction"
        ]
        == 1
    )
    assert report["acceptance"]["extractor_blocker_decreases"] is True
    assert report["acceptance"]["negative_top1_remains_zero"] is True
    assert (
        report["decision"]
        == "benchmark-only-extractor-repair-improved-product-still-blocked"
    )
    assert not poc._raw_report_key_findings(report, "extractor-poc.json")
    serialized = str(report)
    assert "query_id" not in serialized
    assert "relative_path" not in serialized
    assert "target_document" not in serialized
    assert "tesseract.exe" not in serialized


def test_extractor_preview_poc_holds_when_negative_top1_regresses(
    monkeypatch,
    tmp_path: Path,
):
    def fake_run(**kwargs):
        if kwargs["baseline"]:
            return _profile_result(
                profile="psm6",
                baseline=True,
                extractor_count=1,
                deep_count=4,
            )
        return _profile_result(
            profile="psm11",
            baseline=False,
            extractor_count=0,
            deep_count=3,
            negative_top1=1,
        )

    monkeypatch.setattr(poc, "_run_profile_candidate", fake_run)

    report = poc.run_extractor_preview_repair_poc(
        pdf_dir=tmp_path,
        profiles=("11",),
    )

    assert report["selected_profile"]["profile"] == "psm6"
    assert report["acceptance"]["extractor_blocker_decreases"] is False
    assert report["acceptance"]["negative_top1_remains_zero"] is True
    assert report["decision"] == "hold-extractor-preview-repair-poc"
