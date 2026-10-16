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
from benchmarks.ocrtable_hard_negative_audit import _audit_query as _ranking_query
from benchmarks.ocrtable_hard_negative_audit import _mode_summary
from benchmarks.ocrtable_ranking_deep_miss_audit import _cause_family


SCHEMA_VERSION = "ocrtable-extractor-preview-repair-poc-v1"
DEFAULT_PROFILES = ("6", "4", "11", "12", "")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_extractor_preview_repair_poc(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        top_k=args.top_k,
        deep_top_k=args.deep_top_k,
        tesseract_cmd=args.tesseract_cmd,
        ocr_lang=args.ocr_lang,
        baseline_profile=args.baseline_profile,
        profiles=tuple(args.profile or DEFAULT_PROFILES),
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-extractor-preview-repair-poc",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-extractor-preview-repair-poc",
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


def run_extractor_preview_repair_poc(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_CACHE_SAFETY_GOLDEN,
    top_k: int = 10,
    deep_top_k: int = 50,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    baseline_profile: str = "6",
    profiles: tuple[str, ...] = DEFAULT_PROFILES,
) -> dict[str, Any]:
    started = time.perf_counter()
    if deep_top_k < top_k:
        raise ValueError("deep_top_k must be greater than or equal to top_k")
    ordered_profiles = _ordered_profiles(baseline_profile, profiles)
    results = [
        _run_profile_candidate(
            pdf_dir=pdf_dir,
            golden_path=golden_path,
            top_k=top_k,
            deep_top_k=deep_top_k,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=profile,
            baseline=profile == baseline_profile,
        )
        for profile in ordered_profiles
    ]
    baseline = next(result for result in results if result["baseline"])
    compared = [_with_improvement(result, baseline) for result in results]
    selected = _select_profile(compared)
    acceptance = _acceptance(selected)
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
            "pdf_files": compared[0]["corpus"]["pdf_files"] if compared else 0,
            "hard_negative_queries": compared[0]["corpus"]["hard_negative_queries"]
            if compared
            else 0,
            "top_k": top_k,
            "deep_top_k": deep_top_k,
        },
        "profile_count": len(compared),
        "baseline_profile": _profile_name(baseline_profile),
        "profile_results": compared,
        "selected_profile": _selected_summary(selected),
        "acceptance": acceptance,
        "decision": _decision(acceptance),
        "next_work_order": _next_work_order(acceptance),
    }


def _run_profile_candidate(
    *,
    pdf_dir: Path,
    golden_path: Path,
    top_k: int,
    deep_top_k: int,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
    baseline: bool,
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
    with tempfile.TemporaryDirectory(prefix="locallens-ocr-profile-poc-") as temp_root:
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
        ranking_rows = [
            _ranking_query(
                item,
                payloads=payloads,
                source_docs=source_docs,
                searcher=lambda query, k: search.search(
                    query,
                    top_k=k,
                    modality="text",
                ),
                deep_top_k=deep_top_k,
            )
            for item in queries
        ]
        deep_rows = [
            _deep_miss_query(
                item,
                payloads=payloads,
                searcher=lambda query, k: search.search(
                    query,
                    top_k=k,
                    modality="text",
                ),
                deep_top_k=deep_top_k,
            )
            for item in queries
        ]
        manifest_units = manifest.unit_count()
        store_units = store.count()
        store.close()
    return {
        "profile": _profile_name(tesseract_psm),
        "profile_ordinal": _profile_ordinal(tesseract_psm),
        "baseline": baseline,
        "corpus": {
            "pdf_files": len(docs),
            "hard_negative_queries": len(queries),
        },
        "indexed_units": store_units,
        "manifest_units": manifest_units,
        "sync": _sync_summary(sync_report),
        "index_latency_ms": round(index_ms, 6),
        "ranking": _safe_ranking_summary(_mode_summary(ranking_rows)),
        "deep_miss": _safe_deep_miss_summary(deep_rows, source_docs),
    }


def _safe_ranking_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluated_queries": int(summary["evaluated_queries"]),
        "passed_queries": int(summary["passed_queries"]),
        "pass_rate": float(summary["pass_rate"]),
        "target_unit_indexed_count": int(summary["target_unit_indexed_count"]),
        "target_hit_top_k_count": int(summary["target_hit_top_k_count"]),
        "target_hit_deep_k_count": int(summary["target_hit_deep_k_count"]),
        "negative_top1_count": int(summary["negative_top1_count"]),
        "negative_before_target_count": int(summary["negative_before_target_count"]),
        "failure_bucket_counts": dict(summary["failure_bucket_counts"]),
    }


def _safe_deep_miss_summary(
    rows: list[dict[str, Any]],
    source_docs: set[str],
) -> dict[str, Any]:
    deep_rows = [row for row in rows if int(row["target_rank_deep_k"]) == 0]
    cause_counts = Counter(
        _cause_family(row, str(row.get("target_document") or "") in source_docs)
        for row in deep_rows
    )
    reason_counts = Counter(str(row["primary_reason"]) for row in deep_rows)
    deep_count = len(deep_rows)
    return {
        "deep_miss_count": deep_count,
        "deep_miss_rate": _rate(deep_count, len(rows)),
        "extractor_contract_count": int(cause_counts.get("extractor_contract", 0)),
        "non_extractor_deep_miss_count": deep_count
        - int(cause_counts.get("extractor_contract", 0)),
        "cause_family_counts": dict(sorted(cause_counts.items())),
        "primary_reason_counts": dict(sorted(reason_counts.items())),
    }


def _with_improvement(
    result: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    ranking = result["ranking"]
    base_ranking = baseline["ranking"]
    deep = result["deep_miss"]
    base_deep = baseline["deep_miss"]
    return {
        **result,
        "improvement_vs_baseline": {
            "extractor_contract_reduction": int(
                base_deep["extractor_contract_count"]
            )
            - int(deep["extractor_contract_count"]),
            "deep_miss_count_delta": int(deep["deep_miss_count"])
            - int(base_deep["deep_miss_count"]),
            "non_extractor_deep_miss_delta": int(
                deep["non_extractor_deep_miss_count"]
            )
            - int(base_deep["non_extractor_deep_miss_count"]),
            "pass_rate_delta": _delta(
                float(ranking["pass_rate"]),
                float(base_ranking["pass_rate"]),
            ),
            "target_hit_deep_k_count_delta": int(
                ranking["target_hit_deep_k_count"]
            )
            - int(base_ranking["target_hit_deep_k_count"]),
            "negative_top1_count_delta": int(ranking["negative_top1_count"])
            - int(base_ranking["negative_top1_count"]),
            "negative_before_target_count_delta": int(
                ranking["negative_before_target_count"]
            )
            - int(base_ranking["negative_before_target_count"]),
        },
    }


def _select_profile(results: list[dict[str, Any]]) -> dict[str, Any]:
    return max(results, key=_profile_sort_tuple)


def _profile_sort_tuple(result: dict[str, Any]) -> tuple[int, int, int, float, int, int]:
    improvement = result["improvement_vs_baseline"]
    ranking = result["ranking"]
    return (
        int(int(ranking["negative_top1_count"]) == 0),
        int(improvement["extractor_contract_reduction"]),
        -int(improvement["non_extractor_deep_miss_delta"]),
        float(improvement["pass_rate_delta"]),
        int(improvement["target_hit_deep_k_count_delta"]),
        -int(result["profile_ordinal"]),
    )


def _acceptance(selected: dict[str, Any]) -> dict[str, bool]:
    improvement = selected["improvement_vs_baseline"]
    return {
        "extractor_blocker_decreases": (
            int(improvement["extractor_contract_reduction"]) > 0
        ),
        "negative_top1_remains_zero": int(selected["ranking"]["negative_top1_count"])
        == 0,
        "non_extractor_deep_miss_non_regression": (
            int(improvement["non_extractor_deep_miss_delta"]) <= 0
        ),
        "product_runtime_unchanged": True,
        "public_claim_blocked": True,
    }


def _decision(acceptance: dict[str, bool]) -> str:
    if not all(acceptance.values()):
        return "hold-extractor-preview-repair-poc"
    return "benchmark-only-extractor-repair-improved-product-still-blocked"


def _selected_summary(selected: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": selected["profile"],
        "extractor_contract_count": int(
            selected["deep_miss"]["extractor_contract_count"]
        ),
        "deep_miss_count": int(selected["deep_miss"]["deep_miss_count"]),
        "negative_top1_count": int(selected["ranking"]["negative_top1_count"]),
        "improvement_vs_baseline": dict(selected["improvement_vs_baseline"]),
    }


def _next_work_order(acceptance: dict[str, bool]) -> list[dict[str, str]]:
    work: list[dict[str, str]] = []
    if not acceptance["extractor_blocker_decreases"]:
        work.append(
            {
                "id": "LL-OCRTABLE-RANKING-EXTRACTOR-PREVIEW-REPAIR-HOLD",
                "depends_on": "LL-OCRTABLE-RANKING-EXTRACTOR-PREVIEW-REPAIR-POC",
                "scope": "record extractor-profile POC as hold and avoid product extractor change",
                "acceptance_tests": "private evidence only, product runtime unchanged",
                "risk_level": "medium",
                "rollback_plan": "keep targeted repair spec evidence",
            }
        )
    work.append(
        {
            "id": "LL-OCRTABLE-RANKING-QUERY-EMBEDDING-REPAIR-POC",
            "depends_on": "LL-OCRTABLE-RANKING-QUERY-EMBEDDING-REPAIR-SPEC",
            "scope": "run benchmark-only query normalization or embedding-profile repair POC",
            "acceptance_tests": "remaining blockers decrease, negative_top1 0, product runtime unchanged",
            "risk_level": "high",
            "rollback_plan": "keep query/embedding repair spec evidence only",
        }
    )
    work.append(
        {
            "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
            "depends_on": "targeted repair POC results",
            "scope": "decide whether any signal can become a default-off product POC",
            "acceptance_tests": "explicit approval, same-fixture non-regression, public claim blocked",
            "risk_level": "high",
            "rollback_plan": "leave product runtime unchanged",
        }
    )
    return work


def _ordered_profiles(baseline_profile: str, profiles: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for profile in (baseline_profile, *profiles):
        if profile not in ordered:
            ordered.append(profile)
    return tuple(ordered)


def _profile_name(profile: str) -> str:
    return "default" if profile == "" else f"psm{profile}"


def _profile_ordinal(profile: str) -> int:
    if profile == "":
        return 0
    try:
        return int(profile)
    except ValueError:
        return -1


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
        description="Run a benchmark-only OCR extractor preview/profile repair POC."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=DEFAULT_CACHE_SAFETY_GOLDEN.as_posix())
    parser.add_argument("--out")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--deep-top-k", type=int, default=50)
    parser.add_argument("--tesseract-cmd", default="tesseract")
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--baseline-profile", default="6")
    parser.add_argument("--profile", action="append", default=[])
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=_default_blocked_terms_file())
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
