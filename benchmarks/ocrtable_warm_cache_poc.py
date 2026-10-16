from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

from benchmarks.ocrtable_cache_keys import document_result_key
from benchmarks.ocrtable_cache_keys import page_key
from benchmarks.ocrtable_cache_keys import roi_key
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


SCHEMA_VERSION = "ocrtable-warm-cache-poc-v1"
METRIC_FIELDS = (
    "structured_output_term_recall",
    "structured_cell_term_recall",
    "table_context_term_recall",
    "row_f1",
    "cell_f1",
    "mean_cell_text_f1",
)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_warm_cache_poc(
        cold_report_path=Path(args.cold_report),
        pdf_dir=Path(args.pdf_dir),
        candidate=args.candidate,
        cache_out=Path(args.cache_out) if args.cache_out else None,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-warm-cache-poc",
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


def run_warm_cache_poc(
    *,
    cold_report_path: Path,
    pdf_dir: Path,
    candidate: str = "paddleocr-structure",
    cache_out: Path | None = None,
) -> dict:
    cold_report = json.loads(cold_report_path.read_text(encoding="utf-8"))
    cold_row = _candidate(cold_report, candidate)
    details = cold_row.get("documents_detail")
    if not isinstance(details, list) or not details:
        raise ValueError("cold report must include document details")
    if cold_row.get("status") != "ok":
        raise ValueError("cold candidate status must be ok")

    cache_entries: dict[str, dict] = {}
    write_latencies = []
    for detail in details:
        started = time.perf_counter()
        key = _cache_key(pdf_dir, cold_row, detail)
        cache_entries[key] = _cache_payload(detail)
        write_latencies.append((time.perf_counter() - started) * 1000)

    if cache_out:
        cache_out.parent.mkdir(parents=True, exist_ok=True)
        cache_out.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "entries": cache_entries,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    warm_rows = []
    read_latencies = []
    for detail in details:
        started = time.perf_counter()
        key = _cache_key(pdf_dir, cold_row, detail)
        cached = cache_entries.get(key)
        read_latencies.append((time.perf_counter() - started) * 1000)
        if cached:
            warm_rows.append(cached)

    cold_metrics = _metrics_from_details(details)
    warm_metrics = _metrics_from_details(warm_rows)
    metric_delta = {
        key: round(warm_metrics.get(key, 0.0) - cold_metrics.get(key, 0.0), 9)
        for key in METRIC_FIELDS
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "source": "benchmark-only",
        "default_enabled": False,
        "candidate": candidate,
        "cold_source_report": cold_report_path.name,
        "cache_mode": "document-result-read-through-poc",
        "cache_artifact_written": bool(cache_out),
        "cache_artifact_path": "configured-private-cache" if cache_out else "not-written",
        "cache_entries_written": len(cache_entries),
        "queries": len(details),
        "warm_cache_hits": len(warm_rows),
        "warm_cache_hit_rate": round(len(warm_rows) / len(details), 6),
        "cold_metrics": cold_metrics,
        "warm_metrics": warm_metrics,
        "metric_delta": metric_delta,
        "metrics_non_regression": all(value >= 0.0 for value in metric_delta.values()),
        "cold_latency_ms": {
            "p50": float(cold_row.get("p50_latency_ms") or 0.0),
            "p95": float(cold_row.get("p95_latency_ms") or 0.0),
        },
        "warm_latency_ms": {
            "write_p50": _median(write_latencies),
            "write_p95": _p95(write_latencies),
            "read_p50": _median(read_latencies),
            "read_p95": _p95(read_latencies),
        },
        "latency_improvement": {
            "p95_ms_delta": round(_p95(read_latencies) - float(cold_row["p95_latency_ms"]), 3),
            "warm_read_p95_below_1500_ms": _p95(read_latencies) <= 1500.0,
        },
        "claim_boundary": {
            "product_cache_claim_allowed": False,
            "reason": "benchmark-only POC; product cache invalidation is not implemented",
        },
    }
    return report


def _candidate(report: dict, name: str) -> dict:
    for item in report.get("candidates", []):
        if item.get("candidate") == name:
            return item
    raise ValueError(f"candidate not found: {name}")


def _cache_key(pdf_dir: Path, candidate: dict, detail: dict) -> str:
    relative_path = str(detail["relative_path"])
    pdf_path = pdf_dir / relative_path
    content_hash = _file_digest(pdf_path)
    relative_path_hash = _text_digest(relative_path)
    detector_fingerprint = str(candidate["model_cache_fingerprint"])
    page = page_key(
        workspace_id="scanned-table-poc",
        root_id="pdf-fixture",
        file_id=_text_digest(relative_path)[:24],
        content_hash=content_hash,
        relative_path_hash=relative_path_hash,
        page_no=1,
        render_profile={
            "render_scale": candidate["runtime_options"]["render_scale"],
            "rotation_degrees": 0.0,
            "color_mode": "RGB",
            "normalization_version": "pymupdf-first-page-v1",
        },
        detector_profile={
            "detector_model_id": candidate["det_model"],
            "model_cache_fingerprint": detector_fingerprint,
            "score_threshold": candidate["recognition_min_score"],
            "runtime_family": "paddleocr-table",
            "runtime_options": {
                "device": "cpu",
                "mkldnn": candidate["runtime_options"]["enable_mkldnn"],
                "threads": candidate["runtime_options"]["cpu_threads"],
            },
        },
        locality_profile={
            "cache_status": "configured-local-cache",
            "verification": candidate["locality"]["verification"],
        },
        code_profile="scanned-table-structure-poc-v1",
    )
    roi = roi_key(
        page_key_value=page,
        normalized_bbox=[0.0, 0.0, 1.0, 1.0],
        roi_transform_profile={
            "bbox_source": "full-page-result",
            "crop_margin": 0.0,
            "transform_version": "warm-cache-poc-v1",
        },
        recognizer_profile={
            "recognizer_model_id": candidate["rec_model"],
            "model_cache_fingerprint": detector_fingerprint,
            "score_threshold": candidate["recognition_min_score"],
        },
        postprocess_profile={
            "row_grouping_version": "paddleocr-y-row-grouping-v1",
            "cell_assignment_version": "paddleocr-cell-text-v1",
            "table_filter_version": "filter-table-candidate-rows-v1",
            "structured_output_version": "scanned-table-structure-poc-v1",
        },
        code_profile="scanned-table-structure-poc-v1",
    )
    return document_result_key(
        page_key_value=page,
        roi_key_values=[roi],
        document_assembly_profile={"assembly_version": "warm-cache-poc-v1"},
        code_profile="scanned-table-structure-poc-v1",
    )


def _cache_payload(detail: dict) -> dict:
    return {
        "query_id": detail.get("query_id", ""),
        "relative_path_hash": _text_digest(str(detail.get("relative_path", ""))),
        **{key: float(detail.get(key) or 0.0) for key in METRIC_FIELDS},
        "row_count": int(detail.get("row_count") or 0),
        "predicted_cell_count": int(detail.get("predicted_cell_count") or 0),
    }


def _metrics_from_details(details: list[dict]) -> dict:
    return {
        key: round(statistics.fmean(float(item.get(key) or 0.0) for item in details), 6)
        if details
        else 0.0
        for key in METRIC_FIELDS
    }


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 6) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 6)
    ordered = sorted(values)
    index = (len(ordered) - 1) * 0.95
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("cold_report")
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--candidate", default="paddleocr-structure")
    parser.add_argument("--cache-out", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
