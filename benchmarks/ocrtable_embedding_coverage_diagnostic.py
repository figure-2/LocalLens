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
from benchmarks.ocrtable_deep_miss_audit import _audit_query as _deep_miss_audit_query
SCHEMA_VERSION = "ocrtable-embedding-coverage-diagnostic-v1"
CANDIDATES = (
    "baseline",
    "normalized_query",
    "unit_intent_expansion",
    "bilingual_alias_expansion",
    "combined_query_family_expansion",
)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_embedding_coverage_diagnostic(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        top_k=args.top_k,
        deep_top_k=args.deep_top_k,
        max_extra_terms=args.max_extra_terms,
        tesseract_cmd=args.tesseract_cmd,
        ocr_lang=args.ocr_lang,
        tesseract_psm=args.tesseract_psm,
        run_table=not args.skip_table,
        run_ocr=not args.skip_ocr,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-embedding-coverage-diagnostic",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-embedding-coverage-diagnostic",
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


def run_embedding_coverage_diagnostic(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_CACHE_SAFETY_GOLDEN,
    top_k: int = 10,
    deep_top_k: int = 50,
    max_extra_terms: int = 8,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    tesseract_psm: str = "6",
    run_table: bool = True,
    run_ocr: bool = True,
) -> dict[str, Any]:
    if deep_top_k < top_k:
        raise ValueError("deep_top_k must be greater than or equal to top_k")
    if max_extra_terms < 0:
        raise ValueError("max_extra_terms must be non-negative")
    started = time.perf_counter()
    pdf_dir = pdf_dir.resolve()
    queries = [
        item
        for item in _cache_safety_queries(golden_path)
        if item.get("scenario") == "hard-negative"
    ]
    modes: dict[str, dict[str, Any]] = {}
    if run_table:
        modes["table"] = _run_mode_diagnostic(
            pdf_dir=pdf_dir,
            queries=queries,
            mode="table",
            top_k=top_k,
            deep_top_k=deep_top_k,
            max_extra_terms=max_extra_terms,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    if run_ocr:
        modes["ocr"] = _run_mode_diagnostic(
            pdf_dir=pdf_dir,
            queries=queries,
            mode="ocr",
            top_k=top_k,
            deep_top_k=deep_top_k,
            max_extra_terms=max_extra_terms,
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
        "product_repair_approved": False,
        "query_content_recorded": False,
        "document_body_recorded": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "corpus": {
            "pdf_files": len(list(pdf_dir.glob("*.pdf"))),
            "golden_artifact_recorded": False,
            "hard_negative_queries": len(queries),
            "top_k": top_k,
            "deep_top_k": deep_top_k,
            "max_extra_terms": max_extra_terms,
        },
        "diagnostic_candidates": list(CANDIDATES),
        "candidate_contracts": _candidate_contracts(),
        "modes": modes,
        "aggregate": _aggregate_modes(modes),
    }


def _run_mode_diagnostic(
    *,
    pdf_dir: Path,
    queries: list[dict[str, Any]],
    mode: str,
    top_k: int,
    deep_top_k: int,
    max_extra_terms: int,
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
    with tempfile.TemporaryDirectory(prefix=f"locallens-{mode}-coverage-diagnostic-") as temp_root:
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
            _diagnose_query(
                index,
                item,
                payloads=payloads,
                searcher=lambda query, k: search.search(
                    query,
                    top_k=k,
                    modality="text",
                ),
                top_k=top_k,
                deep_top_k=deep_top_k,
                max_extra_terms=max_extra_terms,
            )
            for index, item in enumerate(mode_queries, start=1)
        ]
        target_details = [
            row
            for row in details
            if row["included_in_coverage_diagnostic"]
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
        "coverage_queries": target_details,
        "summary": _summarize_queries(target_details),
    }


def _diagnose_query(
    ordinal: int,
    item: dict[str, Any],
    *,
    payloads: list[dict[str, Any]],
    searcher: Callable[[str, int], list[SearchResult]],
    top_k: int,
    deep_top_k: int,
    max_extra_terms: int,
) -> dict[str, Any]:
    relevant = item.get("relevant") or [{}]
    target = relevant[0]
    deep_miss = _deep_miss_audit_query(
        item,
        payloads=payloads,
        searcher=searcher,
        deep_top_k=deep_top_k,
    )
    included = (
        deep_miss["target_rank_deep_k"] == 0
        and deep_miss["classification"] == "embedding_coverage"
    )
    candidate_rows = {
        candidate: _evaluate_expansion_candidate(
            candidate,
            item,
            target=target,
            searcher=searcher,
            top_k=top_k,
            deep_top_k=deep_top_k,
            max_extra_terms=max_extra_terms,
        )
        for candidate in CANDIDATES
    }
    return {
        "case_ordinal": ordinal,
        "mode": _mode_for_unit_type(str(target.get("unit_type") or "")) or "",
        "target_unit_type": str(target.get("unit_type") or ""),
        "included_in_coverage_diagnostic": included,
        "deep_miss_classification": deep_miss["classification"],
        "deep_miss_primary_reason": deep_miss["primary_reason"],
        "target_preview_term_count": deep_miss["target_preview_term_count"],
        "target_preview_overlap_ratio": deep_miss["target_preview_overlap_ratio"],
        "negative_preview_overlap_ratio": deep_miss["negative_preview_overlap_ratio"],
        "candidates": candidate_rows,
        "best_candidate": _best_candidate(candidate_rows),
    }


def _evaluate_expansion_candidate(
    candidate: str,
    item: dict[str, Any],
    *,
    target: dict[str, Any],
    searcher: Callable[[str, int], list[SearchResult]],
    top_k: int,
    deep_top_k: int,
    max_extra_terms: int,
) -> dict[str, Any]:
    query = str(item.get("query") or "")
    expanded_query, added_terms = _expanded_query(
        candidate,
        query,
        max_extra_terms=max_extra_terms,
    )
    results = searcher(expanded_query, deep_top_k)
    item_top_k = int(item.get("top_k") or top_k)
    max_rank = int(target.get("max_rank") or item_top_k)
    negative_paths = [str(path) for path in item.get("negative_paths", [])]
    target_rank_top = _target_rank(results[:item_top_k], target)
    target_rank_deep = _target_rank(results, target)
    negative_top_ranks = _negative_ranks(results[:item_top_k], negative_paths)
    negative_deep_ranks = _negative_ranks(results, negative_paths)
    negative_before_target = (
        sum(1 for rank in negative_top_ranks if rank < target_rank_top)
        if target_rank_top
        else len(negative_top_ranks)
    )
    passed = (
        target_rank_top > 0
        and target_rank_top <= max_rank
        and negative_before_target == 0
        and not (negative_top_ranks and min(negative_top_ranks) == 1)
    )
    return {
        "candidate": candidate,
        "query_term_count": len(_query_terms(expanded_query)),
        "added_term_count": len(added_terms),
        "label_aware": False,
        "product_runtime_eligible": False,
        "target_rank_top_k": target_rank_top,
        "target_rank_deep_k": target_rank_deep,
        "target_max_rank": max_rank,
        "target_hit_top_k": target_rank_top > 0,
        "target_hit_deep_k": target_rank_deep > 0,
        "negative_best_rank_top_k": min(negative_top_ranks) if negative_top_ranks else 0,
        "negative_best_rank_deep_k": min(negative_deep_ranks) if negative_deep_ranks else 0,
        "negative_before_target_count": negative_before_target,
        "negative_top1": bool(negative_top_ranks and min(negative_top_ranks) == 1),
        "passed": passed,
    }


def _expanded_query(
    candidate: str,
    query: str,
    *,
    max_extra_terms: int,
) -> tuple[str, list[str]]:
    if candidate == "baseline":
        return query, []
    query_terms = _query_terms(query)
    if candidate == "normalized_query":
        return _normalized_query(query), []
    if max_extra_terms == 0:
        return query, []
    if candidate == "unit_intent_expansion":
        base_query = query
        extra_terms = _unit_intent_terms(query_terms)
    elif candidate == "bilingual_alias_expansion":
        base_query = query
        extra_terms = _bilingual_alias_terms(query_terms)
    elif candidate == "combined_query_family_expansion":
        base_query = _normalized_query(query)
        base_terms = _query_terms(base_query)
        extra_terms = _unit_intent_terms(base_terms) + _bilingual_alias_terms(base_terms)
    else:
        raise ValueError(f"unsupported diagnostic candidate: {candidate}")
    base_terms = _query_terms(base_query)
    additions = [
        term
        for term in extra_terms
        if term not in base_terms and not _looks_like_noise_term(term)
    ][:max_extra_terms]
    if not additions:
        return base_query, []
    return f"{base_query} {' '.join(additions)}", additions


def _normalized_query(query: str) -> str:
    normalized = " ".join(sorted(_query_terms(query)))
    return normalized or query


def _unit_intent_terms(query_terms: set[str]) -> list[str]:
    additions: list[str] = []
    if query_terms & {
        "table",
        "row",
        "rows",
        "column",
        "columns",
        "cell",
        "cells",
        "metric",
        "score",
        "count",
        "p50",
        "p95",
        "p99",
    }:
        additions.extend(["table", "row", "column", "cell", "metric", "status"])
    if query_terms & {
        "receipt",
        "invoice",
        "label",
        "notice",
        "permit",
        "card",
        "asset",
        "shipping",
        "badge",
        "ticket",
        "scan",
        "scanned",
        "rotated",
        "contrast",
        "dense",
        "grid",
    }:
        additions.extend(["ocr", "scan", "image", "document", "amount", "asset"])
    if query_terms & {"approved", "approval", "hold", "paid"}:
        additions.extend(["status", "approved", "review"])
    return _unique_terms(additions)


def _bilingual_alias_terms(query_terms: set[str]) -> list[str]:
    aliases = {
        "로컬": ["local"],
        "검색": ["search"],
        "승인": ["approval", "approved"],
        "문서": ["document"],
        "보관함": ["archive"],
        "이십칠": ["27"],
        "배송": ["shipping"],
        "라벨": ["label"],
        "영수증": ["receipt"],
        "청구서": ["invoice"],
        "표": ["table"],
        "행": ["row"],
        "열": ["column"],
        "금액": ["amount"],
        "상태": ["status"],
        "회전": ["rotated"],
        "스캔": ["scan"],
        "local": ["로컬"],
        "search": ["검색"],
        "approval": ["승인"],
        "approved": ["승인"],
        "document": ["문서"],
        "receipt": ["영수증"],
        "invoice": ["청구서"],
        "table": ["표"],
        "amount": ["금액"],
        "status": ["상태"],
    }
    additions: list[str] = []
    for term in sorted(query_terms):
        additions.extend(aliases.get(term, []))
    return _unique_terms(additions)


def _ordered_terms(value: str) -> list[str]:
    return sorted(_query_terms(value))


def _unique_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _looks_like_noise_term(term: str) -> bool:
    return term in {
        "pdf",
        "text",
        "domain",
        "task",
        "topic",
        "scenario",
        "claim",
        "class",
        "safety",
        "hard",
        "negative",
        "cache",
    }


def _best_candidate(candidates: dict[str, dict[str, Any]]) -> str:
    best_name = "baseline"
    best_tuple = _candidate_sort_tuple(candidates["baseline"])
    for name, row in candidates.items():
        row_tuple = _candidate_sort_tuple(row)
        if row_tuple > best_tuple:
            best_name = name
            best_tuple = row_tuple
    return best_name


def _candidate_sort_tuple(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
    return (
        int(row["passed"]),
        int(row["target_hit_top_k"]),
        int(row["target_hit_deep_k"]),
        -int(row["negative_top1"]),
        -int(row["negative_before_target_count"]),
    )


def _summarize_queries(details: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        candidate: _summarize_candidate(details, candidate)
        for candidate in CANDIDATES
    }


def _summarize_candidate(
    details: list[dict[str, Any]],
    candidate: str,
) -> dict[str, Any]:
    rows = [item["candidates"][candidate] for item in details]
    evaluated = len(rows)
    target_hit_top = sum(1 for row in rows if row["target_hit_top_k"])
    target_hit_deep = sum(1 for row in rows if row["target_hit_deep_k"])
    passed = sum(1 for row in rows if row["passed"])
    negative_top1 = sum(1 for row in rows if row["negative_top1"])
    negative_before = sum(int(row["negative_before_target_count"]) for row in rows)
    added_terms = sum(int(row["added_term_count"]) for row in rows)
    return {
        "evaluated_queries": evaluated,
        "target_hit_top_k_count": target_hit_top,
        "target_hit_top_k_rate": _rate(target_hit_top, evaluated),
        "target_hit_deep_k_count": target_hit_deep,
        "target_hit_deep_k_rate": _rate(target_hit_deep, evaluated),
        "deep_miss_remaining_count": evaluated - target_hit_deep,
        "passed_queries": passed,
        "pass_rate": _rate(passed, evaluated),
        "negative_top1_count": negative_top1,
        "negative_before_target_count": negative_before,
        "total_added_terms": added_terms,
    }


def _aggregate_modes(modes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidate_summaries = {}
    for candidate in CANDIDATES:
        summaries = [mode["summary"][candidate] for mode in modes.values()]
        candidate_summaries[candidate] = _merge_summaries(summaries)
    baseline = candidate_summaries["baseline"]
    best_name = _best_aggregate_candidate(candidate_summaries)
    best_deep_name = _best_deep_recovery_candidate(candidate_summaries)
    best = candidate_summaries[best_name]
    best_deep = candidate_summaries[best_deep_name]
    classifications = Counter()
    reasons = Counter()
    for mode in modes.values():
        for row in mode["coverage_queries"]:
            classifications.update([row["deep_miss_classification"]])
            reasons.update([row["deep_miss_primary_reason"]])
    return {
        "evaluated_embedding_coverage_queries": baseline["evaluated_queries"],
        "classification_counts": dict(sorted(classifications.items())),
        "primary_reason_counts": dict(sorted(reasons.items())),
        "candidate_summaries": candidate_summaries,
        "best_candidate": best_name,
        "best_deep_recovery_candidate": best_deep_name,
        "deep_miss_reduction_from_baseline": (
            baseline["deep_miss_remaining_count"] - best["deep_miss_remaining_count"]
        ),
        "max_deep_miss_reduction_from_baseline": (
            baseline["deep_miss_remaining_count"] - best_deep["deep_miss_remaining_count"]
        ),
        "target_hit_deep_k_delta": round(
            best["target_hit_deep_k_rate"] - baseline["target_hit_deep_k_rate"],
            6,
        ),
        "max_target_hit_deep_k_delta": round(
            best_deep["target_hit_deep_k_rate"] - baseline["target_hit_deep_k_rate"],
            6,
        ),
        "negative_top1_regressed": best["negative_top1_count"]
        > baseline["negative_top1_count"],
        "product_runtime_changed": False,
        "product_repair_approved": False,
        "public_quality_claim_allowed": False,
        "recommended_next": _recommended_next(best_name, baseline, best),
    }


def _merge_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = sum(row["evaluated_queries"] for row in summaries)
    target_hit_top = sum(row["target_hit_top_k_count"] for row in summaries)
    target_hit_deep = sum(row["target_hit_deep_k_count"] for row in summaries)
    passed = sum(row["passed_queries"] for row in summaries)
    negative_top1 = sum(row["negative_top1_count"] for row in summaries)
    negative_before = sum(row["negative_before_target_count"] for row in summaries)
    added_terms = sum(row["total_added_terms"] for row in summaries)
    return {
        "evaluated_queries": evaluated,
        "target_hit_top_k_count": target_hit_top,
        "target_hit_top_k_rate": _rate(target_hit_top, evaluated),
        "target_hit_deep_k_count": target_hit_deep,
        "target_hit_deep_k_rate": _rate(target_hit_deep, evaluated),
        "deep_miss_remaining_count": evaluated - target_hit_deep,
        "passed_queries": passed,
        "pass_rate": _rate(passed, evaluated),
        "negative_top1_count": negative_top1,
        "negative_before_target_count": negative_before,
        "total_added_terms": added_terms,
    }


def _best_aggregate_candidate(summaries: dict[str, dict[str, Any]]) -> str:
    best_name = "baseline"
    best_tuple = _summary_sort_tuple(summaries["baseline"])
    for name, row in summaries.items():
        row_tuple = _summary_sort_tuple(row)
        if row_tuple > best_tuple:
            best_name = name
            best_tuple = row_tuple
    return best_name


def _best_deep_recovery_candidate(summaries: dict[str, dict[str, Any]]) -> str:
    best_name = "baseline"
    best_tuple = _deep_recovery_sort_tuple(summaries["baseline"])
    for name, row in summaries.items():
        row_tuple = _deep_recovery_sort_tuple(row)
        if row_tuple > best_tuple:
            best_name = name
            best_tuple = row_tuple
    return best_name


def _summary_sort_tuple(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
    return (
        int(row["passed_queries"]),
        int(row["target_hit_top_k_count"]),
        int(row["target_hit_deep_k_count"]),
        -int(row["negative_top1_count"]),
        -int(row["negative_before_target_count"]),
    )


def _deep_recovery_sort_tuple(row: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(row["target_hit_deep_k_count"]),
        int(row["target_hit_top_k_count"]),
        -int(row["negative_top1_count"]),
        -int(row["negative_before_target_count"]),
    )


def _recommended_next(best_name: str, baseline: dict[str, Any], best: dict[str, Any]) -> str:
    if best["target_hit_deep_k_count"] <= baseline["target_hit_deep_k_count"]:
        return "hold product repair; embedding profile or extractor contract needs deeper audit"
    return "global query-family candidate improved coverage; require explicit approval before same-fixture POC"


def _candidate_contracts() -> dict[str, dict[str, Any]]:
    return {
        "baseline": {
            "uses_original_query_only": True,
            "uses_target_label": False,
            "uses_target_content_signal": False,
            "product_runtime_eligible": False,
        },
        "normalized_query": {
            "uses_original_query_only": False,
            "uses_target_label": False,
            "uses_target_content_signal": False,
            "product_runtime_eligible": False,
        },
        "unit_intent_expansion": {
            "uses_original_query_only": False,
            "uses_target_label": False,
            "uses_target_content_signal": False,
            "product_runtime_eligible": False,
        },
        "bilingual_alias_expansion": {
            "uses_original_query_only": False,
            "uses_target_label": False,
            "uses_target_content_signal": False,
            "product_runtime_eligible": False,
        },
        "combined_query_family_expansion": {
            "uses_original_query_only": False,
            "uses_target_label": False,
            "uses_target_content_signal": False,
            "product_runtime_eligible": False,
        },
    }


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
        description="Run benchmark-only OCR/table embedding coverage diagnostics."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=DEFAULT_CACHE_SAFETY_GOLDEN.as_posix())
    parser.add_argument("--out")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--deep-top-k", type=int, default=50)
    parser.add_argument("--max-extra-terms", type=int, default=8)
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
