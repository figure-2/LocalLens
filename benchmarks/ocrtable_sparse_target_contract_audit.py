from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locallens.core.types import SearchResult
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.search_service import SearchService
from locallens.retrieval.search_service import _query_terms
from locallens.security.artifact_scan import ArtifactFinding
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact

from benchmarks.ocrtable_cache_safety_live_eval import DEFAULT_CACHE_SAFETY_GOLDEN
from benchmarks.ocrtable_cache_safety_live_eval import _cache_safety_queries
from benchmarks.ocrtable_cache_safety_live_eval import _default_blocked_terms_file
from benchmarks.ocrtable_cache_safety_live_eval import _mode_for_unit_type
from benchmarks.ocrtable_cache_safety_live_eval import _raw_report_key_findings
from benchmarks.ocrtable_cache_safety_live_eval import _settings_for_mode
from benchmarks.ocrtable_deep_miss_audit import _audit_query as _deep_miss_audit_query
from benchmarks.ocrtable_deep_miss_audit import _matching_payloads


SCHEMA_VERSION = "ocrtable-sparse-target-contract-audit-v1"
SPARSE_REASON = "target_preview_sparse"
STRICT_RAW_REPORT_KEYS = {
    "absolute_path",
    "blob_path",
    "blob_rel_path",
    "bbox",
    "cache_blob_path",
    "case_id",
    "checksum",
    "chunk_no",
    "corpus_id",
    "document_body",
    "expanded_query",
    "expanded_terms",
    "full_text",
    "golden_artifact",
    "negative_paths",
    "ocr_text",
    "origin",
    "page_no",
    "payload",
    "point_id",
    "private_path",
    "query",
    "query_id",
    "query_set_id",
    "query_terms",
    "query_text",
    "raw_payload",
    "raw_query",
    "reference",
    "relative_path",
    "source",
    "source_path",
    "snippet",
    "table_text",
    "target_document",
    "target_path",
    "text",
    "text_preview",
    "unit_id",
    "manifest_id",
    "doc_name",
    "file_name",
    "filename_tokens",
    "matched_terms",
    "overlap_terms",
    "preview_terms",
}
STRICT_RAW_REPORT_PREFIXES = ("origin_", "reference_", "leg" + "acy_")
STRICT_RAW_REPORT_SUFFIXES = ("_text",)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_sparse_target_contract_audit(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        deep_top_k=args.deep_top_k,
        min_preview_terms=args.min_preview_terms,
        tesseract_cmd=args.tesseract_cmd,
        ocr_lang=args.ocr_lang,
        tesseract_psm=args.tesseract_psm,
        run_table=not args.skip_table,
        run_ocr=not args.skip_ocr,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-sparse-target-contract-audit",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _sparse_report_key_findings(
            report,
            args.out or "ocrtable-sparse-target-contract-audit",
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


def run_sparse_target_contract_audit(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_CACHE_SAFETY_GOLDEN,
    deep_top_k: int = 50,
    min_preview_terms: int = 4,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    tesseract_psm: str = "6",
    run_table: bool = True,
    run_ocr: bool = True,
) -> dict[str, Any]:
    if deep_top_k < 10:
        raise ValueError("deep_top_k must be at least 10")
    if min_preview_terms < 1:
        raise ValueError("min_preview_terms must be positive")
    started = time.perf_counter()
    pdf_dir = pdf_dir.resolve()
    queries = [
        item
        for item in _cache_safety_queries(golden_path)
        if item.get("scenario") == "hard-negative"
    ]
    modes: dict[str, dict[str, Any]] = {}
    if run_table:
        modes["table"] = _run_mode_contract_audit(
            pdf_dir=pdf_dir,
            queries=queries,
            mode="table",
            deep_top_k=deep_top_k,
            min_preview_terms=min_preview_terms,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    if run_ocr:
        modes["ocr"] = _run_mode_contract_audit(
            pdf_dir=pdf_dir,
            queries=queries,
            mode="ocr",
            deep_top_k=deep_top_k,
            min_preview_terms=min_preview_terms,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "execution_scope": "local-live",
        "default_enabled": False,
        "benchmark_only": True,
        "product_runtime_changed": False,
        "product_repair_approved": False,
        "public_quality_claim_allowed": False,
        "query_content_recorded": False,
        "document_body_recorded": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "corpus": {
            "pdf_files": len(list(pdf_dir.glob("*.pdf"))),
            "fixture_artifact_recorded": False,
            "hard_negative_queries": len(queries),
            "deep_top_k": deep_top_k,
            "min_preview_terms": min_preview_terms,
        },
        "audit_contract": {
            "target_text_used_for_query_expansion": False,
            "target_label_used_for_query_expansion": False,
            "query_content_output": False,
            "document_body_output": False,
            "stable_document_identifier_recorded": False,
        },
        "modes": modes,
        "aggregate": _aggregate_modes(modes),
    }


def _run_mode_contract_audit(
    *,
    pdf_dir: Path,
    queries: list[dict[str, Any]],
    mode: str,
    deep_top_k: int,
    min_preview_terms: int,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    docs = sorted(path.name for path in pdf_dir.glob("*.pdf"))
    mode_queries = [
        item
        for item in queries
        if _mode_for_unit_type(
            str(((item.get("relevant") or [{}])[0]).get("unit_type") or "")
        )
        == mode
    ]
    with tempfile.TemporaryDirectory(prefix=f"locallens-{mode}-sparse-contract-") as temp_root:
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
        index_started = time.perf_counter()
        sync_report = sync.sync_folder(source)
        index_ms = (time.perf_counter() - index_started) * 1000
        payloads = [record.get("payload") or {} for record in store.payload_records()]
        search = SearchService(settings, store=store, manifest=manifest)
        details = [
            _audit_sparse_query(
                index,
                item,
                payloads=payloads,
                searcher=lambda query, top_k: search.search(
                    query,
                    top_k=top_k,
                    modality="text",
                ),
                deep_top_k=deep_top_k,
                min_preview_terms=min_preview_terms,
            )
            for index, item in enumerate(mode_queries, start=1)
        ]
        sparse_details = [
            row
            for row in details
            if row["included_in_sparse_target_contract_audit"]
        ]
        manifest_units = manifest.unit_count()
        store_units = store.count()
        store.close()
    return {
        "mode": mode,
        "documents": len(docs),
        "indexed_units": store_units,
        "manifest_units": manifest_units,
        "sync": _sync_summary(sync_report),
        "index_latency_ms": round(index_ms, 6),
        "evaluated_hard_negative_queries": len(details),
        "sparse_target_queries": sparse_details,
        "summary": _summarize_sparse_queries(sparse_details, len(details)),
    }


def _audit_sparse_query(
    ordinal: int,
    item: dict[str, Any],
    *,
    payloads: list[dict[str, Any]],
    searcher: Callable[[str, int], list[SearchResult]],
    deep_top_k: int,
    min_preview_terms: int,
) -> dict[str, Any]:
    relevant = item.get("relevant") or [{}]
    target = relevant[0]
    query = str(item.get("query") or "")
    query_terms = _query_terms(query)
    deep_miss = _deep_miss_audit_query(
        item,
        payloads=payloads,
        searcher=searcher,
        deep_top_k=deep_top_k,
    )
    target_payloads = _matching_payloads(payloads, target)
    target_preview_terms = _payload_preview_terms(target_payloads)
    negative_paths = [str(path) for path in item.get("negative_paths", [])]
    negative_payloads = [
        payload
        for payload in payloads
        if str(payload.get("relative_path") or "") in set(negative_paths)
    ]
    negative_preview_terms = _payload_preview_terms(negative_payloads)
    included = deep_miss["primary_reason"] == SPARSE_REASON
    target_overlap_count = len(query_terms & target_preview_terms)
    negative_overlap_count = len(query_terms & negative_preview_terms)
    preview_term_count = int(deep_miss["target_preview_term_count"])
    target_overlap_ratio = float(deep_miss["target_preview_overlap_ratio"])
    negative_overlap_ratio = float(deep_miss["negative_preview_overlap_ratio"])
    decision = _contract_decision(
        target_payload_count=int(deep_miss["target_payload_count"]),
        target_preview_term_count=preview_term_count,
        target_preview_overlap_ratio=target_overlap_ratio,
        target_filename_overlap_ratio=float(deep_miss["target_filename_overlap_ratio"]),
        negative_preview_overlap_ratio=negative_overlap_ratio,
        negative_filename_overlap_ratio=float(deep_miss["negative_filename_overlap_ratio"]),
        min_preview_terms=min_preview_terms,
    )
    return {
        "case_ordinal": ordinal,
        "mode": _mode_for_unit_type(str(target.get("unit_type") or "")) or "",
        "target_unit_type": str(target.get("unit_type") or ""),
        "included_in_sparse_target_contract_audit": included,
        "deep_miss_classification": deep_miss["classification"],
        "deep_miss_primary_reason": deep_miss["primary_reason"],
        "target_rank_deep_k": deep_miss["target_rank_deep_k"],
        "target_payload_count": deep_miss["target_payload_count"],
        "query_term_count": len(query_terms),
        "target_preview_term_count": preview_term_count,
        "target_preview_unique_term_count": len(target_preview_terms),
        "target_preview_query_overlap_count": target_overlap_count,
        "target_preview_missing_query_term_count": max(
            len(query_terms) - target_overlap_count,
            0,
        ),
        "target_preview_overlap_ratio": target_overlap_ratio,
        "target_filename_overlap_ratio": deep_miss["target_filename_overlap_ratio"],
        "negative_preview_overlap_count": negative_overlap_count,
        "negative_preview_overlap_ratio": negative_overlap_ratio,
        "negative_filename_overlap_ratio": deep_miss["negative_filename_overlap_ratio"],
        "negative_seen_deep_k": deep_miss["negative_seen_deep_k"],
        "preview_density_bucket": _preview_density_bucket(
            preview_term_count,
            min_preview_terms,
        ),
        "preview_query_match_bucket": _overlap_bucket(target_overlap_ratio),
        "negative_dominates_target_preview": negative_overlap_ratio > target_overlap_ratio,
        "negative_dominates_target_filename": (
            float(deep_miss["negative_filename_overlap_ratio"])
            > float(deep_miss["target_filename_overlap_ratio"])
        ),
        "contract_decision": decision,
        "recommended_repair_track": _recommended_repair_track(decision),
        "product_runtime_changed": False,
        "product_repair_approved": False,
    }


def _payload_preview_terms(payloads: list[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for payload in payloads:
        terms.update(_query_terms(str(payload.get("text_preview") or "")))
    return terms


def _contract_decision(
    *,
    target_payload_count: int,
    target_preview_term_count: int,
    target_preview_overlap_ratio: float,
    target_filename_overlap_ratio: float,
    negative_preview_overlap_ratio: float,
    negative_filename_overlap_ratio: float,
    min_preview_terms: int,
) -> str:
    if target_payload_count == 0:
        return "target_payload_missing"
    if target_preview_term_count < min_preview_terms:
        if target_preview_overlap_ratio == 0:
            return "fixture_or_extractor_target_preview_too_sparse"
        return "target_preview_partial_but_below_contract"
    if max(negative_preview_overlap_ratio, negative_filename_overlap_ratio) > max(
        target_preview_overlap_ratio,
        target_filename_overlap_ratio,
    ):
        return "distractor_contract_stronger_than_target"
    return "not_sparse_target_contract_issue"


def _recommended_repair_track(decision: str) -> str:
    if decision == "target_payload_missing":
        return "fixture_target_binding_review"
    if decision in {
        "fixture_or_extractor_target_preview_too_sparse",
        "target_preview_partial_but_below_contract",
    }:
        return "fixture_or_extractor_contract_repair_before_product_change"
    if decision == "distractor_contract_stronger_than_target":
        return "query_contract_or_distractor_contract_review"
    return "hold_product_repair_until_sparse_contract_is_closed"


def _preview_density_bucket(term_count: int, min_preview_terms: int) -> str:
    if term_count == 0:
        return "empty"
    if term_count <= max(1, min_preview_terms // 2):
        return "very_sparse"
    if term_count < min_preview_terms:
        return "sparse"
    return "sufficient"


def _overlap_bucket(ratio: float) -> str:
    if ratio == 0:
        return "none"
    if ratio < 0.25:
        return "low"
    if ratio < 0.5:
        return "medium"
    return "high"


def _summarize_sparse_queries(
    details: list[dict[str, Any]],
    evaluated_queries: int,
) -> dict[str, Any]:
    decisions = Counter(str(row["contract_decision"]) for row in details)
    repair_tracks = Counter(str(row["recommended_repair_track"]) for row in details)
    density = Counter(str(row["preview_density_bucket"]) for row in details)
    match = Counter(str(row["preview_query_match_bucket"]) for row in details)
    missing_terms = [
        int(row["target_preview_missing_query_term_count"])
        for row in details
    ]
    preview_terms = [int(row["target_preview_term_count"]) for row in details]
    target_overlap = [float(row["target_preview_overlap_ratio"]) for row in details]
    negative_overlap = [float(row["negative_preview_overlap_ratio"]) for row in details]
    return {
        "evaluated_queries": evaluated_queries,
        "sparse_target_queries": len(details),
        "sparse_target_rate": _rate(len(details), evaluated_queries),
        "contract_decision_counts": dict(sorted(decisions.items())),
        "recommended_repair_track_counts": dict(sorted(repair_tracks.items())),
        "preview_density_bucket_counts": dict(sorted(density.items())),
        "preview_query_match_bucket_counts": dict(sorted(match.items())),
        "min_target_preview_term_count": min(preview_terms) if preview_terms else 0,
        "max_target_preview_missing_query_term_count": (
            max(missing_terms) if missing_terms else 0
        ),
        "mean_target_preview_overlap_ratio": _mean(target_overlap),
        "mean_negative_preview_overlap_ratio": _mean(negative_overlap),
        "product_repair_approved": False,
        "public_quality_claim_allowed": False,
    }


def _aggregate_modes(modes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summaries = [mode["summary"] for mode in modes.values()]
    evaluated = sum(int(summary["evaluated_queries"]) for summary in summaries)
    sparse_count = sum(int(summary["sparse_target_queries"]) for summary in summaries)
    decisions = Counter()
    tracks = Counter()
    density = Counter()
    match = Counter()
    for summary in summaries:
        decisions.update(summary["contract_decision_counts"])
        tracks.update(summary["recommended_repair_track_counts"])
        density.update(summary["preview_density_bucket_counts"])
        match.update(summary["preview_query_match_bucket_counts"])
    return {
        "evaluated_queries": evaluated,
        "sparse_target_queries": sparse_count,
        "sparse_target_rate": _rate(sparse_count, evaluated),
        "contract_decision_counts": dict(sorted(decisions.items())),
        "recommended_repair_track_counts": dict(sorted(tracks.items())),
        "preview_density_bucket_counts": dict(sorted(density.items())),
        "preview_query_match_bucket_counts": dict(sorted(match.items())),
        "product_runtime_changed": False,
        "product_repair_approved": False,
        "public_quality_claim_allowed": False,
        "ll_corpus_004e2_approval_allowed": sparse_count == 0,
        "recommended_next": _aggregate_recommended_next(sparse_count, decisions),
    }


def _aggregate_recommended_next(
    sparse_count: int,
    decisions: Counter[str],
) -> str:
    if sparse_count == 0:
        return "sparse contract closed; decide whether same-fixture repair POC is warranted"
    if decisions.get("fixture_or_extractor_target_preview_too_sparse", 0):
        return "hold product repair; fix fixture or extractor target preview contract first"
    if decisions.get("target_preview_partial_but_below_contract", 0):
        return "hold product repair; clarify sparse target query contract first"
    return "hold product repair until sparse target case is explicitly accepted or repaired"


def _sync_summary(report) -> dict[str, Any]:
    raw = asdict(report)
    return {
        name: raw[name]
        for name in (
            "added",
            "updated",
            "deleted",
            "skipped",
            "failed",
            "ocr_attempted",
            "ocr_succeeded",
            "ocr_empty",
            "table_attempted",
            "table_succeeded",
            "table_empty",
            "cache_result_hits",
            "cache_result_misses",
            "cache_entries_written",
        )
    }


def _sparse_report_key_findings(
    value: Any,
    artifact_name: str,
) -> list[ArtifactFinding]:
    findings = _raw_report_key_findings(value, artifact_name)
    _collect_sparse_report_key_findings(value, artifact_name, findings)
    return findings


def _collect_sparse_report_key_findings(
    value: Any,
    artifact_name: str,
    findings: list[ArtifactFinding],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_sparse_raw_report_key(str(key)):
                findings.append(
                    ArtifactFinding(
                        artifact_name,
                        "stable or raw report field",
                        f"sparse-report-field-{key}",
                    )
                )
            _collect_sparse_report_key_findings(item, artifact_name, findings)
    elif isinstance(value, list):
        for item in value:
            _collect_sparse_report_key_findings(item, artifact_name, findings)


def _is_sparse_raw_report_key(key: str) -> bool:
    normalized = key.lower()
    return (
        normalized in STRICT_RAW_REPORT_KEYS
        or normalized.startswith("raw_")
        or normalized.startswith(STRICT_RAW_REPORT_PREFIXES)
        or normalized.endswith("_raw")
        or normalized.endswith(STRICT_RAW_REPORT_SUFFIXES)
    )


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit sparse OCR/table target query contracts without raw body output."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=DEFAULT_CACHE_SAFETY_GOLDEN.as_posix())
    parser.add_argument("--out")
    parser.add_argument("--deep-top-k", type=int, default=50)
    parser.add_argument("--min-preview-terms", type=int, default=4)
    parser.add_argument("--tesseract-cmd", default="tesseract")
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--tesseract-psm", default="6")
    parser.add_argument("--skip-table", action="store_true")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=_default_blocked_terms_file())
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
