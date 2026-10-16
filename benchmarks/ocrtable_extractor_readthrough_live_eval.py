from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locallens.core.config import Settings
from locallens.core.types import SyncReport
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.security.artifact_scan import ArtifactFinding
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


SCHEMA_VERSION = "ocrtable-extractor-readthrough-live-eval-v1"
RAW_REPORT_KEYS = {
    "absolute_path",
    "blob_path",
    "blob_rel_path",
    "cache_blob_path",
    "cache_blob_paths",
    "extracted_text",
    "full_text",
    "ocr_text",
    "private_path",
    "raw_payload",
    "table_text",
    "text",
    "text_preview",
}
TABLE_DOCS = (
    "table_report.pdf",
    "invoice_like_table.pdf",
    "table_budget_review_01.pdf",
    "table_rollout_plan_02.pdf",
    "table_latency_check_10.pdf",
)
OCR_DOCS = (
    "ocr_receipt_total_01.pdf",
    "ocr_inventory_label_03.pdf",
    "ocr_service_notice_02.pdf",
    "ocr_noisy_receipt_06.pdf",
    "ocr_rotated_notice_07.pdf",
)
OPTIONAL_UNIT_TYPES = {"pdf_ocr_text", "pdf_table"}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_extractor_readthrough_live_eval(
        pdf_dir=Path(args.pdf_dir),
        table_docs=args.table_doc or list(TABLE_DOCS),
        ocr_docs=args.ocr_doc or list(OCR_DOCS),
        warm_repeats=args.warm_repeats,
        tesseract_cmd=args.tesseract_cmd,
        ocr_lang=args.ocr_lang,
        tesseract_psm=args.tesseract_psm,
        run_table=not args.skip_table,
        run_ocr=not args.skip_ocr,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-extractor-readthrough-live-eval",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-extractor-readthrough-live-eval",
        )
    )
    if findings:
        print(
            json.dumps(
                {"error": "artifact scan failed", "findings": public_findings(findings)},
                indent=2,
            )
        )
        return 1
    if args.out:
        Path(args.out).write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


def run_extractor_readthrough_live_eval(
    *,
    pdf_dir: Path,
    table_docs: list[str],
    ocr_docs: list[str],
    warm_repeats: int = 3,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    tesseract_psm: str = "6",
    run_table: bool = True,
    run_ocr: bool = True,
) -> dict[str, Any]:
    if warm_repeats < 1:
        raise ValueError("warm_repeats must be at least 1")
    pdf_dir = pdf_dir.resolve()
    started = time.perf_counter()
    modes: dict[str, dict[str, Any]] = {}
    if run_table:
        modes["table"] = _run_mode(
            pdf_dir=pdf_dir,
            docs=table_docs,
            mode="table",
            warm_repeats=warm_repeats,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    if run_ocr:
        modes["ocr"] = _run_mode(
            pdf_dir=pdf_dir,
            docs=ocr_docs,
            mode="ocr",
            warm_repeats=warm_repeats,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    aggregate = _aggregate_decision(modes)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "local-live",
        "default_enabled": False,
        "search_time_cache_source_allowed": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "runtime": _runtime_summary(),
        "corpus": {
            "table_docs": len(table_docs) if run_table else 0,
            "ocr_docs": len(ocr_docs) if run_ocr else 0,
            "warm_repeats": warm_repeats,
        },
        "modes": modes,
        "aggregate": aggregate,
    }


def _run_mode(
    *,
    pdf_dir: Path,
    docs: list[str],
    mode: str,
    warm_repeats: int,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    missing = [name for name in docs if not (pdf_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing fixture PDFs: {', '.join(missing)}")
    with tempfile.TemporaryDirectory(prefix=f"locallens-{mode}-live-") as temp_root:
        temp = Path(temp_root)
        source = temp / "source"
        data_dir = temp / "data"
        source.mkdir()
        for name in docs:
            (source / name).write_bytes((pdf_dir / name).read_bytes())
        settings = _settings_for_mode(
            data_dir=data_dir,
            mode=mode,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
        store = QdrantStore(settings, in_memory=True)
        manifest = ManifestStore(settings.manifest_path)
        sync = SyncService(settings, store=store, manifest=manifest)
        cold_started = time.perf_counter()
        cold = sync.sync_folder(source)
        cold_latency_ms = (time.perf_counter() - cold_started) * 1000
        cold_signatures = _optional_signatures(store.payload_records())

        warm_reports = []
        warm_latencies = []
        warm_signature_matches = []
        for _ in range(warm_repeats):
            _touch_all(source)
            warm_started = time.perf_counter()
            warm = sync.sync_folder(source)
            warm_latencies.append((time.perf_counter() - warm_started) * 1000)
            warm_reports.append(warm)
            warm_signature_matches.append(
                _optional_signatures(store.payload_records()) == cold_signatures
            )
        manifest_cache_entries = manifest.cache_entry_count(state="committed")
        store.close()
    return _mode_report(
        mode=mode,
        docs=docs,
        cold=cold,
        cold_latency_ms=cold_latency_ms,
        cold_signatures=cold_signatures,
        warm_reports=warm_reports,
        warm_latencies=warm_latencies,
        warm_signature_matches=warm_signature_matches,
        manifest_cache_entries=manifest_cache_entries,
    )


def _settings_for_mode(
    *,
    data_dir: Path,
    mode: str,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> Settings:
    if mode == "table":
        return Settings(
            data_dir=data_dir,
            workspace_id="ocrtable-live-table",
            pdf_table_mode="local-table",
            pdf_ocr_table_cache_mode="read-through",
        )
    if mode == "ocr":
        return Settings(
            data_dir=data_dir,
            workspace_id="ocrtable-live-ocr",
            pdf_ocr_mode="local-ocr",
            pdf_ocr_lang=ocr_lang,
            tesseract_cmd=tesseract_cmd,
            tesseract_psm=tesseract_psm,
            pdf_ocr_table_cache_mode="read-through",
        )
    raise ValueError(f"unsupported mode: {mode}")


def _mode_report(
    *,
    mode: str,
    docs: list[str],
    cold: SyncReport,
    cold_latency_ms: float,
    cold_signatures: list[dict[str, Any]],
    warm_reports: list[SyncReport],
    warm_latencies: list[float],
    warm_signature_matches: list[bool],
    manifest_cache_entries: int,
) -> dict[str, Any]:
    warm_hits = sum(report.cache_result_hits for report in warm_reports)
    warm_misses = sum(report.cache_result_misses for report in warm_reports)
    warm_total_reads = warm_hits + warm_misses
    warm_hit_rate = warm_hits / warm_total_reads if warm_total_reads else 0.0
    cold_dict = asdict(cold)
    warm_dicts = [asdict(report) for report in warm_reports]
    attempted_field = "table_attempted" if mode == "table" else "ocr_attempted"
    succeeded_field = "table_succeeded" if mode == "table" else "ocr_succeeded"
    return {
        "mode": mode,
        "documents": len(docs),
        "document_names": docs,
        "actual_extractor_used": cold_dict[attempted_field] > 0,
        "cold_report": cold_dict,
        "warm_reports": warm_dicts,
        "cold_optional_units": len(cold_signatures),
        "manifest_cache_entries": manifest_cache_entries,
        "warm_cache_result_hits": warm_hits,
        "warm_cache_result_misses": warm_misses,
        "warm_cache_hit_rate": round(warm_hit_rate, 6),
        "quality_non_regression": all(warm_signature_matches),
        "cold_success_nonzero": cold_dict[succeeded_field] > 0,
        "failures_zero": cold.failed == 0 and all(report.failed == 0 for report in warm_reports),
        "latency_ms": {
            "cold_sync": round(cold_latency_ms, 6),
            "warm_sync_p50": _median(warm_latencies),
            "warm_sync_p95": _p95(warm_latencies),
            "warm_sync_values": [round(value, 6) for value in warm_latencies],
        },
        "cache_effect": {
            "extractor_attempts_skipped_on_warm": all(
                asdict(report)[attempted_field] == 0 for report in warm_reports
            ),
            "warm_hit_rate_is_1": warm_hit_rate == 1.0,
        },
    }


def _optional_signatures(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signatures = []
    for record in records:
        payload = record.get("payload") or {}
        if payload.get("unit_type") not in OPTIONAL_UNIT_TYPES:
            continue
        signatures.append(
            {
                "unit_type": payload.get("unit_type"),
                "relative_path": payload.get("relative_path"),
                "page_no": payload.get("page_no"),
                "image_no": payload.get("image_no"),
                "table_no": payload.get("table_no"),
                "bbox": payload.get("bbox"),
                "extractor_profile": payload.get("extractor_profile"),
                "text_preview": payload.get("text_preview"),
                "has_text_vector": payload.get("has_text_vector"),
            }
        )
    return sorted(
        signatures,
        key=lambda item: (
            str(item["relative_path"]),
            str(item["unit_type"]),
            str(item["page_no"]),
            str(item["image_no"]),
            str(item["table_no"]),
        ),
    )


def _aggregate_decision(modes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mode_values = list(modes.values())
    live_eval_passed = bool(mode_values) and all(
        mode["actual_extractor_used"]
        and mode["failures_zero"]
        and mode["quality_non_regression"]
        and mode["cache_effect"]["warm_hit_rate_is_1"]
        for mode in mode_values
    )
    hold_reasons = []
    if not live_eval_passed:
        hold_reasons.append("live-eval acceptance failed")
    if sum(mode["documents"] for mode in mode_values) < 20:
        hold_reasons.append("live-eval corpus is below public performance claim threshold")
    return {
        "live_eval_passed": live_eval_passed,
        "public_evidence_decision": "hold",
        "public_performance_claim_allowed": False,
        "hold_reasons": hold_reasons
        or ["public promotion requires explicit release-evidence decision"],
    }


def _runtime_summary() -> dict[str, str | bool]:
    return {
        "pdfplumber_available": _module_available("pdfplumber"),
        "tesseract_command": "configured-command",
    }


def _module_available(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def _raw_report_key_findings(value: Any, artifact_name: str) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []
    _collect_raw_report_key_findings(value, artifact_name, findings)
    return findings


def _collect_raw_report_key_findings(
    value: Any,
    artifact_name: str,
    findings: list[ArtifactFinding],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_raw_report_key(str(key)):
                findings.append(
                    ArtifactFinding(
                        artifact_name,
                        "raw report field",
                        f"raw-report-field-{key}",
                    )
                )
            _collect_raw_report_key_findings(item, artifact_name, findings)
    elif isinstance(value, list):
        for item in value:
            _collect_raw_report_key_findings(item, artifact_name, findings)


def _is_raw_report_key(key: str) -> bool:
    normalized = key.lower()
    return (
        normalized in RAW_REPORT_KEYS
        or normalized.startswith("raw_")
        or normalized.endswith("_raw")
        or normalized.endswith("_text")
    )


def _touch_all(source: Path) -> None:
    now = time.time()
    for path in sorted(source.glob("*.pdf")):
        path.touch()
        now += 0.001
        path.touch()


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 6) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95 + 0.999999) - 1))
    return round(ordered[index], 6)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run live pdfplumber/Tesseract extractor read-through cache eval."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--out")
    parser.add_argument("--table-doc", action="append")
    parser.add_argument("--ocr-doc", action="append")
    parser.add_argument("--warm-repeats", type=int, default=3)
    parser.add_argument("--tesseract-cmd", default="tesseract")
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--tesseract-psm", default="6")
    parser.add_argument("--skip-table", action="store_true")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=_default_blocked_terms_file())
    return parser


def _default_blocked_terms_file() -> str | None:
    path = Path(".locallens/publication-terms.txt")
    if path.exists():
        return path.as_posix()
    return None


if __name__ == "__main__":
    raise SystemExit(main())
