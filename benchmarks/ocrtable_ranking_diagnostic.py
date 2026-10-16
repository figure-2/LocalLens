from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict
from dataclasses import replace
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


SCHEMA_VERSION = "ocrtable-ranking-diagnostic-v1"
DIAGNOSTIC_CANDIDATES = (
    "baseline",
    "unit_intent",
    "filename_overlap",
    "snippet_overlap",
    "combined_product_available",
)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_ranking_diagnostic(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        top_k=args.top_k,
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
        args.out or "ocrtable-ranking-diagnostic",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(report, args.out or "ocrtable-ranking-diagnostic")
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


def run_ranking_diagnostic(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_CACHE_SAFETY_GOLDEN,
    top_k: int = 10,
    deep_top_k: int = 50,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    tesseract_psm: str = "6",
    run_table: bool = True,
    run_ocr: bool = True,
) -> dict[str, Any]:
    if deep_top_k < top_k:
        raise ValueError("deep_top_k must be greater than or equal to top_k")
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
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    aggregate = _aggregate_modes(modes)
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
            "top_k": top_k,
            "deep_top_k": deep_top_k,
        },
        "diagnostic_candidates": list(DIAGNOSTIC_CANDIDATES),
        "modes": modes,
        "aggregate": aggregate,
    }


def _run_mode_diagnostic(
    *,
    pdf_dir: Path,
    queries: list[dict[str, Any]],
    mode: str,
    top_k: int,
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
    with tempfile.TemporaryDirectory(prefix=f"locallens-{mode}-ranking-diagnostic-") as temp_root:
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
        search = SearchService(settings, store=store, manifest=manifest)
        details = [
            _diagnose_query(
                item,
                mode=mode,
                top_k=top_k,
                deep_top_k=deep_top_k,
                searcher=lambda query, k: search.search(
                    query,
                    top_k=k,
                    modality="text",
                ),
            )
            for item in mode_queries
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
        "queries": details,
        "summary": _summarize_queries(details),
    }


def _diagnose_query(
    item: dict[str, Any],
    *,
    mode: str,
    top_k: int,
    deep_top_k: int,
    searcher: Callable[[str, int], list[SearchResult]],
) -> dict[str, Any]:
    relevant = item.get("relevant") or [{}]
    target = relevant[0]
    item_top_k = int(item.get("top_k") or top_k)
    max_rank = int(target.get("max_rank") or item_top_k)
    query = str(item.get("query") or "")
    baseline_results = searcher(query, item_top_k)
    deep_results = searcher(query, deep_top_k)
    baseline = _evaluate_candidate(
        baseline_results,
        target=target,
        negative_paths=item.get("negative_paths", []),
        top_k=item_top_k,
        max_rank=max_rank,
        deep_results=deep_results,
    )
    candidate_results = {"baseline": baseline}
    candidate_results.update(
        {
            name: _evaluate_candidate(
                _rerank_candidate(name, query, deep_results),
                target=target,
                negative_paths=item.get("negative_paths", []),
                top_k=item_top_k,
                max_rank=max_rank,
            )
            for name in DIAGNOSTIC_CANDIDATES
            if name != "baseline"
        }
    )
    features = _contract_features(
        query=query,
        target=target,
        results=deep_results,
        negative_paths=item.get("negative_paths", []),
    )
    return {
        "query_id": str(item.get("query_id") or item.get("id") or ""),
        "mode": mode,
        "target_document": str(target.get("relative_path") or ""),
        "target_unit_type": str(target.get("unit_type") or ""),
        "query_top_k": item_top_k,
        "query_term_count": features["query_term_count"],
        "baseline_failure_bucket": _failure_bucket_from_result(baseline),
        "baseline": baseline,
        "contract_features": features,
        "candidates": candidate_results,
        "best_candidate": _best_candidate(candidate_results, baseline),
    }


def _evaluate_candidate(
    results: list[SearchResult],
    *,
    target: dict[str, Any],
    negative_paths: list[str],
    top_k: int,
    max_rank: int,
    deep_results: list[SearchResult] | None = None,
) -> dict[str, Any]:
    top_results = results[:top_k]
    target_rank_top_k = _target_rank(top_results, target)
    target_rank_deep = _target_rank(deep_results or results, target)
    negative_ranks = _negative_ranks(top_results, negative_paths)
    negative_before_target = (
        sum(1 for rank in negative_ranks if rank < target_rank_top_k)
        if target_rank_top_k
        else len(negative_ranks)
    )
    passed = (
        target_rank_top_k > 0
        and target_rank_top_k <= max_rank
        and not negative_before_target
        and not (negative_ranks and min(negative_ranks) == 1)
    )
    return {
        "target_rank_top_k": target_rank_top_k,
        "target_rank_deep_k": target_rank_deep,
        "target_max_rank": max_rank,
        "negative_best_rank_top_k": min(negative_ranks) if negative_ranks else 0,
        "negative_before_target_count": negative_before_target,
        "negative_top1": bool(negative_ranks and min(negative_ranks) == 1),
        "passed": passed,
    }


def _rerank_candidate(
    candidate: str,
    query: str,
    results: list[SearchResult],
) -> list[SearchResult]:
    if candidate == "baseline":
        return list(results)
    query_terms = _query_terms(query)
    reranked: list[SearchResult] = []
    for result in results:
        boost = 0.0
        if candidate in {"unit_intent", "combined_product_available"}:
            boost += _unit_intent_boost(query_terms, result)
        if candidate in {"filename_overlap", "combined_product_available"}:
            boost += _overlap_ratio(
                query_terms,
                _query_terms(result.relative_path.replace("_", " ").replace("-", " ")),
            ) * 0.14
        if candidate in {"snippet_overlap", "combined_product_available"}:
            boost += _overlap_ratio(query_terms, _query_terms(result.snippet)) * 0.10
        reranked.append(replace(result, score=result.score + boost))
    reranked.sort(key=lambda item: (-item.score, item.relative_path, item.unit_type))
    return reranked


def _unit_intent_boost(query_terms: set[str], result: SearchResult) -> float:
    table_terms = {
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
    }
    ocr_terms = {
        "receipt",
        "invoice",
        "label",
        "notice",
        "permit",
        "card",
        "asset",
        "shipping",
        "meeting",
        "backup",
        "badge",
        "ticket",
        "scan",
        "scanned",
        "rotated",
        "contrast",
        "dense",
        "grid",
    }
    if result.unit_type == "pdf_table" and query_terms & table_terms:
        return 0.12
    if result.unit_type == "pdf_ocr_text" and query_terms & ocr_terms:
        return 0.12
    return 0.0


def _contract_features(
    *,
    query: str,
    target: dict[str, Any],
    results: list[SearchResult],
    negative_paths: list[str],
) -> dict[str, Any]:
    query_terms = _query_terms(query)
    target_result = _find_target_result(results, target)
    top1 = results[0] if results else None
    negative_result = _best_negative_result(results, negative_paths)
    return {
        "query_term_count": len(query_terms),
        "target_present_in_deep_k": target_result is not None,
        "top1_relation": _result_relation(top1, target, negative_paths),
        "target_score_recorded": target_result is not None,
        "target_score_gap_from_top1": _score_gap(top1, target_result),
        "target_filename_overlap_ratio": _result_filename_overlap(query_terms, target_result),
        "target_snippet_overlap_ratio": _result_snippet_overlap(query_terms, target_result),
        "top1_filename_overlap_ratio": _result_filename_overlap(query_terms, top1),
        "top1_snippet_overlap_ratio": _result_snippet_overlap(query_terms, top1),
        "best_negative_filename_overlap_ratio": _result_filename_overlap(
            query_terms,
            negative_result,
        ),
        "best_negative_snippet_overlap_ratio": _result_snippet_overlap(
            query_terms,
            negative_result,
        ),
    }


def _find_target_result(
    results: list[SearchResult],
    target: dict[str, Any],
) -> SearchResult | None:
    rank = _target_rank(results, target)
    return results[rank - 1] if rank else None


def _best_negative_result(
    results: list[SearchResult],
    negative_paths: list[str],
) -> SearchResult | None:
    ranks = _negative_ranks(results, negative_paths)
    return results[min(ranks) - 1] if ranks else None


def _result_relation(
    result: SearchResult | None,
    target: dict[str, Any],
    negative_paths: list[str],
) -> str:
    if result is None:
        return "empty"
    if _target_rank([result], target) == 1:
        return "target"
    if result.relative_path in {str(path) for path in negative_paths}:
        return "negative"
    return "other"


def _result_filename_overlap(
    query_terms: set[str],
    result: SearchResult | None,
) -> float:
    if result is None:
        return 0.0
    filename_terms = _query_terms(result.relative_path.replace("_", " ").replace("-", " "))
    return _overlap_ratio(query_terms, filename_terms)


def _result_snippet_overlap(
    query_terms: set[str],
    result: SearchResult | None,
) -> float:
    if result is None:
        return 0.0
    return _overlap_ratio(query_terms, _query_terms(result.snippet))


def _overlap_ratio(query_terms: set[str], candidate_terms: set[str]) -> float:
    if not query_terms or not candidate_terms:
        return 0.0
    return round(len(query_terms & candidate_terms) / len(query_terms), 6)


def _score_gap(
    top1: SearchResult | None,
    target: SearchResult | None,
) -> float | None:
    if top1 is None or target is None:
        return None
    return round(float(top1.score) - float(target.score), 6)


def _failure_bucket_from_result(result: dict[str, Any]) -> str:
    if result["passed"]:
        return "pass"
    if result["negative_before_target_count"]:
        return "negative_before_target"
    if result["target_rank_top_k"] > result["target_max_rank"]:
        return "target_below_max_rank"
    if result["target_rank_deep_k"] > 0:
        return "target_below_top_k"
    return "target_not_in_deep_top_k"


def _best_candidate(
    candidates: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
) -> str:
    baseline_tuple = _candidate_sort_tuple(baseline)
    best_name = "baseline"
    best_tuple = baseline_tuple
    for name, row in candidates.items():
        row_tuple = _candidate_sort_tuple(row)
        if row_tuple > best_tuple:
            best_name = name
            best_tuple = row_tuple
    return best_name


def _candidate_sort_tuple(row: dict[str, Any]) -> tuple[int, int, int, int]:
    passed = int(bool(row["passed"]))
    target_within = int(
        row["target_rank_top_k"] > 0
        and row["target_rank_top_k"] <= row["target_max_rank"]
    )
    target_hit = int(row["target_rank_top_k"] > 0)
    negative_safety = -int(row["negative_top1"]) - int(
        row["negative_before_target_count"]
    )
    return (passed, target_within, target_hit, negative_safety)


def _summarize_queries(details: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        candidate: _summarize_candidate(details, candidate)
        for candidate in DIAGNOSTIC_CANDIDATES
    }


def _summarize_candidate(
    details: list[dict[str, Any]],
    candidate: str,
) -> dict[str, Any]:
    rows = [item["candidates"][candidate] for item in details]
    evaluated = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    target_hit_top_k = sum(1 for row in rows if row["target_rank_top_k"] > 0)
    target_hit_deep = sum(1 for row in rows if row["target_rank_deep_k"] > 0)
    target_within_max = sum(
        1
        for row in rows
        if row["target_rank_top_k"] > 0
        and row["target_rank_top_k"] <= row["target_max_rank"]
    )
    negative_top1 = sum(1 for row in rows if row["negative_top1"])
    negative_before = sum(int(row["negative_before_target_count"]) for row in rows)
    buckets = Counter(_failure_bucket_from_result(row) for row in rows)
    return {
        "evaluated_queries": evaluated,
        "passed_queries": passed,
        "pass_rate": _rate(passed, evaluated),
        "target_hit_top_k_count": target_hit_top_k,
        "target_hit_top_k_rate": _rate(target_hit_top_k, evaluated),
        "target_hit_deep_k_count": target_hit_deep,
        "target_hit_deep_k_rate": _rate(target_hit_deep, evaluated),
        "target_within_max_rank_count": target_within_max,
        "negative_top1_count": negative_top1,
        "negative_before_target_count": negative_before,
        "failure_bucket_counts": dict(sorted(buckets.items())),
    }


def _aggregate_modes(modes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidate_summaries = {}
    for candidate in DIAGNOSTIC_CANDIDATES:
        summaries = [mode["summary"][candidate] for mode in modes.values()]
        candidate_summaries[candidate] = _merge_summaries(summaries)
    baseline = candidate_summaries["baseline"]
    best_name = _best_aggregate_candidate(candidate_summaries)
    best = candidate_summaries[best_name]
    return {
        "candidate_summaries": candidate_summaries,
        "best_candidate": best_name,
        "target_hit_top_k_delta": round(
            best["target_hit_top_k_rate"] - baseline["target_hit_top_k_rate"],
            6,
        ),
        "pass_rate_delta": round(best["pass_rate"] - baseline["pass_rate"], 6),
        "negative_top1_regressed": best["negative_top1_count"]
        > baseline["negative_top1_count"],
        "public_quality_claim_allowed": False,
        "recommended_next": _diagnostic_recommendation(best_name, baseline, best),
    }


def _merge_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = sum(summary["evaluated_queries"] for summary in summaries)
    passed = sum(summary["passed_queries"] for summary in summaries)
    target_hit_top_k = sum(summary["target_hit_top_k_count"] for summary in summaries)
    target_hit_deep = sum(summary["target_hit_deep_k_count"] for summary in summaries)
    target_within_max = sum(
        summary["target_within_max_rank_count"] for summary in summaries
    )
    negative_top1 = sum(summary["negative_top1_count"] for summary in summaries)
    negative_before = sum(summary["negative_before_target_count"] for summary in summaries)
    buckets = Counter()
    for summary in summaries:
        buckets.update(summary["failure_bucket_counts"])
    return {
        "evaluated_queries": evaluated,
        "passed_queries": passed,
        "pass_rate": _rate(passed, evaluated),
        "target_hit_top_k_count": target_hit_top_k,
        "target_hit_top_k_rate": _rate(target_hit_top_k, evaluated),
        "target_hit_deep_k_count": target_hit_deep,
        "target_hit_deep_k_rate": _rate(target_hit_deep, evaluated),
        "target_within_max_rank_count": target_within_max,
        "negative_top1_count": negative_top1,
        "negative_before_target_count": negative_before,
        "failure_bucket_counts": dict(sorted(buckets.items())),
    }


def _best_aggregate_candidate(summaries: dict[str, dict[str, Any]]) -> str:
    def key(item: tuple[str, dict[str, Any]]) -> tuple[float, float, int, int]:
        name, row = item
        safety_penalty = row["negative_top1_count"] + row["negative_before_target_count"]
        baseline_penalty = 1 if name == "baseline" else 0
        return (
            row["pass_rate"],
            row["target_hit_top_k_rate"],
            -safety_penalty,
            -baseline_penalty,
        )

    return max(summaries.items(), key=key)[0]


def _diagnostic_recommendation(
    best_name: str,
    baseline: dict[str, Any],
    best: dict[str, Any],
) -> str:
    if best_name == "baseline":
        return "hold ranking repair; audit query contract or embedding coverage first"
    if best["negative_top1_count"] > baseline["negative_top1_count"]:
        return "reject diagnostic candidate because negative top1 regressed"
    if best["target_hit_top_k_rate"] <= baseline["target_hit_top_k_rate"]:
        return "hold ranking repair because target hit rate did not improve"
    return "continue benchmark-only repair validation; product runtime change remains blocked"


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
        description="Run benchmark-only OCR/table hard-negative ranking diagnostics."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=DEFAULT_CACHE_SAFETY_GOLDEN.as_posix())
    parser.add_argument("--out")
    parser.add_argument("--top-k", type=int, default=10)
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
