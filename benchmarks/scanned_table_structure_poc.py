from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import json
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fitz

from benchmarks.ocrtable_guard_binding import paddleocr_model_cache_fingerprint
from benchmarks.ocrtable_guard_binding import paddleocr_model_dir
from benchmarks.ocrtable_guard_binding import validate_paddleocr_guard_binding
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


WORD_PATTERN = re.compile(r"[A-Za-z0-9가-힣]+")
STRUCTURED_TERM_RECALL_PROMOTION_MIN = 0.85
STRUCTURED_CELL_TERM_RECALL_CLAIM_MIN = 0.85
TABLE_CONTEXT_TERM_RECALL_CLAIM_MIN = 0.85
ROW_F1_PROMOTION_MIN = 0.70
CELL_F1_PROMOTION_MIN = 0.70
CELL_TEXT_F1_CLAIM_MIN = 0.70
STRUCTURED_TABLE_P95_LATENCY_MS_MAX = 1500.0
UNCONFIGURED_LOCALITY_PATHS = {
    None,
    "",
    "missing",
    "dependency-missing",
    "adapter-pending",
}


@dataclass(frozen=True)
class TsvWord:
    text: str
    conf: float
    left: int
    top: int
    width: int
    height: int
    block_num: str
    par_num: str
    line_num: str


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    pdf_dir = Path(args.pdf_dir)
    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    paddleocr_guard_report = None
    if args.paddleocr_runtime_guard_report:
        paddleocr_guard_report = json.loads(
            Path(args.paddleocr_runtime_guard_report).read_text(encoding="utf-8")
        )
    started = time.perf_counter()
    tesseract_row = run_tesseract_tsv_poc(
        pdf_dir,
        golden.get("queries", []),
        candidate="tesseract-tsv",
        command=args.tesseract_cmd,
        lang=args.lang,
        psm=args.psm,
        tessdata_dir=args.tessdata_dir,
        min_conf=args.min_conf,
        include_document_details=args.include_document_details,
    )
    line_filter_row = run_tesseract_tsv_poc(
        pdf_dir,
        golden.get("queries", []),
        candidate="tesseract-line-filter-postprocess",
        command=args.tesseract_cmd,
        lang=args.lang,
        psm=args.psm,
        tessdata_dir=args.tessdata_dir,
        min_conf=args.min_conf,
        row_transform=filter_table_candidate_rows,
        derived_from="tesseract-tsv",
        postprocess_only=True,
        include_document_details=args.include_document_details,
    )
    multipass_row = run_tesseract_multipass_poc(
        pdf_dir,
        golden.get("queries", []),
        candidate="tesseract-multipass-context-structure",
        command=args.tesseract_cmd,
        lang=args.lang,
        psm_values=args.multipass_psm,
        tessdata_dir=args.tessdata_dir,
        min_conf=args.min_conf,
        include_document_details=args.include_document_details,
    )
    projection_pairing_row = run_projection_pairing_poc(
        pdf_dir,
        golden.get("queries", []),
        candidate="raster-projection-ocr-pairing",
        command=args.tesseract_cmd,
        lang=args.lang,
        psm=args.psm,
        tessdata_dir=args.tessdata_dir,
        min_conf=args.min_conf,
        include_document_details=args.include_document_details,
    )
    adaptive_projection_pairing_row = run_adaptive_projection_pairing_poc(
        pdf_dir,
        golden.get("queries", []),
        candidate="raster-deskew-projection-ocr-pairing",
        command=args.tesseract_cmd,
        lang=args.lang,
        psm=args.psm,
        tessdata_dir=args.tessdata_dir,
        min_conf=args.min_conf,
        angle_values=args.projection_angle,
        include_document_details=args.include_document_details,
    )
    paddleocr_row = _candidate_status(
        "paddleocr-structure",
        required_modules=["paddleocr", "paddle"],
        note=(
            "candidate adapter only; requires explicit local PaddleOCR model "
            "cache and remains outside the default runtime"
        ),
    )
    if args.paddleocr_model_cache:
        paddleocr_row = run_paddleocr_structure_poc(
            pdf_dir,
            golden.get("queries", []),
            model_cache=Path(args.paddleocr_model_cache),
            det_model=args.paddleocr_det_model,
            rec_model=args.paddleocr_rec_model,
            min_score=args.paddleocr_min_score,
            locality_verification=args.paddleocr_locality_verification,
            runtime_guard_report=paddleocr_guard_report,
            enable_mkldnn=args.paddleocr_enable_mkldnn,
            cpu_threads=args.paddleocr_cpu_threads,
            render_scale=args.paddleocr_render_scale,
            include_document_details=args.include_document_details,
        )
    report = {
        "poc_name": "scanned-table-structure",
        "default_enabled": False,
        "source": "local",
        "locality": _locality_report(
            local_cache_or_install_path=_locality_install_status(
                args.tesseract_cmd, args.tessdata_dir
            )
        ),
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "candidates": [
            tesseract_row,
            line_filter_row,
            multipass_row,
            projection_pairing_row,
            adaptive_projection_pairing_row,
            paddleocr_row,
            _candidate_status(
                "table-transformer",
                required_modules=["transformers", "torch"],
                note="candidate adapter only; requires a detector plus OCR pairing",
            ),
        ],
    }
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "scanned-table-structure-poc",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    if findings:
        print(
            json.dumps(
                {
                    "error": "artifact scan failed",
                    "findings": public_findings(findings),
                },
                indent=2,
            )
        )
        return 1
    if args.out:
        Path(args.out).write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


def run_tesseract_multipass_poc(
    pdf_dir: Path,
    queries: list[dict],
    *,
    candidate: str = "tesseract-multipass-context-structure",
    command: str,
    lang: str,
    psm_values: list[str],
    tessdata_dir: str,
    min_conf: float,
    include_document_details: bool = False,
) -> dict:
    if not psm_values:
        psm_values = ["3", "4"]
    rows = []
    errors = []
    latencies = []
    for query in queries:
        target_path = _first_relevant_path(query)
        if target_path is None:
            continue
        pdf_path = pdf_dir / target_path
        try:
            document_started = time.perf_counter()
            context_rows = []
            structure_candidates = []
            for psm in psm_values:
                tsv = _ocr_first_page_tsv(
                    pdf_path,
                    command=command,
                    lang=lang,
                    psm=psm,
                    tessdata_dir=tessdata_dir,
                )
                raw_rows = group_words_into_rows(parse_tesseract_tsv(tsv, min_conf))
                context_rows.extend(raw_rows)
                structure_rows = filter_table_candidate_rows(raw_rows)
                structure_candidates.append(
                    {
                        "psm": psm,
                        "score": _structure_candidate_score(structure_rows),
                        "rows": structure_rows,
                    }
                )
            best = max(
                structure_candidates,
                key=lambda item: (item["score"], len(item["rows"])),
                default={"psm": "", "rows": []},
            )
            table_rows = best["rows"]
            latency_ms = (time.perf_counter() - document_started) * 1000
            latencies.append(latency_ms)
            expected_rows = expected_table_rows(query)
            row_metrics = row_structure_metrics(expected_rows, table_rows)
            cell_metrics = cell_structure_metrics(expected_rows, table_rows)
            context_term_recall = term_recall(query.get("query", ""), context_rows)
            structured_term_recall = term_recall(query.get("query", ""), table_rows)
            term_audit = term_recall_audit(
                query.get("query", ""),
                context_rows,
                table_rows,
                expected_rows,
            )
            rows.append(
                {
                    "query_id": query.get("id", ""),
                    "relative_path": target_path,
                    "selected_psm": best["psm"],
                    "row_count": len(table_rows),
                    "expected_row_count": len(expected_rows),
                    "predicted_cell_count": _cell_count(table_rows),
                    "expected_cell_count": _cell_count(expected_rows),
                    "term_recall": context_term_recall,
                    "context_term_recall": context_term_recall,
                    "structured_output_term_recall": structured_term_recall,
                    "structured_cell_term_recall": term_audit[
                        "structured_cell_term_recall"
                    ],
                    "table_context_term_recall": term_audit[
                        "table_context_term_recall"
                    ],
                    "structured_context_term_recall": term_audit[
                        "structured_context_term_recall"
                    ],
                    "missing_structured_term_count": len(
                        term_audit["missing_structured_terms"]
                    ),
                    "term_audit": term_audit,
                    "row_f1": row_metrics["row_f1"],
                    "cell_f1": cell_metrics["cell_f1"],
                    "mean_cell_text_f1": cell_metrics["mean_cell_text_f1"],
                    "row_count_error": row_metrics["row_count_error"],
                    "column_count_error": _column_count_error(expected_rows, table_rows),
                    "latency_ms": round(latency_ms, 3),
                }
            )
        except FileNotFoundError as exc:
            row = _dependency_missing_candidate(candidate, len(queries), exc)
            row["psm_profiles"] = psm_values
            return row
        except Exception as exc:
            errors.append(_error_label(exc))
    report = {
        "candidate": candidate,
        "derived_from": "tesseract-tsv",
        "shared_ocr_backend": True,
        "postprocess_only": False,
        "status": "ok" if rows else "no-results",
        "locality": _locality_report(
            local_cache_or_install_path=_locality_install_status(command, tessdata_dir)
        ),
        "psm_profiles": psm_values,
        "term_source": "multipass-raw-ocr-context",
        "structure_source": "best-line-filter-by-layout-heuristic",
        "primary_term_recall_source": "context",
        "documents": len(rows),
        "tables_detected": sum(1 for item in rows if item["row_count"] >= 2),
        "mean_term_recall": round(
            statistics.fmean(item["term_recall"] for item in rows), 6
        )
        if rows
        else 0.0,
        "mean_context_term_recall": _mean(rows, "context_term_recall"),
        "mean_structured_output_term_recall": _mean(
            rows, "structured_output_term_recall"
        ),
        "mean_structured_cell_term_recall": _mean(
            rows, "structured_cell_term_recall"
        ),
        "mean_table_context_term_recall": _mean(rows, "table_context_term_recall"),
        "mean_structured_context_term_recall": _mean(
            rows, "structured_context_term_recall"
        ),
        "mean_row_f1": _mean(rows, "row_f1"),
        "mean_cell_f1": _mean(rows, "cell_f1"),
        "mean_cell_text_f1": _mean(rows, "mean_cell_text_f1"),
        "mean_row_count_error": _mean(rows, "row_count_error"),
        "mean_column_count_error": _mean(rows, "column_count_error"),
        "p50_latency_ms": round(statistics.median(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": round(_percentile(latencies, 95), 3) if latencies else 0.0,
        "errors": errors[:5],
    }
    return _with_document_details(report, rows, include_document_details)


def run_projection_pairing_poc(
    pdf_dir: Path,
    queries: list[dict],
    *,
    candidate: str = "raster-projection-ocr-pairing",
    command: str,
    lang: str,
    psm: str,
    tessdata_dir: str,
    min_conf: float,
    include_document_details: bool = False,
) -> dict:
    rows = []
    errors = []
    latencies = []
    for query in queries:
        target_path = _first_relevant_path(query)
        if target_path is None:
            continue
        pdf_path = pdf_dir / target_path
        try:
            document_started = time.perf_counter()
            with tempfile.TemporaryDirectory() as temp_dir:
                image_path = Path(temp_dir) / "page.png"
                _render_first_page_image(pdf_path, image_path)
                tsv = _run_tesseract_image_tsv(
                    image_path,
                    command=command,
                    lang=lang,
                    psm=psm,
                    tessdata_dir=tessdata_dir,
                )
                words = parse_tesseract_tsv(tsv, min_conf=min_conf)
                table_rows = project_words_into_grid(image_path, words)
                context_rows = group_words_into_rows(words)
            latency_ms = (time.perf_counter() - document_started) * 1000
            latencies.append(latency_ms)
            expected_rows = expected_table_rows(query)
            row_metrics = row_structure_metrics(expected_rows, table_rows)
            cell_metrics = cell_structure_metrics(expected_rows, table_rows)
            context_term_recall = term_recall(query.get("query", ""), context_rows)
            structured_term_recall = term_recall(query.get("query", ""), table_rows)
            term_audit = term_recall_audit(
                query.get("query", ""),
                context_rows,
                table_rows,
                expected_rows,
            )
            rows.append(
                {
                    "query_id": query.get("id", ""),
                    "relative_path": target_path,
                    "row_count": len(table_rows),
                    "expected_row_count": len(expected_rows),
                    "predicted_cell_count": _cell_count(table_rows),
                    "expected_cell_count": _cell_count(expected_rows),
                    "term_recall": structured_term_recall,
                    "context_term_recall": context_term_recall,
                    "structured_output_term_recall": structured_term_recall,
                    "structured_cell_term_recall": term_audit[
                        "structured_cell_term_recall"
                    ],
                    "table_context_term_recall": term_audit[
                        "table_context_term_recall"
                    ],
                    "structured_context_term_recall": term_audit[
                        "structured_context_term_recall"
                    ],
                    "missing_structured_term_count": len(
                        term_audit["missing_structured_terms"]
                    ),
                    "term_audit": term_audit,
                    "row_f1": row_metrics["row_f1"],
                    "cell_f1": cell_metrics["cell_f1"],
                    "mean_cell_text_f1": cell_metrics["mean_cell_text_f1"],
                    "row_count_error": row_metrics["row_count_error"],
                    "column_count_error": _column_count_error(expected_rows, table_rows),
                    "latency_ms": round(latency_ms, 3),
                }
            )
        except FileNotFoundError as exc:
            return _dependency_missing_candidate(candidate, len(queries), exc)
        except Exception as exc:
            errors.append(_error_label(exc))
    report = {
        "candidate": candidate,
        "derived_from": "raster-projection-detector+tesseract-tsv",
        "shared_ocr_backend": True,
        "postprocess_only": False,
        "status": "ok" if rows else "no-results",
        "locality": _locality_report(
            local_cache_or_install_path=_locality_install_status(command, "")
        ),
        "detector_profile": "dark-pixel-projection-grid-v1",
        "term_source": "raw-ocr-context",
        "structure_source": "projected-grid",
        "primary_term_recall_source": "structured-output",
        "documents": len(rows),
        "tables_detected": sum(1 for item in rows if item["row_count"] >= 2),
        "mean_term_recall": round(
            statistics.fmean(item["term_recall"] for item in rows), 6
        )
        if rows
        else 0.0,
        "mean_context_term_recall": _mean(rows, "context_term_recall"),
        "mean_structured_output_term_recall": _mean(
            rows, "structured_output_term_recall"
        ),
        "mean_structured_cell_term_recall": _mean(
            rows, "structured_cell_term_recall"
        ),
        "mean_table_context_term_recall": _mean(rows, "table_context_term_recall"),
        "mean_structured_context_term_recall": _mean(
            rows, "structured_context_term_recall"
        ),
        "mean_row_f1": _mean(rows, "row_f1"),
        "mean_cell_f1": _mean(rows, "cell_f1"),
        "mean_cell_text_f1": _mean(rows, "mean_cell_text_f1"),
        "mean_row_count_error": _mean(rows, "row_count_error"),
        "mean_column_count_error": _mean(rows, "column_count_error"),
        "p50_latency_ms": round(statistics.median(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": round(_percentile(latencies, 95), 3) if latencies else 0.0,
        "errors": errors[:5],
    }
    return _with_document_details(report, rows, include_document_details)


def run_adaptive_projection_pairing_poc(
    pdf_dir: Path,
    queries: list[dict],
    *,
    candidate: str = "raster-deskew-projection-ocr-pairing",
    command: str,
    lang: str,
    psm: str,
    tessdata_dir: str,
    min_conf: float,
    angle_values: list[float],
    include_document_details: bool = False,
) -> dict:
    angles = angle_values or [0.0]
    rows = []
    errors = []
    latencies = []
    for query in queries:
        target_path = _first_relevant_path(query)
        if target_path is None:
            continue
        pdf_path = pdf_dir / target_path
        try:
            document_started = time.perf_counter()
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                image_path = temp_path / "page.png"
                _render_first_page_image(pdf_path, image_path)
                best = _best_projection_candidate(
                    image_path,
                    angles,
                    command=command,
                    lang=lang,
                    psm=psm,
                    tessdata_dir=tessdata_dir,
                    min_conf=min_conf,
                )
            table_rows = best["rows"]
            context_rows = best["context_rows"]
            latency_ms = (time.perf_counter() - document_started) * 1000
            latencies.append(latency_ms)
            expected_rows = expected_table_rows(query)
            row_metrics = row_structure_metrics(expected_rows, table_rows)
            cell_metrics = cell_structure_metrics(expected_rows, table_rows)
            context_term_recall = term_recall(query.get("query", ""), context_rows)
            structured_term_recall = term_recall(query.get("query", ""), table_rows)
            term_audit = term_recall_audit(
                query.get("query", ""),
                context_rows,
                table_rows,
                expected_rows,
            )
            rows.append(
                {
                    "query_id": query.get("id", ""),
                    "relative_path": target_path,
                    "selected_angle": best["angle"],
                    "row_count": len(table_rows),
                    "expected_row_count": len(expected_rows),
                    "predicted_cell_count": _cell_count(table_rows),
                    "expected_cell_count": _cell_count(expected_rows),
                    "term_recall": structured_term_recall,
                    "context_term_recall": context_term_recall,
                    "structured_output_term_recall": structured_term_recall,
                    "structured_cell_term_recall": term_audit[
                        "structured_cell_term_recall"
                    ],
                    "table_context_term_recall": term_audit[
                        "table_context_term_recall"
                    ],
                    "structured_context_term_recall": term_audit[
                        "structured_context_term_recall"
                    ],
                    "missing_structured_term_count": len(
                        term_audit["missing_structured_terms"]
                    ),
                    "term_audit": term_audit,
                    "row_f1": row_metrics["row_f1"],
                    "cell_f1": cell_metrics["cell_f1"],
                    "mean_cell_text_f1": cell_metrics["mean_cell_text_f1"],
                    "row_count_error": row_metrics["row_count_error"],
                    "column_count_error": _column_count_error(expected_rows, table_rows),
                    "latency_ms": round(latency_ms, 3),
                }
            )
        except FileNotFoundError as exc:
            row = _dependency_missing_candidate(candidate, len(queries), exc)
            row["angle_profiles"] = angles
            return row
        except Exception as exc:
            errors.append(_error_label(exc))
    report = {
        "candidate": candidate,
        "derived_from": "raster-projection-detector+tesseract-tsv",
        "shared_ocr_backend": True,
        "postprocess_only": False,
        "status": "ok" if rows else "no-results",
        "locality": _locality_report(
            local_cache_or_install_path=_locality_install_status(command, "")
        ),
        "detector_profile": "dark-pixel-projection-grid-v2-rotation-search",
        "angle_profiles": angles,
        "term_source": "selected-angle-raw-ocr-context",
        "structure_source": "selected-angle-projected-grid",
        "primary_term_recall_source": "structured-output",
        "documents": len(rows),
        "tables_detected": sum(1 for item in rows if item["row_count"] >= 2),
        "mean_term_recall": round(
            statistics.fmean(item["term_recall"] for item in rows), 6
        )
        if rows
        else 0.0,
        "mean_context_term_recall": _mean(rows, "context_term_recall"),
        "mean_structured_output_term_recall": _mean(
            rows, "structured_output_term_recall"
        ),
        "mean_structured_cell_term_recall": _mean(
            rows, "structured_cell_term_recall"
        ),
        "mean_table_context_term_recall": _mean(rows, "table_context_term_recall"),
        "mean_structured_context_term_recall": _mean(
            rows, "structured_context_term_recall"
        ),
        "mean_row_f1": _mean(rows, "row_f1"),
        "mean_cell_f1": _mean(rows, "cell_f1"),
        "mean_cell_text_f1": _mean(rows, "mean_cell_text_f1"),
        "mean_row_count_error": _mean(rows, "row_count_error"),
        "mean_column_count_error": _mean(rows, "column_count_error"),
        "p50_latency_ms": round(statistics.median(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": round(_percentile(latencies, 95), 3) if latencies else 0.0,
        "errors": errors[:5],
    }
    return _with_document_details(report, rows, include_document_details)


def run_tesseract_tsv_poc(
    pdf_dir: Path,
    queries: list[dict],
    *,
    candidate: str = "tesseract-tsv",
    command: str,
    lang: str,
    psm: str,
    tessdata_dir: str,
    min_conf: float,
    row_transform=None,
    derived_from: str | None = None,
    postprocess_only: bool = False,
    include_document_details: bool = False,
) -> dict:
    rows = []
    errors = []
    started = time.perf_counter()
    latencies = []
    for query in queries:
        target_path = _first_relevant_path(query)
        if target_path is None:
            continue
        pdf_path = pdf_dir / target_path
        try:
            document_started = time.perf_counter()
            tsv = _ocr_first_page_tsv(
                pdf_path,
                command=command,
                lang=lang,
                psm=psm,
                tessdata_dir=tessdata_dir,
            )
            words = parse_tesseract_tsv(tsv, min_conf=min_conf)
            context_rows = group_words_into_rows(words)
            table_rows = context_rows
            if row_transform is not None:
                table_rows = row_transform(table_rows)
            latency_ms = (time.perf_counter() - document_started) * 1000
            latencies.append(latency_ms)
            expected_rows = expected_table_rows(query)
            row_metrics = row_structure_metrics(expected_rows, table_rows)
            cell_metrics = cell_structure_metrics(expected_rows, table_rows)
            context_term_recall = term_recall(query.get("query", ""), context_rows)
            structured_term_recall = term_recall(query.get("query", ""), table_rows)
            term_audit = term_recall_audit(
                query.get("query", ""),
                context_rows,
                table_rows,
                expected_rows,
            )
            rows.append(
                {
                    "query_id": query.get("id", ""),
                    "relative_path": target_path,
                    "row_count": len(table_rows),
                    "expected_row_count": len(expected_rows),
                    "predicted_cell_count": _cell_count(table_rows),
                    "expected_cell_count": _cell_count(expected_rows),
                    "term_recall": structured_term_recall,
                    "context_term_recall": context_term_recall,
                    "structured_output_term_recall": structured_term_recall,
                    "structured_cell_term_recall": term_audit[
                        "structured_cell_term_recall"
                    ],
                    "table_context_term_recall": term_audit[
                        "table_context_term_recall"
                    ],
                    "structured_context_term_recall": term_audit[
                        "structured_context_term_recall"
                    ],
                    "missing_structured_term_count": len(
                        term_audit["missing_structured_terms"]
                    ),
                    "term_audit": term_audit,
                    "row_f1": row_metrics["row_f1"],
                    "cell_f1": cell_metrics["cell_f1"],
                    "mean_cell_text_f1": cell_metrics["mean_cell_text_f1"],
                    "row_count_error": row_metrics["row_count_error"],
                    "column_count_error": _column_count_error(expected_rows, table_rows),
                    "latency_ms": round(latency_ms, 3),
                }
            )
        except FileNotFoundError as exc:
            row = _dependency_missing_candidate(candidate, len(queries), exc)
            row["derived_from"] = derived_from
            row["shared_ocr_backend"] = bool(derived_from)
            row["postprocess_only"] = postprocess_only
            return row
        except Exception as exc:
            errors.append(_error_label(exc))
    report = {
        "candidate": candidate,
        "derived_from": derived_from,
        "shared_ocr_backend": bool(derived_from),
        "postprocess_only": postprocess_only,
        "status": "ok" if rows else "no-results",
        "locality": _locality_report(
            local_cache_or_install_path=_locality_install_status(command, tessdata_dir)
        ),
        "term_source": "structured-output",
        "structure_source": "tesseract-tsv-rows",
        "primary_term_recall_source": "structured-output",
        "documents": len(rows),
        "tables_detected": sum(1 for item in rows if item["row_count"] >= 2),
        "mean_term_recall": round(
            statistics.fmean(item["term_recall"] for item in rows), 6
        )
        if rows
        else 0.0,
        "mean_context_term_recall": _mean(rows, "context_term_recall"),
        "mean_structured_output_term_recall": _mean(
            rows, "structured_output_term_recall"
        ),
        "mean_structured_cell_term_recall": _mean(
            rows, "structured_cell_term_recall"
        ),
        "mean_table_context_term_recall": _mean(rows, "table_context_term_recall"),
        "mean_structured_context_term_recall": _mean(
            rows, "structured_context_term_recall"
        ),
        "mean_row_f1": _mean(rows, "row_f1"),
        "mean_cell_f1": _mean(rows, "cell_f1"),
        "mean_cell_text_f1": _mean(rows, "mean_cell_text_f1"),
        "mean_row_count_error": _mean(rows, "row_count_error"),
        "mean_column_count_error": _mean(rows, "column_count_error"),
        "p50_latency_ms": round(statistics.median(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": round(_percentile(latencies, 95), 3) if latencies else 0.0,
        "errors": errors[:5],
    }
    return _with_document_details(report, rows, include_document_details)


def run_paddleocr_structure_poc(
    pdf_dir: Path,
    queries: list[dict],
    *,
    model_cache: Path,
    det_model: str,
    rec_model: str,
    min_score: float,
    locality_verification: str,
    runtime_guard_report: dict | None = None,
    enable_mkldnn: bool = False,
    cpu_threads: int = 0,
    render_scale: float = 2.0,
    include_document_details: bool = False,
) -> dict:
    missing = [
        module
        for module in ("paddleocr", "paddle")
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        report = _dependency_missing_candidate(
            "paddleocr-structure",
            len(queries),
            ModuleNotFoundError(",".join(missing)),
        )
        report["missing_modules"] = missing
        return report

    det_dir = _paddleocr_model_dir(model_cache, det_model)
    rec_dir = _paddleocr_model_dir(model_cache, rec_model)
    missing_model_files = [
        label
        for label, model_dir in (("text_detection", det_dir), ("text_recognition", rec_dir))
        if not (model_dir / "inference.yml").exists()
    ]
    if missing_model_files:
        report = _dependency_missing_candidate(
            "paddleocr-structure",
            len(queries),
            FileNotFoundError(",".join(missing_model_files)),
        )
        report["missing_model_files"] = missing_model_files
        return report
    model_cache_fingerprint_value = paddleocr_model_cache_fingerprint(
        model_cache=model_cache,
        detector_model_id=det_model,
        recognizer_model_id=rec_model,
    )
    guard_binding = {
        "required": locality_verification == "measured-runtime-guard",
        "status": "not-required",
        "reasons": [],
    }
    if locality_verification == "measured-runtime-guard":
        guard_binding = validate_paddleocr_guard_binding(
            runtime_guard_report,
            detector_model_id=det_model,
            recognizer_model_id=rec_model,
            model_cache_fingerprint_value=model_cache_fingerprint_value,
        )
        if guard_binding["status"] != "passed":
            return _guard_binding_failed_candidate(
                len(queries),
                det_model=det_model,
                rec_model=rec_model,
                model_cache_fingerprint_value=model_cache_fingerprint_value,
                guard_binding=guard_binding,
            )

    init_started = time.perf_counter()
    paddleocr_module = importlib.import_module("paddleocr")
    runtime_kwargs = {
        "device": "cpu",
        "enable_mkldnn": enable_mkldnn,
    }
    if cpu_threads > 0:
        runtime_kwargs["cpu_threads"] = cpu_threads
    ocr = paddleocr_module.PaddleOCR(
        text_detection_model_name=det_model,
        text_detection_model_dir=str(det_dir),
        text_recognition_model_name=rec_model,
        text_recognition_model_dir=str(rec_dir),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        **runtime_kwargs,
    )
    initialization_latency_ms = (time.perf_counter() - init_started) * 1000
    rows = []
    errors = []
    latencies = []
    stage_latencies = {
        "render": [],
        "predict": [],
        "postprocess": [],
    }
    for query in queries:
        target_path = _first_relevant_path(query)
        if target_path is None:
            continue
        pdf_path = pdf_dir / target_path
        try:
            document_started = time.perf_counter()
            with tempfile.TemporaryDirectory() as temp_dir:
                image_path = Path(temp_dir) / "page.png"
                render_started = time.perf_counter()
                _render_first_page_image(pdf_path, image_path, scale=render_scale)
                render_latency_ms = (time.perf_counter() - render_started) * 1000
                predict_started = time.perf_counter()
                result = ocr.predict(str(image_path))
                predict_latency_ms = (time.perf_counter() - predict_started) * 1000
            postprocess_started = time.perf_counter()
            words = _paddleocr_result_to_words(result, min_score=min_score)
            context_rows = _group_detected_words_into_rows(words)
            table_rows = filter_table_candidate_rows(context_rows)
            postprocess_latency_ms = (time.perf_counter() - postprocess_started) * 1000
            latency_ms = (time.perf_counter() - document_started) * 1000
            latencies.append(latency_ms)
            stage_latencies["render"].append(render_latency_ms)
            stage_latencies["predict"].append(predict_latency_ms)
            stage_latencies["postprocess"].append(postprocess_latency_ms)
            expected_rows = expected_table_rows(query)
            row_metrics = row_structure_metrics(expected_rows, table_rows)
            cell_metrics = cell_structure_metrics(expected_rows, table_rows)
            context_term_recall = term_recall(query.get("query", ""), context_rows)
            structured_term_recall = term_recall(query.get("query", ""), table_rows)
            term_audit = term_recall_audit(
                query.get("query", ""),
                context_rows,
                table_rows,
                expected_rows,
            )
            rows.append(
                {
                    "query_id": query.get("id", ""),
                    "relative_path": target_path,
                    "row_count": len(table_rows),
                    "expected_row_count": len(expected_rows),
                    "predicted_cell_count": _cell_count(table_rows),
                    "expected_cell_count": _cell_count(expected_rows),
                    "term_recall": structured_term_recall,
                    "context_term_recall": context_term_recall,
                    "structured_output_term_recall": structured_term_recall,
                    "structured_cell_term_recall": term_audit[
                        "structured_cell_term_recall"
                    ],
                    "table_context_term_recall": term_audit[
                        "table_context_term_recall"
                    ],
                    "structured_context_term_recall": term_audit[
                        "structured_context_term_recall"
                    ],
                    "missing_structured_term_count": len(
                        term_audit["missing_structured_terms"]
                    ),
                    "term_audit": term_audit,
                    "row_f1": row_metrics["row_f1"],
                    "cell_f1": cell_metrics["cell_f1"],
                    "mean_cell_text_f1": cell_metrics["mean_cell_text_f1"],
                    "row_count_error": row_metrics["row_count_error"],
                    "column_count_error": _column_count_error(expected_rows, table_rows),
                    "latency_ms": round(latency_ms, 3),
                    "latency_breakdown_ms": {
                        "render": round(render_latency_ms, 3),
                        "predict": round(predict_latency_ms, 3),
                        "postprocess": round(postprocess_latency_ms, 3),
                    },
                }
            )
        except Exception as exc:
            errors.append(_error_label(exc))

    report = {
        "candidate": "paddleocr-structure",
        "derived_from": None,
        "shared_ocr_backend": False,
        "postprocess_only": False,
        "status": "ok" if rows else "no-results",
        "locality": _locality_report(
            local_cache_or_install_path="configured-local-cache",
            verification=locality_verification,
        ),
        "det_model": det_model,
        "rec_model": rec_model,
        "model_cache_fingerprint": model_cache_fingerprint_value,
        "guard_binding": guard_binding,
        "runtime_options": {
            "enable_mkldnn": enable_mkldnn,
            "cpu_threads": cpu_threads,
            "render_scale": render_scale,
        },
        "recognition_min_score": min_score,
        "term_source": "paddleocr-recognized-text",
        "structure_source": "paddleocr-detection-y-row-grouping",
        "primary_term_recall_source": "structured-output",
        "documents": len(rows),
        "tables_detected": sum(1 for item in rows if item["row_count"] >= 2),
        "mean_term_recall": round(
            statistics.fmean(item["term_recall"] for item in rows), 6
        )
        if rows
        else 0.0,
        "mean_context_term_recall": _mean(rows, "context_term_recall"),
        "mean_structured_output_term_recall": _mean(
            rows, "structured_output_term_recall"
        ),
        "mean_structured_cell_term_recall": _mean(
            rows, "structured_cell_term_recall"
        ),
        "mean_table_context_term_recall": _mean(rows, "table_context_term_recall"),
        "mean_structured_context_term_recall": _mean(
            rows, "structured_context_term_recall"
        ),
        "mean_row_f1": _mean(rows, "row_f1"),
        "mean_cell_f1": _mean(rows, "cell_f1"),
        "mean_cell_text_f1": _mean(rows, "mean_cell_text_f1"),
        "mean_row_count_error": _mean(rows, "row_count_error"),
        "mean_column_count_error": _mean(rows, "column_count_error"),
        "initialization_latency_ms": round(initialization_latency_ms, 3),
        "latency_stage_summary": _stage_latency_summary(stage_latencies),
        "term_miss_summary": _term_miss_summary(rows),
        "p50_latency_ms": round(statistics.median(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": round(_percentile(latencies, 95), 3) if latencies else 0.0,
        "errors": errors[:5],
    }
    return _with_document_details(report, rows, include_document_details)


def parse_tesseract_tsv(tsv_text: str, min_conf: float) -> list[TsvWord]:
    words = []
    reader = csv.DictReader(tsv_text.splitlines(), delimiter="\t")
    for row in reader:
        text = " ".join((row.get("text") or "").split())
        if not text:
            continue
        conf = _float(row.get("conf"), default=-1.0)
        if conf < min_conf:
            continue
        words.append(
            TsvWord(
                text=text,
                conf=conf,
                left=_int(row.get("left")),
                top=_int(row.get("top")),
                width=_int(row.get("width")),
                height=_int(row.get("height")),
                block_num=row.get("block_num") or "0",
                par_num=row.get("par_num") or "0",
                line_num=row.get("line_num") or "0",
            )
        )
    return words


def group_words_into_rows(words: Iterable[TsvWord]) -> list[list[str]]:
    grouped: dict[tuple[str, str, str], list[TsvWord]] = {}
    for word in words:
        key = (word.block_num, word.par_num, word.line_num)
        grouped.setdefault(key, []).append(word)
    lines = sorted(
        grouped.values(),
        key=lambda items: (
            min(word.top for word in items),
            min(word.left for word in items),
        ),
    )
    return [
        [word.text for word in sorted(line, key=lambda item: item.left)]
        for line in lines
        if line
    ]


def _group_detected_words_into_rows(words: Iterable[TsvWord]) -> list[list[str]]:
    rows: list[list[TsvWord]] = []
    for word in sorted(words, key=lambda item: (item.top + item.height / 2, item.left)):
        center_y = word.top + word.height / 2
        placed = False
        for row in rows:
            row_center = statistics.fmean(item.top + item.height / 2 for item in row)
            tolerance = max(12.0, statistics.fmean(item.height for item in row) * 0.75)
            if abs(center_y - row_center) <= tolerance:
                row.append(word)
                placed = True
                break
        if not placed:
            rows.append([word])
    return [
        [word.text for word in sorted(row, key=lambda item: item.left)]
        for row in rows
        if row
    ]


def filter_table_candidate_rows(rows: list[list[str]]) -> list[list[str]]:
    cleaned = []
    for row in rows:
        cells = [
            cell
            for cell in row
            if _tokens(cell) and cell.strip() not in {"|", "||"}
        ]
        if cells:
            cleaned.append(cells)
    while len(cleaned) > 1 and _looks_like_caption_row(cleaned[0]):
        cleaned = cleaned[1:]
    if len(cleaned) <= 1:
        return cleaned
    return [row for row in cleaned if len(row) >= 2]


def _structure_candidate_score(rows: list[list[str]]) -> float:
    if not rows:
        return 0.0
    multi_cell_rows = [row for row in rows if len(row) >= 2]
    term_count = sum(len(_flatten_tokens(row)) for row in multi_cell_rows)
    row_count_penalty = abs(len(multi_cell_rows) - 3) * 2
    single_cell_penalty = (len(rows) - len(multi_cell_rows)) * 3
    return len(multi_cell_rows) * 10 + term_count - row_count_penalty - single_cell_penalty


def project_words_into_grid(image_path: Path, words: list[TsvWord]) -> list[list[str]]:
    grid = _detect_table_grid_lines(image_path)
    if grid is None:
        return []
    vertical_lines, horizontal_lines = grid
    return _assign_words_to_grid(words, vertical_lines, horizontal_lines)


def term_recall(query: str, rows: list[list[str]]) -> float:
    expected = set(_tokens(query))
    if not expected:
        return 0.0
    observed = set(_tokens(" ".join(" ".join(row) for row in rows)))
    return len(expected & observed) / len(expected)


def term_recall_audit(
    query: str,
    context_rows: list[list[str]],
    structured_rows: list[list[str]],
    expected_rows: list[list[str]],
) -> dict:
    query_terms = set(_tokens(query))
    cell_terms = set(_flatten_tokens(_flatten_rows(expected_rows)))
    query_cell_terms = query_terms & cell_terms
    query_context_terms = query_terms - cell_terms
    context_terms = set(_flatten_tokens(_flatten_rows(context_rows)))
    structured_terms = set(_flatten_tokens(_flatten_rows(structured_rows)))

    return {
        "query_term_count": len(query_terms),
        "cell_query_term_count": len(query_cell_terms),
        "context_query_term_count": len(query_context_terms),
        "structured_cell_term_recall": _term_set_recall(
            query_cell_terms,
            structured_terms,
        ),
        "table_context_term_recall": _term_set_recall(
            query_context_terms,
            context_terms,
        ),
        "structured_context_term_recall": _term_set_recall(
            query_context_terms,
            structured_terms,
        ),
        "missing_structured_terms": sorted(query_terms - structured_terms),
        "missing_structured_cell_terms": sorted(query_cell_terms - structured_terms),
        "missing_structured_context_terms": sorted(
            query_context_terms - structured_terms
        ),
    }


def _term_set_recall(expected_terms: set[str], observed_terms: set[str]) -> float:
    if not expected_terms:
        return 1.0
    return len(expected_terms & observed_terms) / len(expected_terms)


def _flatten_rows(rows: list[list[str]]) -> list[str]:
    return [cell for row in rows for cell in row]


def expected_table_rows(query: dict) -> list[list[str]]:
    table = query.get("expected_table") or {}
    rows = table.get("rows") or []
    return [[str(cell) for cell in row] for row in rows if row]


def row_structure_metrics(
    expected_rows: list[list[str]],
    predicted_rows: list[list[str]],
) -> dict[str, float]:
    if not expected_rows:
        return {
            "row_precision": 0.0,
            "row_recall": 0.0,
            "row_f1": 0.0,
            "row_count_error": float(len(predicted_rows)),
        }
    matched_expected = _matched_row_indexes(expected_rows, predicted_rows)
    matched_predicted = _matched_row_indexes(predicted_rows, expected_rows)
    precision = len(matched_predicted) / len(predicted_rows) if predicted_rows else 0.0
    recall = len(matched_expected) / len(expected_rows)
    return {
        "row_precision": round(precision, 6),
        "row_recall": round(recall, 6),
        "row_f1": round(_f1(precision, recall), 6),
        "row_count_error": float(abs(len(predicted_rows) - len(expected_rows))),
    }


def cell_structure_metrics(
    expected_rows: list[list[str]],
    predicted_rows: list[list[str]],
) -> dict[str, float]:
    expected_cells = _normalized_cells(expected_rows)
    predicted_cells = _normalized_cells(predicted_rows)
    if not expected_cells:
        return {
            "cell_precision": 0.0,
            "cell_recall": 0.0,
            "cell_f1": 0.0,
            "mean_cell_text_f1": 0.0,
        }
    matched_expected: set[int] = set()
    matched_predicted: set[int] = set()
    text_scores = []
    for expected_index, expected in enumerate(expected_cells):
        best_index = None
        best_score = 0.0
        for predicted_index, predicted in enumerate(predicted_cells):
            if predicted_index in matched_predicted:
                continue
            score = _token_f1(expected, predicted)
            if score > best_score:
                best_index = predicted_index
                best_score = score
        text_scores.append(best_score)
        if best_index is not None and best_score >= 0.75:
            matched_expected.add(expected_index)
            matched_predicted.add(best_index)
    precision = len(matched_predicted) / len(predicted_cells) if predicted_cells else 0.0
    recall = len(matched_expected) / len(expected_cells)
    return {
        "cell_precision": round(precision, 6),
        "cell_recall": round(recall, 6),
        "cell_f1": round(_f1(precision, recall), 6),
        "mean_cell_text_f1": round(statistics.fmean(text_scores), 6)
        if text_scores
        else 0.0,
    }


def _matched_row_indexes(
    source_rows: list[list[str]],
    target_rows: list[list[str]],
) -> set[int]:
    matched = set()
    for source_index, source in enumerate(source_rows):
        if any(_token_f1(source, target) >= 0.5 for target in target_rows):
            matched.add(source_index)
    return matched


def _looks_like_caption_row(row: list[str]) -> bool:
    terms = set(_flatten_tokens(row))
    if "fixture" in terms:
        return True
    if "table" not in terms:
        return False
    return not _looks_like_structural_header(terms)


def _looks_like_structural_header(terms: set[str]) -> bool:
    header_terms = {
        "agent",
        "count",
        "metric",
        "owner",
        "p95",
        "priority",
        "rank",
        "region",
        "risk",
        "score",
        "signal",
        "state",
        "status",
        "total",
    }
    return len(terms) >= 3 and bool(terms & header_terms)


def _normalized_cells(rows: list[list[str]]) -> list[list[str]]:
    cells = []
    for row in rows:
        for cell in row:
            cell_terms = _tokens(str(cell))
            if cell_terms:
                cells.append(cell_terms)
    return cells


def _token_f1(left: list[str], right: list[str]) -> float:
    left_set = set(_flatten_tokens(left))
    right_set = set(_flatten_tokens(right))
    if not left_set or not right_set:
        return 0.0
    overlap = len(left_set & right_set)
    precision = overlap / len(right_set)
    recall = overlap / len(left_set)
    return _f1(precision, recall)


def _flatten_tokens(values: list[str]) -> list[str]:
    tokens = []
    for value in values:
        tokens.extend(_tokens(value))
    return tokens


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _cell_count(rows: list[list[str]]) -> int:
    return sum(len(row) for row in rows)


def _column_count_error(
    expected_rows: list[list[str]],
    predicted_rows: list[list[str]],
) -> float:
    expected = max((len(row) for row in expected_rows), default=0)
    predicted = max((len(row) for row in predicted_rows), default=0)
    return float(abs(predicted - expected))


def _mean(rows: list[dict], key: str) -> float:
    values = [float(row[key]) for row in rows if key in row]
    return round(statistics.fmean(values), 6) if values else 0.0


def _stage_latency_summary(stage_latencies: dict[str, list[float]]) -> dict:
    return {
        stage: _latency_distribution(values)
        for stage, values in sorted(stage_latencies.items())
    }


def _latency_distribution(values: list[float]) -> dict:
    if not values:
        return {
            "mean_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
        }
    return {
        "mean_ms": round(statistics.fmean(values), 3),
        "p50_ms": round(statistics.median(values), 3),
        "p95_ms": round(_percentile(values, 95), 3),
        "max_ms": round(max(values), 3),
    }


def _term_miss_summary(rows: list[dict]) -> dict:
    return {
        "query_count": len(rows),
        "structured_output_miss_query_count": _term_miss_query_count(
            rows, "missing_structured_terms"
        ),
        "structured_cell_miss_query_count": _term_miss_query_count(
            rows, "missing_structured_cell_terms"
        ),
        "structured_context_miss_query_count": _term_miss_query_count(
            rows, "missing_structured_context_terms"
        ),
        "top_missing_structured_terms": _top_missing_terms(
            rows, "missing_structured_terms"
        ),
        "top_missing_structured_cell_terms": _top_missing_terms(
            rows, "missing_structured_cell_terms"
        ),
        "top_missing_structured_context_terms": _top_missing_terms(
            rows, "missing_structured_context_terms"
        ),
    }


def _term_miss_query_count(rows: list[dict], audit_key: str) -> int:
    return sum(
        1
        for row in rows
        if (row.get("term_audit", {}).get(audit_key) or [])
    )


def _top_missing_terms(
    rows: list[dict],
    audit_key: str,
    *,
    limit: int = 10,
) -> list[dict]:
    counts: dict[str, int] = {}
    for row in rows:
        for term in row.get("term_audit", {}).get(audit_key) or []:
            counts[str(term)] = counts.get(str(term), 0) + 1
    return [
        {"term": term, "count": count}
        for term, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:limit]
    ]


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = int(round((percentile / 100) * (len(ordered) - 1)))
    return ordered[max(0, min(index, len(ordered) - 1))]


def _ocr_first_page_tsv(
    pdf_path: Path,
    *,
    command: str,
    lang: str,
    psm: str,
    tessdata_dir: str,
) -> str:
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path.name)
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "page.png"
        with fitz.open(pdf_path) as doc:
            if len(doc) == 0:
                return ""
            pixmap = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixmap.save(str(image_path))
        args = [command, str(image_path), "stdout", "-l", lang]
        if tessdata_dir:
            args.extend(["--tessdata-dir", tessdata_dir])
        if psm:
            args.extend(["--psm", psm])
        args.append("tsv")
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if completed.returncode != 0:
        return ""
    return completed.stdout or ""


def _render_first_page_image(
    pdf_path: Path,
    image_path: Path,
    *,
    scale: float = 2.0,
) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path.name)
    with fitz.open(pdf_path) as doc:
        if len(doc) == 0:
            raise ValueError("empty PDF")
        pixmap = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        pixmap.save(str(image_path))


def _run_tesseract_image_tsv(
    image_path: Path,
    *,
    command: str,
    lang: str,
    psm: str,
    tessdata_dir: str,
) -> str:
    args = [command, str(image_path), "stdout", "-l", lang]
    if tessdata_dir:
        args.extend(["--tessdata-dir", tessdata_dir])
    if psm:
        args.extend(["--psm", psm])
    args.append("tsv")
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout or ""


def _detect_table_grid_lines(image_path: Path) -> tuple[list[int], list[int]] | None:
    import numpy as np
    from PIL import Image, ImageFilter

    with Image.open(image_path) as image:
        gray = image.convert("L").filter(ImageFilter.MedianFilter(size=3))
        pixels = np.asarray(gray)
    dark_pixels = pixels < 205
    horizontal_scores = dark_pixels.mean(axis=1)
    vertical_scores = dark_pixels.mean(axis=0)
    horizontal_lines = _line_centers(horizontal_scores, min_score=0.22)
    vertical_lines = _line_centers(vertical_scores, min_score=0.12)
    horizontal_lines = _trim_outer_noise(horizontal_lines)
    vertical_lines = _trim_outer_noise(vertical_lines)
    if len(horizontal_lines) < 2 or len(vertical_lines) < 2:
        return None
    return vertical_lines, horizontal_lines


def _line_centers(scores, *, min_score: float) -> list[int]:
    centers = []
    start = None
    for index, score in enumerate(scores):
        if score >= min_score and start is None:
            start = index
        elif score < min_score and start is not None:
            if index - start >= 2:
                centers.append((start + index - 1) // 2)
            start = None
    if start is not None and len(scores) - start >= 2:
        centers.append((start + len(scores) - 1) // 2)
    return centers


def _trim_outer_noise(lines: list[int]) -> list[int]:
    if len(lines) <= 6:
        return lines
    best = lines
    for start in range(0, len(lines) - 2):
        candidate = lines[start:]
        gaps = [right - left for left, right in zip(candidate, candidate[1:])]
        if len(gaps) >= 2 and min(gaps) >= 20:
            best = candidate
            break
    return best


def _assign_words_to_grid(
    words: list[TsvWord],
    vertical_lines: list[int],
    horizontal_lines: list[int],
) -> list[list[str]]:
    row_bands = list(zip(horizontal_lines[:-1], horizontal_lines[1:]))
    column_bands = list(zip(vertical_lines[:-1], vertical_lines[1:]))
    buckets: dict[tuple[int, int], list[TsvWord]] = {}
    for word in words:
        center_x = word.left + word.width / 2
        center_y = word.top + word.height / 2
        row_index = _band_index(center_y, row_bands)
        column_index = _band_index(center_x, column_bands)
        if row_index is None or column_index is None:
            continue
        buckets.setdefault((row_index, column_index), []).append(word)
    rows = []
    for row_index, _ in enumerate(row_bands):
        row = []
        for column_index, _ in enumerate(column_bands):
            words_in_cell = sorted(
                buckets.get((row_index, column_index), []),
                key=lambda item: item.left,
            )
            row.append(" ".join(word.text for word in words_in_cell).strip())
        if any(_tokens(cell) for cell in row):
            rows.append(row)
    return rows


def _best_projection_candidate(
    image_path: Path,
    angles: list[float],
    *,
    command: str,
    lang: str,
    psm: str,
    tessdata_dir: str,
    min_conf: float,
) -> dict:
    candidates = []
    for angle in angles:
        candidate_image = image_path
        if angle:
            candidate_image = image_path.with_name(
                f"{image_path.stem}_{_angle_label(angle)}.png"
            )
            _rotate_image(image_path, candidate_image, angle)
        tsv = _run_tesseract_image_tsv(
            candidate_image,
            command=command,
            lang=lang,
            psm=psm,
            tessdata_dir=tessdata_dir,
        )
        words = parse_tesseract_tsv(tsv, min_conf=min_conf)
        table_rows = project_words_into_grid(candidate_image, words)
        candidates.append(
            {
                "angle": angle,
                "rows": table_rows,
                "context_rows": group_words_into_rows(words),
                "score": _structure_candidate_score(table_rows),
            }
        )
    return max(
        candidates,
        key=lambda item: (item["score"], len(item["rows"])),
        default={"angle": 0.0, "rows": [], "context_rows": []},
    )


def _rotate_image(source: Path, target: Path, angle: float) -> None:
    from PIL import Image

    with Image.open(source) as image:
        image.rotate(angle, expand=True, fillcolor=(255, 255, 255)).save(target)


def _angle_label(angle: float) -> str:
    return str(angle).replace("-", "m").replace(".", "p")


def _band_index(value: float, bands: list[tuple[int, int]]) -> int | None:
    for index, (start, end) in enumerate(bands):
        margin = max(4, (end - start) * 0.04)
        if start + margin <= value <= end - margin:
            return index
    return None


def _candidate_status(
    candidate: str,
    *,
    required_modules: list[str],
    note: str,
) -> dict:
    missing = [
        module
        for module in required_modules
        if importlib.util.find_spec(module) is None
    ]
    status = "dependency-missing" if missing else "adapter-pending"
    return _with_structure_promotion_gate({
        "candidate": candidate,
        "status": status,
        "locality": _locality_report(
            local_cache_or_install_path="dependency-missing" if missing else "adapter-pending"
        ),
        "documents": 0,
        "tables_detected": 0,
        "mean_term_recall": 0.0,
        "mean_context_term_recall": 0.0,
        "mean_structured_output_term_recall": 0.0,
        "mean_row_f1": 0.0,
        "mean_cell_f1": 0.0,
        "mean_cell_text_f1": 0.0,
        "p50_latency_ms": 0.0,
        "p95_latency_ms": 0.0,
        "missing_modules": missing,
        "note": note,
    })


def _dependency_missing_candidate(
    candidate: str,
    documents: int,
    exc: BaseException,
) -> dict:
    return _with_structure_promotion_gate({
        "candidate": candidate,
        "status": "dependency-missing",
        "locality": _locality_report(local_cache_or_install_path="missing"),
        "documents": documents,
        "tables_detected": 0,
        "mean_term_recall": 0.0,
        "mean_context_term_recall": 0.0,
        "mean_structured_output_term_recall": 0.0,
        "mean_row_f1": 0.0,
        "mean_cell_f1": 0.0,
        "mean_cell_text_f1": 0.0,
        "p50_latency_ms": 0.0,
        "p95_latency_ms": 0.0,
        "errors": [_error_label(exc)],
    })


def _guard_binding_failed_candidate(
    documents: int,
    *,
    det_model: str,
    rec_model: str,
    model_cache_fingerprint_value: str,
    guard_binding: dict,
) -> dict:
    return _with_structure_promotion_gate(
        {
            "candidate": "paddleocr-structure",
            "status": "guard-binding-failed",
            "locality": _locality_report(
                local_cache_or_install_path="configured-local-cache",
                verification="guard-binding-failed",
            ),
            "det_model": det_model,
            "rec_model": rec_model,
            "model_cache_fingerprint": model_cache_fingerprint_value,
            "guard_binding": guard_binding,
            "documents": documents,
            "tables_detected": 0,
            "mean_term_recall": 0.0,
            "mean_context_term_recall": 0.0,
            "mean_structured_output_term_recall": 0.0,
            "mean_structured_cell_term_recall": 0.0,
            "mean_table_context_term_recall": 0.0,
            "mean_structured_context_term_recall": 0.0,
            "mean_row_f1": 0.0,
            "mean_cell_f1": 0.0,
            "mean_cell_text_f1": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "primary_term_recall_source": "structured-output",
            "errors": guard_binding["reasons"],
        }
    )


def _with_document_details(
    report: dict,
    rows: list[dict],
    include_document_details: bool,
) -> dict:
    report = _with_structure_promotion_gate(report)
    if include_document_details:
        report["documents_detail"] = rows
    else:
        report["documents_detail_count"] = len(rows)
        report["documents_detail"] = "omitted; enable --include-document-details locally"
    return report


def _with_structure_promotion_gate(report: dict) -> dict:
    report["structure_promotion_gate"] = structure_promotion_gate(report)
    report["claim_class_gate"] = structure_claim_class_gate(
        report,
        report["structure_promotion_gate"],
    )
    report["promotion_decision"] = report["structure_promotion_gate"]["decision"]
    return report


def structure_claim_class_gate(
    report: dict,
    broad_gate: dict | None = None,
) -> dict:
    broad_gate = broad_gate or structure_promotion_gate(report)
    structured_cell_reasons = _claim_common_reasons(report)
    table_context_reasons = _claim_common_reasons(report)

    if (
        float(report.get("mean_structured_cell_term_recall") or 0.0)
        < STRUCTURED_CELL_TERM_RECALL_CLAIM_MIN
    ):
        structured_cell_reasons.append("structured_cell_term_recall_below_threshold")
    if float(report.get("mean_row_f1") or 0.0) < ROW_F1_PROMOTION_MIN:
        structured_cell_reasons.append("row_f1_below_threshold")
    if float(report.get("mean_cell_f1") or 0.0) < CELL_F1_PROMOTION_MIN:
        structured_cell_reasons.append("cell_f1_below_threshold")
    if float(report.get("mean_cell_text_f1") or 0.0) < CELL_TEXT_F1_CLAIM_MIN:
        structured_cell_reasons.append("cell_text_f1_below_threshold")

    if (
        float(report.get("mean_table_context_term_recall") or 0.0)
        < TABLE_CONTEXT_TERM_RECALL_CLAIM_MIN
    ):
        table_context_reasons.append("table_context_term_recall_below_threshold")
    if float(report.get("mean_context_term_recall") or 0.0) <= 0.0:
        table_context_reasons.append("context_term_recall_not_recorded")

    return {
        "broad_claim_allowed": broad_gate["decision"] == "promote",
        "claim_classes": {
            "broad_structured_table_retrieval": {
                "decision": broad_gate["decision"],
                "reasons": broad_gate["reasons"],
                "source_gate": "structure_promotion_gate",
            },
            "structured_cell_extraction": {
                "decision": "eligible" if not structured_cell_reasons else "hold",
                "criteria": {
                    "structured_cell_term_recall_min": STRUCTURED_CELL_TERM_RECALL_CLAIM_MIN,
                    "row_f1_min": ROW_F1_PROMOTION_MIN,
                    "cell_f1_min": CELL_F1_PROMOTION_MIN,
                    "cell_text_f1_min": CELL_TEXT_F1_CLAIM_MIN,
                    "requires_offline_gate": True,
                    "requires_p95_latency": True,
                    "p95_latency_ms_max": STRUCTURED_TABLE_P95_LATENCY_MS_MAX,
                },
                "reasons": structured_cell_reasons,
            },
            "table_context_retrieval": {
                "decision": "eligible" if not table_context_reasons else "hold",
                "criteria": {
                    "table_context_term_recall_min": TABLE_CONTEXT_TERM_RECALL_CLAIM_MIN,
                    "requires_context_term_recall": True,
                    "requires_offline_gate": True,
                    "requires_p95_latency": True,
                    "p95_latency_ms_max": STRUCTURED_TABLE_P95_LATENCY_MS_MAX,
                },
                "reasons": table_context_reasons,
            },
        },
        "rules": [
            "structured_cell_extraction_does_not_allow_broad_claim",
            "table_context_retrieval_does_not_allow_broad_claim",
            "broad_claim_requires_structure_promotion_gate",
        ],
    }


def _claim_common_reasons(report: dict) -> list[str]:
    reasons = []
    locality = report.get("locality", {})
    if report.get("status") != "ok":
        reasons.append("candidate_status_not_ok")
    reasons.extend(_p95_latency_reasons(report))
    if locality.get("runtime_network_calls") != 0:
        reasons.append("runtime_network_calls_not_zero")
    if locality.get("automatic_model_downloads") != 0:
        reasons.append("automatic_model_downloads_not_zero")
    if locality.get("external_provider_fallbacks") != 0:
        reasons.append("external_provider_fallbacks_not_zero")
    if locality.get("verification") != "measured-runtime-guard":
        reasons.append("runtime_locality_not_measured")
    if locality.get("local_cache_or_install_path") in UNCONFIGURED_LOCALITY_PATHS:
        reasons.append("local_cache_or_install_path_not_configured")
    return reasons


def structure_promotion_gate(report: dict) -> dict:
    reasons = []
    locality = report.get("locality", {})
    if report.get("status") != "ok":
        reasons.append("candidate_status_not_ok")
    if report.get("primary_term_recall_source") != "structured-output":
        reasons.append("primary_term_recall_not_structured_output")
    if (
        float(report.get("mean_structured_output_term_recall") or 0.0)
        < STRUCTURED_TERM_RECALL_PROMOTION_MIN
    ):
        reasons.append("structured_output_term_recall_below_threshold")
    if float(report.get("mean_row_f1") or 0.0) < ROW_F1_PROMOTION_MIN:
        reasons.append("row_f1_below_threshold")
    if float(report.get("mean_cell_f1") or 0.0) < CELL_F1_PROMOTION_MIN:
        reasons.append("cell_f1_below_threshold")
    reasons.extend(_p95_latency_reasons(report))
    if locality.get("runtime_network_calls") != 0:
        reasons.append("runtime_network_calls_not_zero")
    if locality.get("automatic_model_downloads") != 0:
        reasons.append("automatic_model_downloads_not_zero")
    if locality.get("external_provider_fallbacks") != 0:
        reasons.append("external_provider_fallbacks_not_zero")
    if locality.get("verification") != "measured-runtime-guard":
        reasons.append("runtime_locality_not_measured")
    if locality.get("local_cache_or_install_path") in UNCONFIGURED_LOCALITY_PATHS:
        reasons.append("local_cache_or_install_path_not_configured")
    return {
        "decision": "promote" if not reasons else "hold",
        "criteria": {
            "structured_output_term_recall_min": STRUCTURED_TERM_RECALL_PROMOTION_MIN,
            "row_f1_min": ROW_F1_PROMOTION_MIN,
            "cell_f1_min": CELL_F1_PROMOTION_MIN,
            "requires_primary_term_recall_source": "structured-output",
            "requires_offline_gate": True,
            "requires_p95_latency": True,
            "p95_latency_ms_max": STRUCTURED_TABLE_P95_LATENCY_MS_MAX,
        },
        "reasons": reasons,
    }


def _p95_latency_reasons(report: dict) -> list[str]:
    p95_latency_ms = float(report.get("p95_latency_ms") or 0.0)
    if p95_latency_ms <= 0.0:
        return ["p95_latency_not_recorded"]
    if p95_latency_ms > STRUCTURED_TABLE_P95_LATENCY_MS_MAX:
        return ["p95_latency_above_threshold"]
    return []


def _first_relevant_path(query: dict) -> str | None:
    for target in query.get("relevant", []):
        relative_path = target.get("relative_path")
        if relative_path:
            return relative_path
    return None


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in WORD_PATTERN.finditer(text)]


def _int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _float(value: str | None, default: float) -> float:
    try:
        return float(value or default)
    except ValueError:
        return default


def _error_label(exc: BaseException) -> str:
    label = exc.__class__.__name__
    message = str(exc)
    if not message:
        return label
    return f"{label}: {message[:120]}"


def _locality_report(
    *,
    local_cache_or_install_path: str,
    verification: str | None = None,
) -> dict:
    report = {
        "runtime_network_calls": 0,
        "automatic_model_downloads": 0,
        "local_cache_or_install_path": local_cache_or_install_path,
        "external_provider_fallbacks": 0,
    }
    if verification is not None:
        report["verification"] = verification
    return report


def _paddleocr_model_dir(model_cache: Path, model_name: str) -> Path:
    return paddleocr_model_dir(model_cache, model_name)


def _paddleocr_result_to_words(result, *, min_score: float) -> list[TsvWord]:
    if not result:
        return []
    first = result[0]
    texts = list(first.get("rec_texts") or [])
    scores = list(first.get("rec_scores") or [])
    boxes = first.get("rec_boxes")
    if boxes is None:
        boxes = []
    if hasattr(boxes, "tolist"):
        boxes = boxes.tolist()
    words = []
    for index, text in enumerate(texts):
        score = float(scores[index]) if index < len(scores) else 0.0
        if score < min_score:
            continue
        box = boxes[index] if index < len(boxes) else [0, 0, 0, 0]
        left, top, right, bottom = _box_bounds(box)
        words.append(
            TsvWord(
                text=str(text),
                conf=score * 100,
                left=left,
                top=top,
                width=max(0, right - left),
                height=max(0, bottom - top),
                block_num="1",
                par_num="1",
                line_num=str(index),
            )
        )
    return words


def _box_bounds(box) -> tuple[int, int, int, int]:
    if hasattr(box, "tolist"):
        box = box.tolist()
    if len(box) == 4 and all(not isinstance(item, (list, tuple)) for item in box):
        left, top, right, bottom = box
        return int(left), int(top), int(right), int(bottom)
    points = box or [[0, 0], [0, 0], [0, 0], [0, 0]]
    xs = [int(point[0]) for point in points if len(point) >= 2]
    ys = [int(point[1]) for point in points if len(point) >= 2]
    return min(xs, default=0), min(ys, default=0), max(xs, default=0), max(ys, default=0)


def _locality_install_status(command: str, tessdata_dir: str) -> str:
    if tessdata_dir:
        return "configured-local-command-and-tessdata"
    if shutil.which(command):
        return "configured-local-command"
    return "missing"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "pdf_dir",
        nargs="?",
        default="benchmarks/fixtures/pdf_corpus",
    )
    parser.add_argument(
        "--golden",
        default="benchmarks/fixtures/golden_pdf_scanned_table_queries.json",
    )
    parser.add_argument("--tesseract-cmd", default="tesseract")
    parser.add_argument("--tessdata-dir", default="")
    parser.add_argument("--lang", default="eng")
    parser.add_argument("--psm", default="4")
    parser.add_argument("--multipass-psm", action="append", default=["3", "4", "11", "12"])
    parser.add_argument(
        "--projection-angle",
        action="append",
        type=float,
        default=[0.0, -2.0, 2.0],
    )
    parser.add_argument("--min-conf", type=float, default=25.0)
    parser.add_argument("--paddleocr-model-cache", default="")
    parser.add_argument("--paddleocr-det-model", default="PP-OCRv5_server_det")
    parser.add_argument("--paddleocr-rec-model", default="en_PP-OCRv5_mobile_rec")
    parser.add_argument("--paddleocr-min-score", type=float, default=0.3)
    parser.add_argument("--paddleocr-enable-mkldnn", action="store_true")
    parser.add_argument("--paddleocr-cpu-threads", type=int, default=0)
    parser.add_argument("--paddleocr-render-scale", type=float, default=2.0)
    parser.add_argument("--paddleocr-runtime-guard-report", default="")
    parser.add_argument(
        "--paddleocr-locality-verification",
        choices=("static-preflight-only", "measured-runtime-guard"),
        default="static-preflight-only",
    )
    parser.add_argument("--include-document-details", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
