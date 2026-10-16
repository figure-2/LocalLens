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
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact

from benchmarks.ocrtable_cache_safety_live_eval import DEFAULT_CACHE_SAFETY_GOLDEN
from benchmarks.ocrtable_cache_safety_live_eval import _cache_safety_queries
from benchmarks.ocrtable_cache_safety_live_eval import _default_blocked_terms_file
from benchmarks.ocrtable_cache_safety_live_eval import _mode_for_unit_type
from benchmarks.ocrtable_cache_safety_live_eval import _negative_ranks
from benchmarks.ocrtable_cache_safety_live_eval import _raw_report_key_findings
from benchmarks.ocrtable_cache_safety_live_eval import _settings_for_mode
from benchmarks.ocrtable_cache_safety_live_eval import _target_rank


SCHEMA_VERSION = "ocrtable-deep-miss-audit-v1"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_deep_miss_audit(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        deep_top_k=args.deep_top_k,
        tesseract_cmd=args.tesseract_cmd,
        ocr_lang=args.ocr_lang,
        tesseract_psm=args.tesseract_psm,
        run_table=not args.skip_table,
        run_ocr=not args.skip_ocr,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-deep-miss-audit",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(report, args.out or "ocrtable-deep-miss-audit")
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


def run_deep_miss_audit(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_CACHE_SAFETY_GOLDEN,
    deep_top_k: int = 50,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    tesseract_psm: str = "6",
    run_table: bool = True,
    run_ocr: bool = True,
) -> dict[str, Any]:
    if deep_top_k < 10:
        raise ValueError("deep_top_k must be at least 10")
    started = time.perf_counter()
    pdf_dir = pdf_dir.resolve()
    queries = [
        item
        for item in _cache_safety_queries(golden_path)
        if item.get("scenario") == "hard-negative"
    ]
    modes: dict[str, dict[str, Any]] = {}
    if run_table:
        modes["table"] = _run_mode_deep_miss_audit(
            pdf_dir=pdf_dir,
            queries=queries,
            mode="table",
            deep_top_k=deep_top_k,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    if run_ocr:
        modes["ocr"] = _run_mode_deep_miss_audit(
            pdf_dir=pdf_dir,
            queries=queries,
            mode="ocr",
            deep_top_k=deep_top_k,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "local-live",
        "default_enabled": False,
        "benchmark_only": True,
        "product_runtime_changed": False,
        "query_content_recorded": False,
        "document_body_recorded": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "corpus": {
            "pdf_files": len(list(pdf_dir.glob("*.pdf"))),
            "golden_artifact": golden_path.name,
            "hard_negative_queries": len(queries),
            "deep_top_k": deep_top_k,
        },
        "modes": modes,
        "aggregate": _aggregate_modes(modes),
    }


def _run_mode_deep_miss_audit(
    *,
    pdf_dir: Path,
    queries: list[dict[str, Any]],
    mode: str,
    deep_top_k: int,
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
    with tempfile.TemporaryDirectory(prefix=f"locallens-{mode}-deep-miss-audit-") as temp_root:
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
        all_details = [
            _audit_query(
                item,
                payloads=payloads,
                searcher=lambda query, top_k: search.search(
                    query,
                    top_k=top_k,
                    modality="text",
                ),
                deep_top_k=deep_top_k,
            )
            for item in mode_queries
        ]
        deep_misses = [row for row in all_details if row["target_rank_deep_k"] == 0]
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
        "evaluated_queries": len(all_details),
        "deep_miss_queries": deep_misses,
        "summary": _summarize_deep_misses(deep_misses, len(all_details)),
    }


def _audit_query(
    item: dict[str, Any],
    *,
    payloads: list[dict[str, Any]],
    searcher: Callable[[str, int], list[SearchResult]],
    deep_top_k: int,
) -> dict[str, Any]:
    relevant = item.get("relevant") or [{}]
    target = relevant[0]
    query = str(item.get("query") or "")
    results = searcher(query, deep_top_k)
    query_terms = _query_terms(query)
    negative_paths = [str(path) for path in item.get("negative_paths", [])]
    target_payloads = _matching_payloads(payloads, target)
    negative_payloads = [
        payload
        for payload in payloads
        if str(payload.get("relative_path") or "") in set(negative_paths)
    ]
    target_rank = _target_rank(results, target)
    negative_ranks = _negative_ranks(results, negative_paths)
    target_overlap = _payload_overlap(query_terms, target_payloads)
    negative_overlap = _payload_overlap(query_terms, negative_payloads)
    target_filename_overlap = _filename_overlap(
        query_terms,
        str(target.get("relative_path") or ""),
    )
    negative_filename_overlap = max(
        (_filename_overlap(query_terms, path) for path in negative_paths),
        default=0.0,
    )
    classification = _classify_deep_miss(
        target_rank=target_rank,
        target_payload_count=len(target_payloads),
        target_preview_term_count=_max_preview_term_count(target_payloads),
        target_payload_overlap=target_overlap,
        target_filename_overlap=target_filename_overlap,
        negative_payload_overlap=negative_overlap,
        negative_filename_overlap=negative_filename_overlap,
        negative_ranks=negative_ranks,
    )
    return {
        "query_id": str(item.get("query_id") or item.get("id") or ""),
        "mode": _mode_for_unit_type(str(target.get("unit_type") or "")) or "",
        "target_document": str(target.get("relative_path") or ""),
        "target_unit_type": str(target.get("unit_type") or ""),
        "target_rank_deep_k": target_rank,
        "target_payload_count": len(target_payloads),
        "target_preview_term_count": _max_preview_term_count(target_payloads),
        "query_term_count": len(query_terms),
        "target_filename_overlap_ratio": target_filename_overlap,
        "target_preview_overlap_ratio": target_overlap,
        "negative_filename_overlap_ratio": negative_filename_overlap,
        "negative_preview_overlap_ratio": negative_overlap,
        "negative_best_rank_deep_k": min(negative_ranks) if negative_ranks else 0,
        "negative_seen_deep_k": bool(negative_ranks),
        "classification": classification["classification"],
        "primary_reason": classification["primary_reason"],
        "recommended_repair_track": classification["recommended_repair_track"],
    }


def _matching_payloads(
    payloads: list[dict[str, Any]],
    target: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        payload
        for payload in payloads
        if payload.get("relative_path") == target.get("relative_path")
        and payload.get("unit_type") == target.get("unit_type")
        and _target_payload_fields_match(payload, target)
    ]


def _target_payload_fields_match(
    payload: dict[str, Any],
    target: dict[str, Any],
) -> bool:
    for key in ("page_no", "image_no", "table_no"):
        expected = target.get(key)
        if expected is not None and str(payload.get(key)) != str(expected):
            return False
    return True


def _payload_overlap(query_terms: set[str], payloads: list[dict[str, Any]]) -> float:
    if not payloads:
        return 0.0
    return max(
        _overlap_ratio(query_terms, _query_terms(str(payload.get("text_preview") or "")))
        for payload in payloads
    )


def _filename_overlap(query_terms: set[str], relative_path: str) -> float:
    return _overlap_ratio(
        query_terms,
        _query_terms(relative_path.replace("_", " ").replace("-", " ")),
    )


def _max_preview_term_count(payloads: list[dict[str, Any]]) -> int:
    return max(
        (len(_query_terms(str(payload.get("text_preview") or ""))) for payload in payloads),
        default=0,
    )


def _overlap_ratio(query_terms: set[str], candidate_terms: set[str]) -> float:
    if not query_terms or not candidate_terms:
        return 0.0
    return round(len(query_terms & candidate_terms) / len(query_terms), 6)


def _classify_deep_miss(
    *,
    target_rank: int,
    target_payload_count: int,
    target_preview_term_count: int,
    target_payload_overlap: float,
    target_filename_overlap: float,
    negative_payload_overlap: float,
    negative_filename_overlap: float,
    negative_ranks: list[int],
) -> dict[str, str]:
    if target_rank > 0:
        return {
            "classification": "not_deep_miss",
            "primary_reason": "target_found_in_deep_k",
            "recommended_repair_track": "none",
        }
    if target_payload_count == 0:
        return {
            "classification": "query_contract",
            "primary_reason": "target_payload_missing",
            "recommended_repair_track": "fixture_target_contract_review",
        }
    if target_preview_term_count < 4:
        return {
            "classification": "query_contract",
            "primary_reason": "target_preview_sparse",
            "recommended_repair_track": "target_content_or_extractor_contract_review",
        }
    target_best = max(target_payload_overlap, target_filename_overlap)
    negative_best = max(negative_payload_overlap, negative_filename_overlap)
    if target_best >= 0.5 and negative_best < target_best:
        return {
            "classification": "embedding_coverage",
            "primary_reason": "target_lexically_strong_but_vector_missed",
            "recommended_repair_track": "embedding_profile_or_query_embedding_audit",
        }
    if negative_best > target_best:
        return {
            "classification": "query_contract",
            "primary_reason": "negative_lexical_signal_stronger",
            "recommended_repair_track": "query_contract_or_distractor_contract_review",
        }
    if negative_ranks:
        return {
            "classification": "mixed",
            "primary_reason": "negative_present_and_target_missing",
            "recommended_repair_track": "query_contract_plus_benchmark_ranking_diagnostic",
        }
    return {
        "classification": "embedding_coverage",
        "primary_reason": "target_and_negative_absent_from_deep_k",
        "recommended_repair_track": "embedding_coverage_or_query_expansion_audit",
    }


def _summarize_deep_misses(
    details: list[dict[str, Any]],
    evaluated_queries: int,
) -> dict[str, Any]:
    classification_counts = Counter(str(row["classification"]) for row in details)
    reason_counts = Counter(str(row["primary_reason"]) for row in details)
    track_counts = Counter(str(row["recommended_repair_track"]) for row in details)
    negative_seen = sum(1 for row in details if row["negative_seen_deep_k"])
    return {
        "evaluated_queries": evaluated_queries,
        "deep_miss_count": len(details),
        "deep_miss_rate": _rate(len(details), evaluated_queries),
        "negative_seen_deep_k_count": negative_seen,
        "classification_counts": dict(sorted(classification_counts.items())),
        "primary_reason_counts": dict(sorted(reason_counts.items())),
        "recommended_repair_track_counts": dict(sorted(track_counts.items())),
    }


def _aggregate_modes(modes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summaries = [mode["summary"] for mode in modes.values()]
    evaluated = sum(summary["evaluated_queries"] for summary in summaries)
    deep_misses = sum(summary["deep_miss_count"] for summary in summaries)
    negative_seen = sum(summary["negative_seen_deep_k_count"] for summary in summaries)
    classifications = Counter()
    reasons = Counter()
    tracks = Counter()
    for summary in summaries:
        classifications.update(summary["classification_counts"])
        reasons.update(summary["primary_reason_counts"])
        tracks.update(summary["recommended_repair_track_counts"])
    return {
        "evaluated_queries": evaluated,
        "deep_miss_count": deep_misses,
        "deep_miss_rate": _rate(deep_misses, evaluated),
        "negative_seen_deep_k_count": negative_seen,
        "classification_counts": dict(sorted(classifications.items())),
        "primary_reason_counts": dict(sorted(reasons.items())),
        "recommended_repair_track_counts": dict(sorted(tracks.items())),
        "product_repair_approved": False,
        "public_quality_claim_allowed": False,
        "recommended_next": _recommended_next(classifications),
    }


def _recommended_next(classifications: Counter[str]) -> str:
    if classifications.get("embedding_coverage", 0):
        return "audit embedding/query embedding coverage before product rerank"
    if classifications.get("query_contract", 0):
        return "repair query contract before rerank POC"
    if classifications.get("mixed", 0):
        return "separate query contract and ranking diagnostics before product change"
    return "hold product repair until explicit approval"


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


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit OCR/table hard-negative deep misses without raw query output."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=DEFAULT_CACHE_SAFETY_GOLDEN.as_posix())
    parser.add_argument("--out")
    parser.add_argument("--deep-top-k", type=int, default=50)
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
