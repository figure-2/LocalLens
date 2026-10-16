from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from benchmarks import ocrtable_extractor_readthrough_live_eval as readthrough_eval
from benchmarks import ocrtable_cache_safety_live_eval as safety_eval
from benchmarks.ocrtable_cache_safety_live_eval import _default_blocked_terms_file
from benchmarks.ocrtable_cache_safety_live_eval import _aggregate_decision
from benchmarks.ocrtable_cache_safety_live_eval import _cache_safety_binding
from benchmarks.ocrtable_cache_safety_live_eval import _case_docs_for_mode
from benchmarks.ocrtable_cache_safety_live_eval import _corpus_cache_aggregate
from benchmarks.ocrtable_cache_safety_live_eval import _hard_negative_ranking_checks
from benchmarks.ocrtable_cache_safety_live_eval import _mode_acceptance
from benchmarks.ocrtable_cache_safety_live_eval import _PreparedCase
from benchmarks.ocrtable_cache_safety_live_eval import _raw_report_key_findings
from locallens.core.types import SearchResult


def test_mode_acceptance_requires_search_invariance_and_fallbacks():
    cases = {
        "cache_blob_removed": {
            "search_results_unchanged": True,
            "search_result_cache_payload_fields": 0,
        },
        "index_manifest_removed": {"cache_recovery_blocked": True},
        "stale_content": {
            "stale_hit_count": 0,
            "quality_non_regression": True,
        },
        "corrupt_blob": {
            "cache_result_hits": 0,
            "cache_corrupt_skipped": 1,
            "quality_non_regression": True,
        },
    }

    acceptance = _mode_acceptance(cases)

    assert all(acceptance.values())


def test_mode_acceptance_rejects_cache_recovery_from_removed_index():
    cases = {
        "cache_blob_removed": {
            "search_results_unchanged": True,
            "search_result_cache_payload_fields": 0,
        },
        "index_manifest_removed": {"cache_recovery_blocked": False},
        "stale_content": {
            "stale_hit_count": 0,
            "quality_non_regression": True,
        },
        "corrupt_blob": {
            "cache_result_hits": 0,
            "cache_corrupt_skipped": 1,
            "quality_non_regression": True,
        },
    }

    acceptance = _mode_acceptance(cases)

    assert acceptance["cache_cannot_recover_removed_index"] is False


def test_aggregate_keeps_public_cache_claim_on_hold():
    mode = {
        "acceptance": {
            "cache_blob_removal_search_invariant": True,
            "search_payload_cache_fields_zero": True,
            "cache_cannot_recover_removed_index": True,
            "stale_hit_zero": True,
            "corrupt_fallback_counted": True,
            "quality_non_regression": True,
        }
    }

    aggregate = _aggregate_decision({"table": mode, "ocr": mode})

    assert aggregate["safety_live_eval_passed"] is True
    assert aggregate["query_binding_passed"] is True
    assert aggregate["public_cache_claim_allowed"] is False
    assert aggregate["public_evidence_decision"] == "hold"


def test_cache_safety_binding_consumes_golden_scenarios():
    root = Path(__file__).resolve().parents[1]

    binding = _cache_safety_binding(
        root / "benchmarks" / "fixtures" / "pdf_corpus",
        root / "benchmarks" / "fixtures" / "golden_pdf_cache_safety_queries.json",
    )

    assert binding["enabled"] is True
    assert binding["queries_loaded"] == 30
    assert binding["scenario_counts"] == {
        "corrupt-blob": 2,
        "hard-negative": 18,
        "manifest-removed": 3,
        "search-source-negative": 3,
        "stale-content": 2,
        "warm-reuse": 2,
    }
    assert binding["hard_negative_queries"] == 18
    assert binding["negative_paths"] == 18
    assert all(binding["acceptance"].values())
    assert set(_case_docs_for_mode(binding, "table")) == {
        "cache_blob_removed",
        "index_manifest_removed",
        "stale_content",
        "corrupt_blob",
    }
    assert set(_case_docs_for_mode(binding, "ocr")) == {
        "cache_blob_removed",
        "index_manifest_removed",
        "stale_content",
        "corrupt_blob",
    }


def test_run_cache_safety_uses_bound_case_documents(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    calls = []

    def fake_run_mode(**kwargs):
        calls.append(kwargs)
        return {
            "mode": kwargs["mode"],
            "acceptance": {
                "cache_blob_removal_search_invariant": True,
                "search_payload_cache_fields_zero": True,
                "cache_cannot_recover_removed_index": True,
                "stale_hit_zero": True,
                "corrupt_fallback_counted": True,
                "quality_non_regression": True,
            },
        }

    monkeypatch.setattr(safety_eval, "_run_mode", fake_run_mode)

    report = safety_eval.run_cache_safety_live_eval(
        pdf_dir=root / "benchmarks" / "fixtures" / "pdf_corpus",
        cache_safety_golden=root
        / "benchmarks"
        / "fixtures"
        / "golden_pdf_cache_safety_queries.json",
    )

    assert report["query_binding"]["enabled"] is True
    assert report["aggregate"]["query_binding_passed"] is True
    assert report["aggregate"]["safety_live_eval_passed"] is True
    assert [call["mode"] for call in calls] == ["table", "ocr"]
    assert calls[0]["case_docs"]["stale_content"] == "table_rollout_plan_02.pdf"
    assert calls[0]["case_docs"]["corrupt_blob"] == "table_latency_check_10.pdf"
    assert calls[1]["case_docs"]["stale_content"] == "ocr_noisy_receipt_06.pdf"
    assert calls[1]["case_docs"]["corrupt_blob"] == "ocr_rotated_notice_07.pdf"


def test_run_cache_safety_attaches_release_scale_corpus_eval(monkeypatch):
    root = Path(__file__).resolve().parents[1]

    def fake_run_mode(**kwargs):
        return {
            "mode": kwargs["mode"],
            "acceptance": {
                "cache_blob_removal_search_invariant": True,
                "search_payload_cache_fields_zero": True,
                "cache_cannot_recover_removed_index": True,
                "stale_hit_zero": True,
                "corrupt_fallback_counted": True,
                "quality_non_regression": True,
            },
        }

    def fake_corpus_cache_eval(**kwargs):
        return {
            "enabled": True,
            "source_pdf_files": 120,
            "warm_repeats": kwargs["warm_repeats"],
            "aggregate": {
                "cache_live_eval_passed": True,
                "hard_negative_ranking_checked": True,
                "hard_negative_ranking_passed": False,
            },
        }

    monkeypatch.setattr(safety_eval, "_run_mode", fake_run_mode)
    monkeypatch.setattr(safety_eval, "_run_corpus_cache_eval", fake_corpus_cache_eval)

    report = safety_eval.run_cache_safety_live_eval(
        pdf_dir=root / "benchmarks" / "fixtures" / "pdf_corpus",
        cache_safety_golden=root
        / "benchmarks"
        / "fixtures"
        / "golden_pdf_cache_safety_queries.json",
        run_corpus_cache_eval=True,
        warm_repeats=2,
    )

    assert report["corpus_cache_eval"]["enabled"] is True
    assert report["corpus_cache_eval"]["source_pdf_files"] == 120
    assert report["aggregate"]["release_scale_cache_eval_passed"] is True
    assert report["aggregate"]["hard_negative_ranking_checked"] is True
    assert report["aggregate"]["hard_negative_ranking_passed"] is False


def test_hard_negative_ranking_checks_record_rank_without_query_content():
    queries = [
        {
            "query_id": "hard-negative-table",
            "query": "table budget owner",
            "scenario": "hard-negative",
            "top_k": 5,
            "negative_paths": ["distractor_notes_01.pdf"],
            "relevant": [
                {
                    "relative_path": "table_budget_review_01.pdf",
                    "unit_type": "pdf_table",
                    "max_rank": 3,
                    "table_no": 0,
                }
            ],
        }
    ]

    def searcher(query: str, top_k: int):
        assert query == "table budget owner"
        assert top_k == 5
        return [
            SearchResult(
                score=0.99,
                modality="text",
                relative_path="table_budget_review_01.pdf",
                page_no=1,
                snippet="sanitized",
                unit_type="pdf_table",
                payload={"table_no": 0},
            ),
            SearchResult(
                score=0.88,
                modality="text",
                relative_path="distractor_notes_01.pdf",
                page_no=1,
                snippet="sanitized",
                unit_type="document",
                payload={},
            ),
        ]

    report = _hard_negative_ranking_checks(
        queries=queries,
        mode="table",
        searcher=searcher,
    )

    assert report["evaluated_queries"] == 1
    assert report["target_hit_count"] == 1
    assert report["target_hit_rate"] == 1.0
    assert report["negative_within_top_k_count"] == 1
    assert report["negative_top1_count"] == 0
    assert report["negative_before_target_count"] == 0
    assert report["passed"] is True
    assert report["details"] == [
        {
            "query_id": "hard-negative-table",
            "target_rank": 1,
            "target_max_rank": 3,
            "negative_best_rank": 2,
            "negative_before_target_count": 0,
            "negative_top1": False,
            "passed": True,
        }
    ]
    assert not _raw_report_key_findings(report, "ranking.json")


def test_corpus_cache_aggregate_tracks_cache_and_ranking_separately():
    mode = {
        "actual_extractor_used": True,
        "failures_zero": True,
        "quality_non_regression": True,
        "cache_effect": {"warm_hit_rate_is_1": True},
        "hard_negative_ranking": {
            "evaluated_queries": 3,
            "passed": False,
        },
    }

    aggregate = _corpus_cache_aggregate({"table": mode, "ocr": mode})

    assert aggregate["cache_live_eval_passed"] is True
    assert aggregate["hard_negative_ranking_checked"] is True
    assert aggregate["hard_negative_ranking_passed"] is False
    assert aggregate["release_scale_eval_passed"] is True
    assert aggregate["public_performance_claim_allowed"] is False


def test_top_level_aggregate_holds_public_claim_when_release_scale_ranking_fails():
    mode = {
        "acceptance": {
            "cache_blob_removal_search_invariant": True,
            "search_payload_cache_fields_zero": True,
            "cache_cannot_recover_removed_index": True,
            "stale_hit_zero": True,
            "corrupt_fallback_counted": True,
            "quality_non_regression": True,
        }
    }
    corpus = {
        "enabled": True,
        "source_pdf_files": 120,
        "aggregate": {
            "cache_live_eval_passed": True,
            "hard_negative_ranking_checked": True,
            "hard_negative_ranking_passed": False,
        },
    }

    aggregate = _aggregate_decision({"table": mode, "ocr": mode}, None, corpus)

    assert aggregate["release_scale_cache_eval_passed"] is True
    assert aggregate["hard_negative_ranking_passed"] is False
    assert aggregate["public_cache_claim_allowed"] is False
    assert aggregate["hold_reasons"] == ["hard-negative ranking checks failed"]


def test_aggregate_rejects_unbound_cache_safety_queries():
    mode = {
        "acceptance": {
            "cache_blob_removal_search_invariant": True,
            "search_payload_cache_fields_zero": True,
            "cache_cannot_recover_removed_index": True,
            "stale_hit_zero": True,
            "corrupt_fallback_counted": True,
            "quality_non_regression": True,
        }
    }
    binding = {
        "enabled": True,
        "acceptance": {
            "query_set_bound": True,
            "targets_exist": True,
            "negative_paths_exist": False,
            "lifecycle_cases_bound": True,
            "invalid_query_count_zero": True,
            "hard_negative_paths_present": True,
        },
    }

    aggregate = _aggregate_decision({"table": mode, "ocr": mode}, binding)

    assert aggregate["query_binding_passed"] is False
    assert aggregate["safety_live_eval_passed"] is False


def test_live_eval_defaults_to_publication_terms_file_when_present(
    tmp_path: Path,
    monkeypatch,
):
    terms_dir = tmp_path / ".locallens"
    terms_dir.mkdir()
    (terms_dir / "publication-terms.txt").write_text(
        "blocked marker\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert _default_blocked_terms_file() == ".locallens/publication-terms.txt"
    assert (
        readthrough_eval._default_blocked_terms_file()
        == ".locallens/publication-terms.txt"
    )


def test_live_eval_report_rejects_raw_payload_fields():
    report = {
        "modes": {
            "ocr": {
                "cases": {
                    "unsafe": {
                        "text_preview": "raw extracted text",
                        "blob_rel_path": "cache/blob.json",
                        "raw_candidate": "raw value",
                        "ocr_text": "visible OCR text",
                    }
                }
            }
        }
    }

    findings = _raw_report_key_findings(report, "report.json")

    assert {finding.rule_id for finding in findings} == {
        "raw-report-field-text_preview",
        "raw-report-field-blob_rel_path",
        "raw-report-field-raw_candidate",
        "raw-report-field-ocr_text",
    }


def test_prepared_case_cleans_store_when_optional_units_missing(
    monkeypatch,
    tmp_path: Path,
):
    source_pdf = tmp_path / "fixture.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    closed = []

    class FakeStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def payload_records(self):
            return []

        def close(self):
            closed.append(True)

    class FakeManifest:
        def __init__(self, path):
            self.path = path

    class FakeSync:
        def __init__(self, *_args, **_kwargs):
            pass

        def sync_folder(self, _source):
            return SimpleNamespace(cache_entries_written=1)

    monkeypatch.setattr(safety_eval, "QdrantStore", FakeStore)
    monkeypatch.setattr(safety_eval, "ManifestStore", FakeManifest)
    monkeypatch.setattr(safety_eval, "SyncService", FakeSync)

    try:
        _PreparedCase(
            source_pdf,
            "fixture.pdf",
            "ocr",
            "tesseract",
            "eng",
            "6",
        )
    except RuntimeError as exc:
        assert "no optional units" in str(exc)
    else:
        raise AssertionError("expected missing optional units to fail")

    assert closed == [True]
