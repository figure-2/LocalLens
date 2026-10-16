from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from benchmarks.ocrtable_guard_binding import paddleocr_model_cache_fingerprint
import benchmarks.scanned_table_structure_poc as poc

from benchmarks.scanned_table_structure_poc import (
    _locality_report,
    _paddleocr_model_dir,
    _paddleocr_result_to_words,
    _stage_latency_summary,
    _rotate_image,
    _structure_candidate_score,
    _term_miss_summary,
    _assign_words_to_grid,
    _group_detected_words_into_rows,
    cell_structure_metrics,
    expected_table_rows,
    filter_table_candidate_rows,
    group_words_into_rows,
    parse_tesseract_tsv,
    run_tesseract_tsv_poc,
    run_paddleocr_structure_poc,
    run_adaptive_projection_pairing_poc,
    run_tesseract_multipass_poc,
    row_structure_metrics,
    structure_claim_class_gate,
    structure_promotion_gate,
    term_recall,
    term_recall_audit,
)


def test_tesseract_tsv_rows_are_grouped_in_reading_order():
    tsv = "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t50\t10\t30\t12\t96\tregion",
            "5\t1\t1\t1\t1\t2\t120\t10\t30\t12\t92\towner",
            "5\t1\t1\t1\t2\t1\t50\t40\t30\t12\t91\tnorth",
            "5\t1\t1\t1\t2\t2\t120\t40\t30\t12\t89\tkim",
        ]
    )

    words = parse_tesseract_tsv(tsv, min_conf=25)
    rows = group_words_into_rows(words)

    assert rows == [["region", "owner"], ["north", "kim"]]


def test_tesseract_tsv_parser_filters_low_confidence_words():
    tsv = "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t50\t10\t30\t12\t96\tvisible",
            "5\t1\t1\t1\t1\t2\t120\t10\t30\t12\t9\tnoise",
        ]
    )

    words = parse_tesseract_tsv(tsv, min_conf=25)

    assert [word.text for word in words] == ["visible"]


def test_term_recall_uses_structured_rows():
    rows = [["north", "sales", "table"], ["region", "owner", "total"]]

    assert term_recall("north sales table total missing", rows) == 0.8


def test_term_recall_audit_splits_context_and_structured_cell_terms():
    query = "support queue table ticket priority agent alpha high mina beta low joon"
    context_rows = [
        ["support queue table"],
        ["ticket", "priority", "agent"],
        ["alpha", "high", "mina"],
        ["beta", "low", "joon"],
    ]
    structured_rows = [
        ["ticket", "priority", "agent"],
        ["alpha", "high", "mina"],
        ["beta", "low", "joon"],
    ]

    audit = term_recall_audit(
        query,
        context_rows,
        structured_rows,
        structured_rows,
    )

    assert audit["structured_cell_term_recall"] == 1.0
    assert audit["table_context_term_recall"] == 1.0
    assert audit["structured_context_term_recall"] == 0.0
    assert audit["missing_structured_cell_terms"] == []
    assert audit["missing_structured_context_terms"] == [
        "queue",
        "support",
        "table",
    ]


def test_expected_table_rows_are_read_from_golden_query():
    query = {"expected_table": {"rows": [["region", "owner"], ["north", "kim"]]}}

    assert expected_table_rows(query) == [["region", "owner"], ["north", "kim"]]


def test_row_and_cell_structure_metrics_compare_expected_grid():
    expected = [["region", "owner"], ["north", "kim"]]
    predicted = [["region", "owner"], ["north", "kim"], ["extra", "caption"]]

    row_metrics = row_structure_metrics(expected, predicted)
    cell_metrics = cell_structure_metrics(expected, predicted)

    assert row_metrics["row_recall"] == 1.0
    assert row_metrics["row_f1"] < 1.0
    assert cell_metrics["cell_recall"] == 1.0
    assert cell_metrics["cell_f1"] < 1.0


def test_table_candidate_filter_removes_caption_and_separator_cells():
    rows = [
        ["NORTH", "SALES", "TABLE"],
        ["|", "REGION", "OWNER", "TOTAL", "|"],
        ["NORTH", "KIM", "184"],
    ]

    assert filter_table_candidate_rows(rows) == [
        ["REGION", "OWNER", "TOTAL"],
        ["NORTH", "KIM", "184"],
    ]


def test_table_candidate_filter_keeps_table_header():
    rows = [
        ["TABLE", "OWNER", "STATUS"],
        ["RELEASE", "KIM", "READY"],
    ]

    assert filter_table_candidate_rows(rows) == rows


def test_candidate_locality_report_contains_offline_gate_fields():
    report = _locality_report(local_cache_or_install_path="configured-local-command")

    assert report == {
        "runtime_network_calls": 0,
        "automatic_model_downloads": 0,
        "local_cache_or_install_path": "configured-local-command",
        "external_provider_fallbacks": 0,
    }


def test_locality_report_can_mark_measured_runtime_guard():
    report = _locality_report(
        local_cache_or_install_path="configured-local-cache",
        verification="measured-runtime-guard",
    )

    assert report["verification"] == "measured-runtime-guard"


def test_paddleocr_model_dir_accepts_root_or_official_models_layout(tmp_path):
    direct = tmp_path / "det"
    nested = tmp_path / "official_models" / "rec"
    direct.mkdir()
    nested.mkdir(parents=True)
    (direct / "inference.yml").write_text("model: det", encoding="utf-8")
    (nested / "inference.yml").write_text("model: rec", encoding="utf-8")

    assert _paddleocr_model_dir(tmp_path, "det") == direct
    assert _paddleocr_model_dir(tmp_path, "rec") == nested


def test_paddleocr_result_words_group_by_detected_y_position():
    result = [
        {
            "rec_texts": ["REGION", "OWNER", "NORTH", "KIM"],
            "rec_scores": [0.99, 0.98, 0.97, 0.96],
            "rec_boxes": [
                [10, 10, 50, 30],
                [80, 12, 120, 30],
                [10, 60, 50, 80],
                [80, 61, 120, 80],
            ],
        }
    ]

    words = _paddleocr_result_to_words(result, min_score=0.3)

    assert _group_detected_words_into_rows(words) == [
        ["REGION", "OWNER"],
        ["NORTH", "KIM"],
    ]


def test_stage_latency_summary_reports_distribution():
    summary = _stage_latency_summary(
        {
            "render": [1.0, 2.0, 3.0],
            "predict": [10.0],
            "postprocess": [],
        }
    )

    assert summary["render"] == {
        "mean_ms": 2.0,
        "p50_ms": 2.0,
        "p95_ms": 3.0,
        "max_ms": 3.0,
    }
    assert summary["predict"]["p95_ms"] == 10.0
    assert summary["postprocess"]["p95_ms"] == 0.0


def test_term_miss_summary_splits_cell_and_context_misses():
    rows = [
        {
            "query_id": "q1",
            "term_audit": {
                "missing_structured_terms": ["caption", "total"],
                "missing_structured_cell_terms": ["total"],
                "missing_structured_context_terms": ["caption"],
            },
        },
        {
            "query_id": "q2",
            "term_audit": {
                "missing_structured_terms": ["caption"],
                "missing_structured_cell_terms": [],
                "missing_structured_context_terms": ["caption"],
            },
        },
    ]

    summary = _term_miss_summary(rows)

    assert summary["query_count"] == 2
    assert summary["structured_output_miss_query_count"] == 2
    assert summary["structured_cell_miss_query_count"] == 1
    assert summary["structured_context_miss_query_count"] == 2
    assert summary["top_missing_structured_terms"][0] == {
        "term": "caption",
        "count": 2,
    }
    assert summary["top_missing_structured_cell_terms"] == [
        {"term": "total", "count": 1}
    ]


def test_paddleocr_structure_reports_missing_local_models(monkeypatch, tmp_path):
    monkeypatch.setattr(
        poc.importlib.util,
        "find_spec",
        lambda name: object() if name in {"paddleocr", "paddle"} else None,
    )

    report = run_paddleocr_structure_poc(
        tmp_path,
        [{"relevant": [{"relative_path": "missing.pdf"}]}],
        model_cache=tmp_path,
        det_model="det",
        rec_model="rec",
        min_score=0.3,
        locality_verification="measured-runtime-guard",
    )

    assert report["status"] == "dependency-missing"
    assert report["missing_model_files"] == ["text_detection", "text_recognition"]


def test_paddleocr_structure_requires_measured_guard_binding(monkeypatch, tmp_path):
    monkeypatch.setattr(
        poc.importlib.util,
        "find_spec",
        lambda name: object() if name in {"paddleocr", "paddle"} else None,
    )
    _paddle_model_dir(tmp_path, "det", "det-yaml")
    _paddle_model_dir(tmp_path, "rec", "rec-yaml")

    report = run_paddleocr_structure_poc(
        tmp_path,
        [{"id": "q1", "query": "region owner", "relevant": [{"relative_path": "doc.pdf"}]}],
        model_cache=tmp_path,
        det_model="det",
        rec_model="rec",
        min_score=0.3,
        locality_verification="measured-runtime-guard",
    )

    assert report["status"] == "guard-binding-failed"
    assert report["guard_binding"]["status"] == "failed"
    assert "guard_artifact_missing" in report["guard_binding"]["reasons"]
    assert report["promotion_decision"] == "hold"
    assert str(tmp_path) not in str(report)


def test_paddleocr_structure_rejects_guard_model_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        poc.importlib.util,
        "find_spec",
        lambda name: object() if name in {"paddleocr", "paddle"} else None,
    )
    _paddle_model_dir(tmp_path, "det", "det-yaml")
    _paddle_model_dir(tmp_path, "rec", "rec-yaml")
    fingerprint = paddleocr_model_cache_fingerprint(
        model_cache=tmp_path,
        detector_model_id="det",
        recognizer_model_id="rec",
    )
    guard_report = _passed_guard_report(
        det_model="other-det",
        rec_model="rec",
        fingerprint=fingerprint,
    )

    report = run_paddleocr_structure_poc(
        tmp_path,
        [{"id": "q1", "query": "region owner", "relevant": [{"relative_path": "doc.pdf"}]}],
        model_cache=tmp_path,
        det_model="det",
        rec_model="rec",
        min_score=0.3,
        locality_verification="measured-runtime-guard",
        runtime_guard_report=guard_report,
    )

    assert report["status"] == "guard-binding-failed"
    assert "detector_model_id_mismatch" in report["guard_binding"]["reasons"]
    assert report["locality"]["verification"] == "guard-binding-failed"


def test_paddleocr_structure_uses_matching_runtime_guard_report(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        poc.importlib.util,
        "find_spec",
        lambda name: object() if name in {"paddleocr", "paddle"} else None,
    )
    _paddle_model_dir(tmp_path, "det", "det-yaml")
    _paddle_model_dir(tmp_path, "rec", "rec-yaml")
    fingerprint = paddleocr_model_cache_fingerprint(
        model_cache=tmp_path,
        detector_model_id="det",
        recognizer_model_id="rec",
    )
    guard_report = _passed_guard_report(
        det_model="det",
        rec_model="rec",
        fingerprint=fingerprint,
    )
    captured = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def predict(self, image_path):
            return [
                {
                    "rec_texts": ["REGION", "OWNER", "NORTH", "KIM"],
                    "rec_scores": [0.99, 0.99, 0.99, 0.99],
                    "rec_boxes": [
                        [10, 10, 50, 30],
                        [80, 10, 120, 30],
                        [10, 60, 50, 80],
                        [80, 60, 120, 80],
                    ],
                }
            ]

    monkeypatch.setattr(
        poc.importlib,
        "import_module",
        lambda name: SimpleNamespace(PaddleOCR=FakePaddleOCR),
    )
    monkeypatch.setattr(
        poc,
        "_render_first_page_image",
        lambda pdf_path, image_path, scale: Path(image_path).write_text(
            "image", encoding="utf-8"
        ),
    )

    report = run_paddleocr_structure_poc(
        tmp_path,
        [
            {
                "id": "q1",
                "query": "region owner north kim",
                "relevant": [{"relative_path": "doc.pdf"}],
                "expected_table": {
                    "rows": [["REGION", "OWNER"], ["NORTH", "KIM"]]
                },
            }
        ],
        model_cache=tmp_path,
        det_model="det",
        rec_model="rec",
        min_score=0.3,
        locality_verification="measured-runtime-guard",
        runtime_guard_report=guard_report,
    )

    assert report["status"] == "ok"
    assert report["guard_binding"]["status"] == "passed"
    assert report["locality"]["verification"] == "measured-runtime-guard"
    assert report["model_cache_fingerprint"] == fingerprint
    assert captured["text_detection_model_name"] == "det"
    assert captured["text_recognition_model_name"] == "rec"
    assert str(tmp_path) not in str(report)


def test_assign_words_to_detected_grid_cells():
    words = [
        _word("region", 12, 14),
        _word("owner", 52, 14),
        _word("north", 12, 54),
        _word("kim", 52, 54),
    ]

    rows = _assign_words_to_grid(
        words,
        vertical_lines=[0, 40, 80],
        horizontal_lines=[0, 40, 80],
    )

    assert rows == [["region", "owner"], ["north", "kim"]]


def test_structure_candidate_score_prefers_complete_multi_cell_rows():
    incomplete = [["REGION", "OWNER", "TOTAL"], ["NORTH", "KIM", "184"]]
    complete = [
        ["REGION", "OWNER", "TOTAL"],
        ["NORTH", "KIM", "184"],
        ["WEST", "LEE", "126"],
    ]

    assert _structure_candidate_score(complete) > _structure_candidate_score(incomplete)


def test_multipass_candidate_reports_missing_dependency(tmp_path):
    report = run_tesseract_multipass_poc(
        tmp_path,
        [{"relevant": [{"relative_path": "missing.pdf"}]}],
        candidate="tesseract-multipass-context-structure",
        command="missing-command",
        lang="eng",
        psm_values=["3", "4"],
        tessdata_dir="",
        min_conf=25,
    )

    assert report["status"] == "dependency-missing"
    assert report["psm_profiles"] == ["3", "4"]


def test_adaptive_projection_candidate_reports_missing_dependency(tmp_path):
    report = run_adaptive_projection_pairing_poc(
        tmp_path,
        [{"relevant": [{"relative_path": "missing.pdf"}]}],
        candidate="raster-deskew-projection-ocr-pairing",
        command="missing-command",
        lang="eng",
        psm="4",
        tessdata_dir="",
        min_conf=25,
        angle_values=[0.0, -2.0, 2.0],
    )

    assert report["status"] == "dependency-missing"
    assert report["angle_profiles"] == [0.0, -2.0, 2.0]


def test_rotate_image_creates_output(tmp_path):
    from PIL import Image

    source = tmp_path / "source.png"
    target = tmp_path / "rotated.png"
    Image.new("RGB", (20, 10), "white").save(source)

    _rotate_image(source, target, 2.0)

    assert target.exists()


def test_postprocess_candidate_reports_provenance(tmp_path):
    report = run_tesseract_tsv_poc(
        tmp_path,
        [],
        candidate="tesseract-line-filter-postprocess",
        command="missing-command",
        lang="eng",
        psm="4",
        tessdata_dir="",
        min_conf=25,
        derived_from="tesseract-tsv",
        postprocess_only=True,
    )

    assert report["derived_from"] == "tesseract-tsv"
    assert report["shared_ocr_backend"] is True
    assert report["postprocess_only"] is True


def test_postprocess_report_splits_context_and_structured_term_recall(
    monkeypatch, tmp_path
):
    tsv = "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t20\t10\t30\t12\t96\tcaption",
            "5\t1\t1\t1\t2\t1\t20\t40\t30\t12\t96\tregion",
            "5\t1\t1\t1\t2\t2\t80\t40\t30\t12\t96\towner",
            "5\t1\t1\t1\t3\t1\t20\t70\t30\t12\t96\tnorth",
            "5\t1\t1\t1\t3\t2\t80\t70\t30\t12\t96\tkim",
        ]
    )
    monkeypatch.setattr(poc, "_ocr_first_page_tsv", lambda *args, **kwargs: tsv)

    report = run_tesseract_tsv_poc(
        tmp_path,
        [
            {
                "id": "q1",
                "query": "caption region owner north kim",
                "relevant": [{"relative_path": "doc.pdf"}],
            }
        ],
        candidate="tesseract-line-filter-postprocess",
        command="tesseract",
        lang="eng",
        psm="4",
        tessdata_dir="",
        min_conf=25,
        row_transform=filter_table_candidate_rows,
        derived_from="tesseract-tsv",
        postprocess_only=True,
    )

    assert report["mean_context_term_recall"] == 1.0
    assert report["mean_structured_output_term_recall"] == 0.8
    assert report["mean_term_recall"] == 0.8
    assert report["primary_term_recall_source"] == "structured-output"
    assert report["promotion_decision"] == "hold"


def test_structure_promotion_gate_uses_structured_output_not_context():
    report = {
        "status": "ok",
        "primary_term_recall_source": "context",
        "mean_context_term_recall": 0.95,
        "mean_structured_output_term_recall": 0.70,
        "mean_row_f1": 0.90,
        "mean_cell_f1": 0.90,
        "p95_latency_ms": 100.0,
        "locality": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "local_cache_or_install_path": "configured-local-command",
            "verification": "measured-runtime-guard",
        },
    }

    gate = structure_promotion_gate(report)

    assert gate["decision"] == "hold"
    assert "primary_term_recall_not_structured_output" in gate["reasons"]
    assert "structured_output_term_recall_below_threshold" in gate["reasons"]


def test_structure_promotion_gate_can_promote_unified_local_output():
    report = {
        "status": "ok",
        "primary_term_recall_source": "structured-output",
        "mean_structured_output_term_recall": 0.90,
        "mean_row_f1": 0.82,
        "mean_cell_f1": 0.81,
        "p95_latency_ms": 120.0,
        "locality": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "local_cache_or_install_path": "configured-local-command",
            "verification": "measured-runtime-guard",
        },
    }

    gate = structure_promotion_gate(report)

    assert gate == {
        "decision": "promote",
        "criteria": {
            "structured_output_term_recall_min": 0.85,
            "row_f1_min": 0.70,
            "cell_f1_min": 0.70,
            "requires_primary_term_recall_source": "structured-output",
            "requires_offline_gate": True,
            "requires_p95_latency": True,
            "p95_latency_ms_max": 1500.0,
        },
        "reasons": [],
    }


def test_structure_promotion_gate_rejects_static_locality_values():
    report = {
        "status": "ok",
        "primary_term_recall_source": "structured-output",
        "mean_structured_output_term_recall": 0.90,
        "mean_row_f1": 0.82,
        "mean_cell_f1": 0.81,
        "p95_latency_ms": 120.0,
        "locality": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "local_cache_or_install_path": "configured-local-command",
            "verification": "static-preflight-only",
        },
    }

    gate = structure_promotion_gate(report)

    assert gate["decision"] == "hold"
    assert "runtime_locality_not_measured" in gate["reasons"]


def test_structure_promotion_gate_rejects_above_latency_budget():
    report = {
        "status": "ok",
        "primary_term_recall_source": "structured-output",
        "mean_structured_output_term_recall": 0.90,
        "mean_row_f1": 0.82,
        "mean_cell_f1": 0.81,
        "p95_latency_ms": 1500.001,
        "locality": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "local_cache_or_install_path": "configured-local-command",
            "verification": "measured-runtime-guard",
        },
    }

    gate = structure_promotion_gate(report)

    assert gate["decision"] == "hold"
    assert gate["criteria"]["p95_latency_ms_max"] == 1500.0
    assert "p95_latency_above_threshold" in gate["reasons"]


def test_claim_class_gate_does_not_promote_broad_claim_from_cell_only_success():
    report = {
        "status": "ok",
        "primary_term_recall_source": "structured-output",
        "mean_structured_output_term_recall": 0.76,
        "mean_structured_cell_term_recall": 1.0,
        "mean_table_context_term_recall": 1.0,
        "mean_context_term_recall": 1.0,
        "mean_row_f1": 1.0,
        "mean_cell_f1": 1.0,
        "mean_cell_text_f1": 1.0,
        "p95_latency_ms": 120.0,
        "locality": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "local_cache_or_install_path": "configured-local-command",
            "verification": "measured-runtime-guard",
        },
    }

    gate = structure_claim_class_gate(report)

    assert gate["broad_claim_allowed"] is False
    assert gate["claim_classes"]["broad_structured_table_retrieval"][
        "decision"
    ] == "hold"
    assert gate["claim_classes"]["structured_cell_extraction"][
        "decision"
    ] == "eligible"
    assert "structured_cell_extraction_does_not_allow_broad_claim" in gate["rules"]


def test_claim_class_gate_requires_latency_budget_for_narrow_claims():
    report = {
        "status": "ok",
        "primary_term_recall_source": "structured-output",
        "mean_structured_output_term_recall": 0.76,
        "mean_structured_cell_term_recall": 1.0,
        "mean_table_context_term_recall": 1.0,
        "mean_context_term_recall": 1.0,
        "mean_row_f1": 1.0,
        "mean_cell_f1": 1.0,
        "mean_cell_text_f1": 1.0,
        "p95_latency_ms": 2000.0,
        "locality": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "local_cache_or_install_path": "configured-local-command",
            "verification": "measured-runtime-guard",
        },
    }

    gate = structure_claim_class_gate(report)

    assert gate["claim_classes"]["structured_cell_extraction"]["decision"] == "hold"
    assert gate["claim_classes"]["table_context_retrieval"]["decision"] == "hold"
    assert "p95_latency_above_threshold" in gate["claim_classes"][
        "structured_cell_extraction"
    ]["reasons"]
    assert "p95_latency_above_threshold" in gate["claim_classes"][
        "table_context_retrieval"
    ]["reasons"]


def test_claim_class_gate_can_promote_broad_only_when_promotion_gate_passes():
    report = {
        "status": "ok",
        "primary_term_recall_source": "structured-output",
        "mean_structured_output_term_recall": 0.90,
        "mean_structured_cell_term_recall": 1.0,
        "mean_table_context_term_recall": 1.0,
        "mean_context_term_recall": 1.0,
        "mean_row_f1": 0.82,
        "mean_cell_f1": 0.81,
        "mean_cell_text_f1": 0.80,
        "p95_latency_ms": 120.0,
        "locality": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "local_cache_or_install_path": "configured-local-command",
            "verification": "measured-runtime-guard",
        },
    }

    gate = structure_claim_class_gate(report)

    assert gate["broad_claim_allowed"] is True
    assert gate["claim_classes"]["broad_structured_table_retrieval"][
        "decision"
    ] == "promote"


def test_claim_class_gate_requires_table_context_metric_for_context_claim():
    report = {
        "status": "ok",
        "primary_term_recall_source": "structured-output",
        "mean_structured_output_term_recall": 0.90,
        "mean_structured_cell_term_recall": 1.0,
        "mean_table_context_term_recall": 0.50,
        "mean_context_term_recall": 1.0,
        "mean_row_f1": 0.82,
        "mean_cell_f1": 0.81,
        "mean_cell_text_f1": 0.80,
        "p95_latency_ms": 120.0,
        "locality": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "local_cache_or_install_path": "configured-local-command",
            "verification": "measured-runtime-guard",
        },
    }

    gate = structure_claim_class_gate(report)

    assert gate["claim_classes"]["table_context_retrieval"]["decision"] == "hold"
    assert "table_context_term_recall_below_threshold" in gate["claim_classes"][
        "table_context_retrieval"
    ]["reasons"]


def _word(text: str, left: int, top: int):
    from benchmarks.scanned_table_structure_poc import TsvWord

    return TsvWord(
        text=text,
        conf=90,
        left=left,
        top=top,
        width=12,
        height=10,
        block_num="1",
        par_num="1",
        line_num="1",
    )


def _paddle_model_dir(root: Path, name: str, content: str) -> Path:
    model_dir = root / name
    model_dir.mkdir(parents=True)
    (model_dir / "inference.yml").write_text(content, encoding="utf-8")
    return model_dir


def _passed_guard_report(*, det_model: str, rec_model: str, fingerprint: str) -> dict:
    return {
        "candidate": "paddleocr-table",
        "status": "passed",
        "offline_gate": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "verification": "measured-runtime-guard",
            "local_cache_or_install_path": "configured-local-cache",
            "passed": True,
        },
        "cache_observation": {
            "created_or_changed_entries": 0,
            "absolute_paths_reported": False,
        },
        "model_binding": {
            "binding_present": True,
            "detector_model_id": det_model,
            "recognizer_model_id": rec_model,
            "model_cache_fingerprint": fingerprint,
        },
    }
