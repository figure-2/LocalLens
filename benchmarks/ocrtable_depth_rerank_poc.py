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
from benchmarks.ocrtable_cache_safety_live_eval import _raw_report_key_findings
from benchmarks.ocrtable_cache_safety_live_eval import _settings_for_mode
from benchmarks.ocrtable_deep_miss_audit import _audit_query as _deep_miss_query
from benchmarks.ocrtable_embedding_coverage_diagnostic import (
    _expanded_query,
)
from benchmarks.ocrtable_query_embedding_repair_poc import (
    REFERENCE_CANDIDATE as QUERY_REFERENCE_CANDIDATE,
)
from benchmarks.ocrtable_query_embedding_repair_poc import (
    _evaluate_candidate as _query_embedding_evaluate_candidate,
)
from benchmarks.ocrtable_query_embedding_repair_poc import _include_case
from benchmarks.ocrtable_query_embedding_repair_poc import _targeted_family_name
from benchmarks.ocrtable_ranking_deep_miss_audit import _cause_family
from benchmarks.ocrtable_ranking_diagnostic import DIAGNOSTIC_CANDIDATES
from benchmarks.ocrtable_ranking_diagnostic import (
    _evaluate_candidate as _ranking_evaluate_candidate,
)
from benchmarks.ocrtable_ranking_diagnostic import _rerank_candidate


SCHEMA_VERSION = "ocrtable-depth-rerank-poc-v1"
REFERENCE_CANDIDATE = "depth200_no_rerank"
RERANK_CANDIDATES = tuple(
    candidate for candidate in DIAGNOSTIC_CANDIDATES if candidate != "baseline"
) + (
    "strong_text_overlap",
    "overlap_rank_fusion",
)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_depth_rerank_poc(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        top_k=args.top_k,
        baseline_deep_top_k=args.baseline_deep_top_k,
        candidate_pool_depth=args.candidate_pool_depth,
        max_extra_terms=args.max_extra_terms,
        tesseract_cmd=args.tesseract_cmd,
        ocr_lang=args.ocr_lang,
        tesseract_psm=args.tesseract_psm,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-depth-rerank-poc",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(report, args.out or "ocrtable-depth-rerank-poc")
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


def run_depth_rerank_poc(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_CACHE_SAFETY_GOLDEN,
    top_k: int = 10,
    baseline_deep_top_k: int = 50,
    candidate_pool_depth: int = 200,
    max_extra_terms: int = 8,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    tesseract_psm: str = "6",
) -> dict[str, Any]:
    started = time.perf_counter()
    if baseline_deep_top_k < top_k:
        raise ValueError("baseline_deep_top_k must be greater than or equal to top_k")
    if candidate_pool_depth < baseline_deep_top_k:
        raise ValueError(
            "candidate_pool_depth must be greater than or equal to baseline_deep_top_k"
        )
    if max_extra_terms < 0:
        raise ValueError("max_extra_terms must be non-negative")
    run = _run_depth_rerank_candidates(
        pdf_dir=pdf_dir,
        golden_path=golden_path,
        top_k=top_k,
        baseline_deep_top_k=baseline_deep_top_k,
        candidate_pool_depth=candidate_pool_depth,
        max_extra_terms=max_extra_terms,
        tesseract_cmd=tesseract_cmd,
        ocr_lang=ocr_lang,
        tesseract_psm=tesseract_psm,
    )
    reference = run["candidate_summaries"][REFERENCE_CANDIDATE]
    selected_name = _select_candidate(run["candidate_summaries"], reference)
    selected = run["candidate_summaries"][selected_name]
    improvement = _improvement(selected, reference)
    acceptance = _acceptance(improvement, selected)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "local-live",
        "benchmark_only": True,
        "default_enabled": False,
        "product_runtime_changed": False,
        "product_repair_approved": False,
        "public_quality_claim_allowed": False,
        "search_time_source_changed": False,
        "query_content_recorded": False,
        "document_body_recorded": False,
        "stable_document_identifier_recorded": False,
        "case_identifier_policy": "aggregate-only",
        "tesseract_command_recorded": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "corpus": {
            "pdf_files": run["corpus"]["pdf_files"],
            "hard_negative_queries": run["corpus"]["hard_negative_queries"],
            "targeted_depth_rerank_cases": run["targeted_case_count"],
            "top_k": top_k,
            "baseline_deep_top_k": baseline_deep_top_k,
            "candidate_pool_depth": candidate_pool_depth,
            "max_extra_terms": max_extra_terms,
        },
        "reference_candidate": REFERENCE_CANDIDATE,
        "rerank_candidate_count": len(RERANK_CANDIDATES),
        "targeted_case_family_counts": run["targeted_case_family_counts"],
        "candidate_summaries": run["candidate_summaries"],
        "selected_candidate": selected_name,
        "improvement_vs_reference": improvement,
        "acceptance": acceptance,
        "decision": _decision(acceptance),
        "next_work_order": _next_work_order(acceptance),
    }


def _run_depth_rerank_candidates(
    *,
    pdf_dir: Path,
    golden_path: Path,
    top_k: int,
    baseline_deep_top_k: int,
    candidate_pool_depth: int,
    max_extra_terms: int,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    pdf_dir = pdf_dir.resolve()
    docs = sorted(path.name for path in pdf_dir.glob("*.pdf"))
    source_docs = set(docs)
    queries = [
        item
        for item in _cache_safety_queries(golden_path)
        if item.get("scenario") == "hard-negative"
        and _mode_for_unit_type(
            str(((item.get("relevant") or [{}])[0]).get("unit_type") or "")
        )
        == "ocr"
    ]
    with tempfile.TemporaryDirectory(prefix="locallens-depth-rerank-poc-") as temp_root:
        temp = Path(temp_root)
        source = temp / "source"
        data_dir = temp / "data"
        source.mkdir()
        for name in docs:
            (source / name).write_bytes((pdf_dir / name).read_bytes())
        settings = _settings_for_mode(
            data_dir=data_dir,
            mode="ocr",
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
        rows = [
            _targeted_case(
                item,
                payloads=payloads,
                source_docs=source_docs,
                searcher=lambda query, k: search.search(
                    query,
                    top_k=k,
                    modality="text",
                ),
                top_k=top_k,
                baseline_deep_top_k=baseline_deep_top_k,
                candidate_pool_depth=candidate_pool_depth,
                max_extra_terms=max_extra_terms,
            )
            for item in queries
        ]
        manifest_units = manifest.unit_count()
        store_units = store.count()
        store.close()
    targeted = [row for row in rows if row["included_in_targeted_poc"]]
    return {
        "corpus": {
            "pdf_files": len(docs),
            "hard_negative_queries": len(queries),
        },
        "indexed_units": store_units,
        "manifest_units": manifest_units,
        "sync": _sync_summary(sync_report),
        "index_latency_ms": round(index_ms, 6),
        "targeted_case_count": len(targeted),
        "targeted_case_family_counts": dict(
            sorted(Counter(row["blocker_family"] for row in targeted).items())
        ),
        "candidate_summaries": _candidate_summaries(targeted),
    }


def _targeted_case(
    item: dict[str, Any],
    *,
    payloads: list[dict[str, Any]],
    source_docs: set[str],
    searcher: Callable[[str, int], list[SearchResult]],
    top_k: int,
    baseline_deep_top_k: int,
    candidate_pool_depth: int,
    max_extra_terms: int,
) -> dict[str, Any]:
    target = (item.get("relevant") or [{}])[0]
    deep = _deep_miss_query(
        item,
        payloads=payloads,
        searcher=searcher,
        deep_top_k=baseline_deep_top_k,
    )
    family = _cause_family(deep, str(deep.get("target_document") or "") in source_docs)
    query_reference = _query_embedding_evaluate_candidate(
        QUERY_REFERENCE_CANDIDATE,
        item,
        target=target,
        searcher=searcher,
        top_k=top_k,
        deep_top_k=baseline_deep_top_k,
        max_extra_terms=max_extra_terms,
    )
    included = _include_case(deep, family, query_reference)
    expanded_query, added_terms = _expanded_query(
        QUERY_REFERENCE_CANDIDATE,
        str(item.get("query") or ""),
        max_extra_terms=max_extra_terms,
    )
    pool_results = searcher(expanded_query, candidate_pool_depth)
    candidate_rows = {
        REFERENCE_CANDIDATE: _evaluate_depth_candidate(
            REFERENCE_CANDIDATE,
            item,
            target=target,
            pool_results=pool_results,
            rerank_query=expanded_query,
            top_k=top_k,
            candidate_pool_depth=candidate_pool_depth,
            added_term_count=len(added_terms),
        )
    }
    candidate_rows.update(
        {
            candidate: _evaluate_depth_candidate(
                candidate,
                item,
                target=target,
                pool_results=pool_results,
                rerank_query=expanded_query,
                top_k=top_k,
                candidate_pool_depth=candidate_pool_depth,
                added_term_count=len(added_terms),
            )
            for candidate in RERANK_CANDIDATES
        }
    )
    return {
        "included_in_targeted_poc": included,
        "mode": _mode_for_unit_type(str(target.get("unit_type") or "")) or "",
        "target_unit_type": str(target.get("unit_type") or ""),
        "blocker_family": _targeted_family_name(
            family,
            {QUERY_REFERENCE_CANDIDATE: query_reference},
        ),
        "baseline_primary_reason": str(deep.get("primary_reason") or ""),
        "target_preview_term_count": int(deep.get("target_preview_term_count") or 0),
        "target_preview_overlap_ratio": float(
            deep.get("target_preview_overlap_ratio") or 0.0
        ),
        "negative_preview_overlap_ratio": float(
            deep.get("negative_preview_overlap_ratio") or 0.0
        ),
        "candidates": candidate_rows,
    }


def _evaluate_depth_candidate(
    candidate: str,
    item: dict[str, Any],
    *,
    target: dict[str, Any],
    pool_results: list[SearchResult],
    rerank_query: str,
    top_k: int,
    candidate_pool_depth: int,
    added_term_count: int,
) -> dict[str, Any]:
    item_top_k = int(item.get("top_k") or top_k)
    max_rank = int(target.get("max_rank") or item_top_k)
    negative_paths = [str(path) for path in item.get("negative_paths", [])]
    ranked_results = (
        list(pool_results)
        if candidate == REFERENCE_CANDIDATE
        else _depth_rerank_candidate(candidate, rerank_query, pool_results)
    )
    evaluated = _ranking_evaluate_candidate(
        ranked_results,
        target=target,
        negative_paths=negative_paths,
        top_k=item_top_k,
        max_rank=max_rank,
        deep_results=pool_results,
    )
    return {
        "candidate": candidate,
        "query_term_count": len(_query_terms(rerank_query)),
        "added_term_count": added_term_count,
        "candidate_pool_depth": candidate_pool_depth,
        "label_aware": False,
        "product_runtime_eligible": False,
        "target_rank_top_k": int(evaluated["target_rank_top_k"]),
        "target_rank_pool": int(evaluated["target_rank_deep_k"]),
        "target_max_rank": int(evaluated["target_max_rank"]),
        "target_hit_top_k": int(evaluated["target_rank_top_k"]) > 0,
        "target_hit_pool": int(evaluated["target_rank_deep_k"]) > 0,
        "negative_best_rank_top_k": int(evaluated["negative_best_rank_top_k"]),
        "negative_before_target_count": int(
            evaluated["negative_before_target_count"]
        ),
        "negative_top1": bool(evaluated["negative_top1"]),
        "passed": bool(evaluated["passed"]),
    }


def _depth_rerank_candidate(
    candidate: str,
    query: str,
    results: list[SearchResult],
) -> list[SearchResult]:
    if candidate in DIAGNOSTIC_CANDIDATES:
        return _rerank_candidate(candidate, query, results)
    query_terms = _query_terms(query)
    if candidate == "strong_text_overlap":
        return _strong_text_overlap_rerank(query_terms, results)
    if candidate == "overlap_rank_fusion":
        return _overlap_rank_fusion_rerank(query_terms, results)
    raise ValueError(f"unsupported depth rerank candidate: {candidate}")


def _strong_text_overlap_rerank(
    query_terms: set[str],
    results: list[SearchResult],
) -> list[SearchResult]:
    reranked = [
        replace(
            result,
            score=(
                float(result.score)
                + _result_filename_overlap(query_terms, result) * 0.75
                + _result_snippet_overlap(query_terms, result) * 0.55
                + _unit_intent_match(query_terms, result) * 0.20
            ),
        )
        for result in results
    ]
    reranked.sort(key=lambda item: (-item.score, item.relative_path, item.unit_type))
    return reranked


def _overlap_rank_fusion_rerank(
    query_terms: set[str],
    results: list[SearchResult],
) -> list[SearchResult]:
    reranked = []
    for rank, result in enumerate(results, start=1):
        fusion_score = (
            _result_filename_overlap(query_terms, result) * 0.45
            + _result_snippet_overlap(query_terms, result) * 0.45
            + _unit_intent_match(query_terms, result) * 0.10
            + (1.0 / (rank + 9)) * 0.05
        )
        reranked.append(replace(result, score=fusion_score))
    reranked.sort(key=lambda item: (-item.score, item.relative_path, item.unit_type))
    return reranked


def _result_filename_overlap(query_terms: set[str], result: SearchResult) -> float:
    filename_terms = _query_terms(result.relative_path.replace("_", " ").replace("-", " "))
    return _overlap_ratio(query_terms, filename_terms)


def _result_snippet_overlap(query_terms: set[str], result: SearchResult) -> float:
    return _overlap_ratio(query_terms, _query_terms(result.snippet))


def _unit_intent_match(query_terms: set[str], result: SearchResult) -> float:
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
    if result.unit_type == "pdf_ocr_text" and query_terms & ocr_terms:
        return 1.0
    return 0.0


def _overlap_ratio(query_terms: set[str], candidate_terms: set[str]) -> float:
    if not query_terms or not candidate_terms:
        return 0.0
    return round(len(query_terms & candidate_terms) / len(query_terms), 6)


def _candidate_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        candidate: _summarize_candidate(rows, candidate)
        for candidate in (REFERENCE_CANDIDATE, *RERANK_CANDIDATES)
    }


def _summarize_candidate(
    rows: list[dict[str, Any]],
    candidate: str,
) -> dict[str, Any]:
    candidate_rows = [row["candidates"][candidate] for row in rows]
    evaluated = len(candidate_rows)
    target_hit_top = sum(1 for row in candidate_rows if row["target_hit_top_k"])
    target_hit_pool = sum(1 for row in candidate_rows if row["target_hit_pool"])
    passed = sum(1 for row in candidate_rows if row["passed"])
    negative_top1 = sum(1 for row in candidate_rows if row["negative_top1"])
    negative_before = sum(int(row["negative_before_target_count"]) for row in candidate_rows)
    return {
        "evaluated_cases": evaluated,
        "max_candidate_pool_depth": max(
            (int(row["candidate_pool_depth"]) for row in candidate_rows),
            default=0,
        ),
        "target_hit_top_k_count": target_hit_top,
        "target_hit_top_k_rate": _rate(target_hit_top, evaluated),
        "target_hit_pool_count": target_hit_pool,
        "target_hit_pool_rate": _rate(target_hit_pool, evaluated),
        "remaining_top_k_blocker_count": evaluated - target_hit_top,
        "remaining_pool_blocker_count": evaluated - target_hit_pool,
        "passed_cases": passed,
        "pass_rate": _rate(passed, evaluated),
        "negative_top1_count": negative_top1,
        "negative_before_target_count": negative_before,
    }


def _select_candidate(
    summaries: dict[str, dict[str, Any]],
    reference: dict[str, Any],
) -> str:
    def key(item: tuple[str, dict[str, Any]]) -> tuple[int, int, int, float, int, int]:
        name, row = item
        safety = int(row["negative_top1_count"] <= reference["negative_top1_count"])
        top_hit_gain = int(row["target_hit_top_k_count"]) - int(
            reference["target_hit_top_k_count"]
        )
        pass_gain = int(row["passed_cases"]) - int(reference["passed_cases"])
        reference_bonus = 1 if name == REFERENCE_CANDIDATE else 0
        return (
            safety,
            pass_gain,
            top_hit_gain,
            float(row["pass_rate"]),
            -int(row["negative_before_target_count"]),
            reference_bonus,
        )

    return max(summaries.items(), key=key)[0]


def _improvement(
    selected: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    return {
        "target_hit_top_k_count_delta": int(selected["target_hit_top_k_count"])
        - int(reference["target_hit_top_k_count"]),
        "target_hit_pool_count_delta": int(selected["target_hit_pool_count"])
        - int(reference["target_hit_pool_count"]),
        "remaining_top_k_blocker_count_delta": int(
            selected["remaining_top_k_blocker_count"]
        )
        - int(reference["remaining_top_k_blocker_count"]),
        "remaining_pool_blocker_count_delta": int(
            selected["remaining_pool_blocker_count"]
        )
        - int(reference["remaining_pool_blocker_count"]),
        "passed_cases_delta": int(selected["passed_cases"])
        - int(reference["passed_cases"]),
        "negative_top1_count_delta": int(selected["negative_top1_count"])
        - int(reference["negative_top1_count"]),
        "negative_before_target_count_delta": int(
            selected["negative_before_target_count"]
        )
        - int(reference["negative_before_target_count"]),
        "pass_rate_delta": _delta(float(selected["pass_rate"]), float(reference["pass_rate"])),
    }


def _acceptance(
    improvement: dict[str, Any],
    selected: dict[str, Any],
) -> dict[str, bool]:
    return {
        "target_hit_top_k_improves": int(
            improvement["target_hit_top_k_count_delta"]
        )
        > 0,
        "passed_cases_improve": int(improvement["passed_cases_delta"]) > 0,
        "negative_top1_remains_zero": int(selected["negative_top1_count"]) == 0,
        "product_runtime_unchanged": True,
        "public_claim_blocked": True,
    }


def _decision(acceptance: dict[str, bool]) -> str:
    if not all(acceptance.values()):
        return "hold-depth-rerank-poc"
    return "benchmark-only-depth-rerank-improved-product-decision-required"


def _next_work_order(acceptance: dict[str, bool]) -> list[dict[str, str]]:
    if not (
        acceptance["target_hit_top_k_improves"]
        and acceptance["passed_cases_improve"]
        and acceptance["negative_top1_remains_zero"]
    ):
        return [
            {
                "id": "LL-OCRTABLE-RANKING-REPAIR-HOLD",
                "depends_on": "LL-OCRTABLE-RANKING-DEPTH-RERANK-POC",
                "scope": "record depth/rerank POC as hold and avoid product ranking repair",
                "acceptance_tests": "private evidence only, product runtime unchanged",
                "risk_level": "medium",
                "rollback_plan": "keep benchmark-only evidence",
            },
            {
                "id": "LL-OCRTABLE-010-PUBLIC-EVIDENCE-DECIDE",
                "depends_on": "OCR/table repair hold decision",
                "scope": "decide if any private OCR/table evidence can be promoted publicly",
                "acceptance_tests": "docs, claims, .locallens, release-gate pass together",
                "risk_level": "medium",
                "rollback_plan": "keep private-only evidence",
            },
        ]
    return [
        {
            "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
            "depends_on": "LL-OCRTABLE-RANKING-DEPTH-RERANK-POC",
            "scope": "decide whether depth/rerank can become a default-off product POC",
            "acceptance_tests": "explicit approval, same-fixture non-regression, search-time cache source forbidden",
            "risk_level": "high",
            "rollback_plan": "leave product runtime unchanged",
        },
        {
            "id": "LL-OCRTABLE-010-PUBLIC-EVIDENCE-DECIDE",
            "depends_on": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
            "scope": "decide if OCR/table evidence can be promoted publicly",
            "acceptance_tests": "docs, claims, .locallens, release-gate pass together",
            "risk_level": "medium",
            "rollback_plan": "keep private-only evidence",
        },
    ]


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
            "cache_result_hits",
            "cache_result_misses",
            "cache_entries_written",
        )
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _delta(left: float, right: float) -> float:
    return round(float(left) - float(right), 6)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run benchmark-only OCR/table depth rerank POC."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=DEFAULT_CACHE_SAFETY_GOLDEN.as_posix())
    parser.add_argument("--out")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--baseline-deep-top-k", type=int, default=50)
    parser.add_argument("--candidate-pool-depth", type=int, default=200)
    parser.add_argument("--max-extra-terms", type=int, default=8)
    parser.add_argument("--tesseract-cmd", default="tesseract")
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--tesseract-psm", default="6")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=_default_blocked_terms_file())
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
