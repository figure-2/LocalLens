from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from benchmarks import ocrtable_sparse_target_repair_spec as spec


def _item():
    return {
        "query": "receipt total approved amount 184 dollars",
        "relevant": [
            {
                "relative_path": "ocr_receipt_total_01.pdf",
                "unit_type": "pdf_ocr_text",
                "image_no": 0,
            }
        ],
    }


def test_root_cause_prefers_extractor_profile_when_alternate_passes(monkeypatch):
    def fake_units(*, tesseract_psm: str, **_kwargs):
        if tesseract_psm == "11":
            preview = "receipt total approved amount 184 dollars"
        else:
            preview = "receipt total approved"
        return [
            SimpleNamespace(
                unit_type="pdf_ocr_text",
                image_no=0,
                text="receipt total approved amount 184 dollars",
                text_preview=preview,
            )
        ]

    monkeypatch.setattr(spec, "_ocr_units_for_single_target", fake_units)
    monkeypatch.setattr(
        spec,
        "_fixture_intent_terms",
        lambda _path: {"receipt", "total", "approved", "amount", "184", "dollars"},
    )

    row = spec._repair_case_report(
        1,
        _item(),
        pdf_dir=Path("."),
        min_preview_terms=4,
        min_query_overlap=4,
        tesseract_cmd="tesseract",
        ocr_lang="eng",
        psm_profiles=("", "11"),
    )

    assert row["root_cause_decision"] == "extractor_profile_repair_candidate"
    assert row["best_profile_summary"]["profile_ordinal"] == 11
    assert row["best_profile_summary"]["passes_full_unit_contract"] is True
    assert row["best_profile_summary"]["passes_preview_contract"] is True


def test_root_cause_keeps_fixture_contract_when_intent_is_too_sparse(monkeypatch):
    monkeypatch.setattr(
        spec,
        "_ocr_units_for_single_target",
        lambda **_kwargs: [
            SimpleNamespace(
                unit_type="pdf_ocr_text",
                image_no=0,
                text="receipt total",
                text_preview="receipt total",
            )
        ],
    )
    monkeypatch.setattr(spec, "_fixture_intent_terms", lambda _path: {"receipt", "total"})

    row = spec._repair_case_report(
        1,
        _item(),
        pdf_dir=Path("."),
        min_preview_terms=4,
        min_query_overlap=4,
        tesseract_cmd="tesseract",
        ocr_lang="eng",
        psm_profiles=("",),
    )

    assert row["root_cause_decision"] == "fixture_query_contract_insufficient"
    assert row["fixture_intent_contract_sufficient"] is False
    assert (
        row["recommended_action"]
        == "repair_fixture_or_query_contract_before_004e2"
    )


def test_root_cause_separates_missing_intent_catalog_from_extractor_profile(monkeypatch):
    monkeypatch.setattr(
        spec,
        "_ocr_units_for_single_target",
        lambda **_kwargs: [
            SimpleNamespace(
                unit_type="pdf_ocr_text",
                image_no=0,
                text="receipt total approved amount 184 dollars",
                text_preview="receipt total approved amount 184 dollars",
            )
        ],
    )
    monkeypatch.setattr(spec, "_fixture_intent_terms", lambda _path: set())

    row = spec._repair_case_report(
        1,
        _item(),
        pdf_dir=Path("."),
        min_preview_terms=4,
        min_query_overlap=4,
        tesseract_cmd="tesseract",
        ocr_lang="eng",
        psm_profiles=("",),
    )

    assert (
        row["root_cause_decision"]
        == "fixture_intent_catalog_missing_with_extractor_profile_candidate"
    )
    assert row["fixture_intent_status"] == "intent_catalog_missing"
    assert row["best_profile_summary"]["passes_preview_contract"] is True
    assert (
        row["recommended_action"]
        == "repair_fixture_intent_catalog_then_measure_profile_candidate"
    )


def test_root_cause_detects_preview_loss_when_full_unit_passes(monkeypatch):
    monkeypatch.setattr(
        spec,
        "_ocr_units_for_single_target",
        lambda **_kwargs: [
            SimpleNamespace(
                unit_type="pdf_ocr_text",
                image_no=0,
                text="receipt total approved amount 184 dollars",
                text_preview="receipt total approved",
            )
        ],
    )
    monkeypatch.setattr(
        spec,
        "_fixture_intent_terms",
        lambda _path: {"receipt", "total", "approved", "amount", "184", "dollars"},
    )

    row = spec._repair_case_report(
        1,
        _item(),
        pdf_dir=Path("."),
        min_preview_terms=4,
        min_query_overlap=4,
        tesseract_cmd="tesseract",
        ocr_lang="eng",
        psm_profiles=("",),
    )

    assert row["root_cause_decision"] == "extractor_preview_repair_required"
    assert row["best_profile_summary"]["unit_query_overlap_count"] == 6
    assert row["best_profile_summary"]["preview_query_overlap_count"] == 3
    assert row["best_profile_summary"]["preview_loss_query_term_count"] == 3


def test_aggregate_blocks_004e2_until_sparse_case_is_repaired():
    aggregate = spec._aggregate_repair_spec(
        [
            {
                "root_cause_decision": "extractor_output_sparse",
                "recommended_action": "repair_extractor_preview_or_fixture_surface_before_004e2",
            }
        ]
    )

    assert aggregate["evaluated_sparse_target_queries"] == 1
    assert aggregate["ll_corpus_004e2_approval_allowed"] is False
    assert aggregate["product_runtime_changed"] is False


def test_run_spec_uses_ocr_mode_local_ordinals(monkeypatch, tmp_path: Path):
    queries = [
        {"scenario": "hard-negative", "relevant": [{"unit_type": "pdf_table"}]},
        {
            "scenario": "hard-negative",
            "query": "first ocr query",
            "relevant": [{"unit_type": "pdf_ocr_text", "relative_path": "first.pdf"}],
        },
        {
            "scenario": "hard-negative",
            "query": "second ocr query",
            "relevant": [{"unit_type": "pdf_ocr_text", "relative_path": "second.pdf"}],
        },
    ]
    selected = []
    monkeypatch.setattr(spec, "_cache_safety_queries", lambda _path: queries)
    monkeypatch.setattr(
        spec,
        "run_sparse_target_contract_audit",
        lambda **_kwargs: {
            "modes": {
                "ocr": {
                    "sparse_target_queries": [
                        {"case_ordinal": 2},
                    ]
                }
            }
        },
    )

    def fake_report(ordinal, item, **_kwargs):
        selected.append((ordinal, item["query"]))
        return {
            "root_cause_decision": "extractor_output_sparse",
            "recommended_action": "repair_extractor_preview_or_fixture_surface_before_004e2",
        }

    monkeypatch.setattr(spec, "_repair_case_report", fake_report)

    report = spec.run_sparse_target_repair_spec(pdf_dir=tmp_path)

    assert selected == [(2, "second ocr query")]
    assert report["corpus"]["hard_negative_queries"] == 3
    assert report["corpus"]["sparse_target_queries"] == 1


def test_repair_spec_report_key_guard_rejects_stable_identifiers(tmp_path: Path):
    report = {
        "case_reports": [
            {
                "target_document": "unsafe.pdf",
                "query_id": "unsafe",
            }
        ]
    }

    findings = spec._sparse_report_key_findings(
        report,
        str(tmp_path / "repair-spec.json"),
    )

    assert findings


def test_work_order_is_plain_and_actionable():
    work_order = spec._work_order(
        [
            {
                "root_cause_decision": "extractor_profile_repair_candidate",
                "recommended_action": "measure_same_fixture_with_candidate_profile_before_runtime_change",
            }
        ]
    )

    assert work_order[0]["id"] == "LL-CORPUS-004E4-REPAIR-POC-APPROVAL"
    assert "acceptance_tests" in work_order[0]
    assert work_order[-1]["rollback_plan"] == "keep benchmark-only evidence"
