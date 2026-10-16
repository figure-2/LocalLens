from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
from benchmarks.ocrtable_deep_miss_audit import _audit_query as _deep_miss_query
from benchmarks.ocrtable_embedding_coverage_diagnostic import CANDIDATES as BASE_CANDIDATES
from benchmarks.ocrtable_embedding_coverage_diagnostic import _expanded_query
from benchmarks.ocrtable_ranking_deep_miss_audit import _cause_family


SCHEMA_VERSION = "ocrtable-query-embedding-repair-poc-v1"
REFERENCE_CANDIDATE = "normalized_query"
EXTRA_CANDIDATES = (
    "ocr_profile_expansion_v2",
    "normalized_query_depth100",
    "normalized_query_depth200",
)
QUERY_EMBEDDING_FAMILIES = {
    "embedding",
    "embedding_or_query_embedding",
    "mixed_query_embedding",
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_query_embedding_repair_poc(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        top_k=args.top_k,
        deep_top_k=args.deep_top_k,
        max_extra_terms=args.max_extra_terms,
        tesseract_cmd=args.tesseract_cmd,
        ocr_lang=args.ocr_lang,
        tesseract_psm=args.tesseract_psm,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-query-embedding-repair-poc",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-query-embedding-repair-poc",
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


def run_query_embedding_repair_poc(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_CACHE_SAFETY_GOLDEN,
    top_k: int = 10,
    deep_top_k: int = 50,
    max_extra_terms: int = 8,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    tesseract_psm: str = "6",
) -> dict[str, Any]:
    started = time.perf_counter()
    if deep_top_k < top_k:
        raise ValueError("deep_top_k must be greater than or equal to top_k")
    if max_extra_terms < 0:
        raise ValueError("max_extra_terms must be non-negative")
    run = _run_targeted_candidates(
        pdf_dir=pdf_dir,
        golden_path=golden_path,
        top_k=top_k,
        deep_top_k=deep_top_k,
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
            "targeted_query_embedding_cases": run["targeted_case_count"],
            "top_k": top_k,
            "deep_top_k": deep_top_k,
            "max_extra_terms": max_extra_terms,
        },
        "reference_candidate": REFERENCE_CANDIDATE,
        "candidate_count": len(run["candidate_summaries"]),
        "targeted_case_family_counts": run["targeted_case_family_counts"],
        "candidate_summaries": run["candidate_summaries"],
        "selected_candidate": selected_name,
        "improvement_vs_reference": improvement,
        "acceptance": acceptance,
        "decision": _decision(acceptance),
        "next_work_order": _next_work_order(acceptance),
    }


def _run_targeted_candidates(
    *,
    pdf_dir: Path,
    golden_path: Path,
    top_k: int,
    deep_top_k: int,
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
    with tempfile.TemporaryDirectory(prefix="locallens-query-embedding-poc-") as temp_root:
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
                deep_top_k=deep_top_k,
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
    searcher,
    top_k: int,
    deep_top_k: int,
    max_extra_terms: int,
) -> dict[str, Any]:
    target = (item.get("relevant") or [{}])[0]
    deep = _deep_miss_query(
        item,
        payloads=payloads,
        searcher=searcher,
        deep_top_k=deep_top_k,
    )
    family = _cause_family(deep, str(deep.get("target_document") or "") in source_docs)
    candidate_rows = {
        candidate: _evaluate_candidate(
            candidate,
            item,
            target=target,
            searcher=searcher,
            top_k=top_k,
            deep_top_k=deep_top_k,
            max_extra_terms=max_extra_terms,
        )
        for candidate in (*BASE_CANDIDATES, *EXTRA_CANDIDATES)
    }
    included = _include_case(deep, family, candidate_rows[REFERENCE_CANDIDATE])
    return {
        "included_in_targeted_poc": included,
        "mode": _mode_for_unit_type(str(target.get("unit_type") or "")) or "",
        "target_unit_type": str(target.get("unit_type") or ""),
        "blocker_family": _targeted_family_name(family, candidate_rows),
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


def _include_case(
    deep: dict[str, Any],
    family: str,
    reference: dict[str, Any],
) -> bool:
    if int(deep["target_rank_deep_k"]) > 0:
        return False
    if family == "mixed_query_embedding":
        return True
    if family in {"embedding", "embedding_or_query_embedding"}:
        return not bool(reference["target_hit_deep_k"])
    return False


def _targeted_family_name(
    family: str,
    candidate_rows: dict[str, dict[str, Any]],
) -> str:
    if family == "mixed_query_embedding":
        return "mixed_query_embedding"
    if family in {"embedding", "embedding_or_query_embedding"}:
        if not candidate_rows[REFERENCE_CANDIDATE]["target_hit_deep_k"]:
            return "unrecovered_embedding"
        return "embedding_reference_recovered"
    return family


def _evaluate_candidate(
    candidate: str,
    item: dict[str, Any],
    *,
    target: dict[str, Any],
    searcher,
    top_k: int,
    deep_top_k: int,
    max_extra_terms: int,
) -> dict[str, Any]:
    expanded, added_terms, candidate_depth = _candidate_plan(
        candidate,
        str(item.get("query") or ""),
        max_extra_terms=max_extra_terms,
        deep_top_k=deep_top_k,
    )
    results = searcher(expanded, candidate_depth)
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
        "query_term_count": len(_query_terms(expanded)),
        "added_term_count": len(added_terms),
        "candidate_depth": candidate_depth,
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


def _candidate_plan(
    candidate: str,
    query: str,
    *,
    max_extra_terms: int,
    deep_top_k: int,
) -> tuple[str, list[str], int]:
    depth_candidate_prefix = "normalized_query_depth"
    if candidate.startswith(depth_candidate_prefix):
        expanded, added_terms = _expanded_query(
            "normalized_query",
            query,
            max_extra_terms=max_extra_terms,
        )
        depth = int(candidate.removeprefix(depth_candidate_prefix))
        return expanded, added_terms, max(depth, 1)
    if candidate in BASE_CANDIDATES:
        expanded, added_terms = _expanded_query(
            candidate,
            query,
            max_extra_terms=max_extra_terms,
        )
        return expanded, added_terms, deep_top_k
    if candidate != "ocr_profile_expansion_v2":
        raise ValueError(f"unsupported query/embedding repair candidate: {candidate}")
    base_query, base_added = _expanded_query(
        "combined_query_family_expansion",
        query,
        max_extra_terms=max_extra_terms,
    )
    if max_extra_terms == 0:
        return base_query, base_added, deep_top_k
    query_terms = _query_terms(base_query)
    base_terms = set(query_terms)
    additions = [
        term
        for term in _ocr_profile_terms(query_terms)
        if term not in base_terms and term not in set(base_added)
    ]
    remaining = max(0, max_extra_terms - len(base_added))
    selected = additions[:remaining]
    if not selected:
        return base_query, base_added, deep_top_k
    return f"{base_query} {' '.join(selected)}", [*base_added, *selected], deep_top_k


def _ocr_profile_terms(query_terms: set[str]) -> list[str]:
    additions: list[str] = []
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
        "amount",
        "status",
        "total",
    }:
        additions.extend(
            [
                "ocr",
                "scan",
                "document",
                "receipt",
                "invoice",
                "label",
                "status",
                "amount",
                "total",
                "date",
                "number",
            ]
        )
    if query_terms & {"로컬", "검색", "승인", "문서", "영수증", "청구서", "배송", "라벨"}:
        additions.extend(
            [
                "local",
                "search",
                "approval",
                "document",
                "receipt",
                "invoice",
                "shipping",
                "label",
            ]
        )
    return _unique(additions)


def _candidate_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        candidate: _summarize_candidate(rows, candidate)
        for candidate in (*BASE_CANDIDATES, *EXTRA_CANDIDATES)
    }


def _summarize_candidate(
    rows: list[dict[str, Any]],
    candidate: str,
) -> dict[str, Any]:
    candidate_rows = [row["candidates"][candidate] for row in rows]
    evaluated = len(candidate_rows)
    target_hit_top = sum(1 for row in candidate_rows if row["target_hit_top_k"])
    target_hit_deep = sum(1 for row in candidate_rows if row["target_hit_deep_k"])
    passed = sum(1 for row in candidate_rows if row["passed"])
    negative_top1 = sum(1 for row in candidate_rows if row["negative_top1"])
    negative_before = sum(int(row["negative_before_target_count"]) for row in candidate_rows)
    added_terms = sum(int(row["added_term_count"]) for row in candidate_rows)
    return {
        "evaluated_cases": evaluated,
        "max_candidate_depth": max(
            (int(row["candidate_depth"]) for row in candidate_rows),
            default=0,
        ),
        "target_hit_top_k_count": target_hit_top,
        "target_hit_top_k_rate": _rate(target_hit_top, evaluated),
        "target_hit_deep_k_count": target_hit_deep,
        "target_hit_deep_k_rate": _rate(target_hit_deep, evaluated),
        "remaining_blocker_count": evaluated - target_hit_deep,
        "passed_cases": passed,
        "pass_rate": _rate(passed, evaluated),
        "negative_top1_count": negative_top1,
        "negative_before_target_count": negative_before,
        "total_added_terms": added_terms,
    }


def _select_candidate(
    summaries: dict[str, dict[str, Any]],
    reference: dict[str, Any],
) -> str:
    def key(item: tuple[str, dict[str, Any]]) -> tuple[int, int, float, int, int]:
        name, row = item
        safety = int(row["negative_top1_count"] <= reference["negative_top1_count"])
        reduction = int(reference["remaining_blocker_count"]) - int(
            row["remaining_blocker_count"]
        )
        reference_bonus = 1 if name == REFERENCE_CANDIDATE else 0
        return (
            safety,
            reduction,
            float(row["target_hit_deep_k_rate"]),
            -int(row["negative_before_target_count"]),
            reference_bonus,
        )

    return max(summaries.items(), key=key)[0]


def _improvement(
    selected: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    return {
        "remaining_blocker_count_delta": int(selected["remaining_blocker_count"])
        - int(reference["remaining_blocker_count"]),
        "target_hit_deep_k_count_delta": int(selected["target_hit_deep_k_count"])
        - int(reference["target_hit_deep_k_count"]),
        "target_hit_top_k_count_delta": int(selected["target_hit_top_k_count"])
        - int(reference["target_hit_top_k_count"]),
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
        "remaining_blockers_decrease": (
            int(improvement["remaining_blocker_count_delta"]) < 0
        ),
        "negative_top1_remains_zero": int(selected["negative_top1_count"]) == 0,
        "product_runtime_unchanged": True,
        "public_claim_blocked": True,
    }


def _decision(acceptance: dict[str, bool]) -> str:
    if not all(acceptance.values()):
        return "hold-query-embedding-repair-poc"
    return "benchmark-only-query-embedding-improved-product-still-blocked"


def _next_work_order(acceptance: dict[str, bool]) -> list[dict[str, str]]:
    if not acceptance["remaining_blockers_decrease"]:
        return [
            {
                "id": "LL-OCRTABLE-RANKING-QUERY-EMBEDDING-REPAIR-HOLD",
                "depends_on": "LL-OCRTABLE-RANKING-QUERY-EMBEDDING-REPAIR-POC",
                "scope": "record query/embedding POC as hold and avoid product query changes",
                "acceptance_tests": "private evidence only, product runtime unchanged",
                "risk_level": "medium",
                "rollback_plan": "keep query/embedding repair spec evidence",
            },
            {
                "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
                "depends_on": "targeted repair POC results",
                "scope": "decide whether OCR/table ranking repair remains hold or gets another targeted POC",
                "acceptance_tests": "explicit approval, same-fixture non-regression, public claim blocked",
                "risk_level": "high",
                "rollback_plan": "leave product runtime unchanged",
            },
        ]
    return [
        {
            "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
            "depends_on": "targeted repair POC results",
            "scope": "decide whether any signal can become a default-off product POC",
            "acceptance_tests": "explicit approval, same-fixture non-regression, public claim blocked",
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


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _delta(left: float, right: float) -> float:
    return round(float(left) - float(right), 6)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run benchmark-only OCR query/embedding repair POC."
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
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=_default_blocked_terms_file())
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
