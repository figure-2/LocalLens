from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact

from benchmarks.ocrtable_cache_safety_live_eval import DEFAULT_CACHE_SAFETY_GOLDEN
from benchmarks.ocrtable_cache_safety_live_eval import _default_blocked_terms_file
from benchmarks.ocrtable_cache_safety_live_eval import _raw_report_key_findings
from benchmarks.ocrtable_embedding_coverage_diagnostic import (
    run_embedding_coverage_diagnostic,
)
from benchmarks.ocrtable_ranking_deep_miss_audit import (
    run_ranking_deep_miss_audit,
)


SCHEMA_VERSION = "ocrtable-embedding-coverage-poc-v1"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_embedding_coverage_poc(
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
        args.out or "ocrtable-embedding-coverage-poc",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-embedding-coverage-poc",
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


def run_embedding_coverage_poc(
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
    started = time.perf_counter()
    deep_miss = run_ranking_deep_miss_audit(
        pdf_dir=pdf_dir,
        golden_path=golden_path,
        deep_top_k=deep_top_k,
        tesseract_cmd=tesseract_cmd,
        ocr_lang=ocr_lang,
        tesseract_psm=tesseract_psm,
        run_table=run_table,
        run_ocr=run_ocr,
    )
    diagnostic = run_embedding_coverage_diagnostic(
        pdf_dir=pdf_dir,
        golden_path=golden_path,
        top_k=top_k,
        deep_top_k=deep_top_k,
        max_extra_terms=max_extra_terms,
        tesseract_cmd=tesseract_cmd,
        ocr_lang=ocr_lang,
        tesseract_psm=tesseract_psm,
        run_table=run_table,
        run_ocr=run_ocr,
    )
    result = _poc_result(deep_miss, diagnostic)
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
            "pdf_files": deep_miss["corpus"]["pdf_files"],
            "hard_negative_queries": deep_miss["corpus"]["hard_negative_queries"],
            "top_k": top_k,
            "deep_top_k": deep_top_k,
            "max_extra_terms": max_extra_terms,
        },
        "baseline_deep_miss": _safe_deep_miss_summary(deep_miss["aggregate"]),
        "embedding_coverage": _safe_coverage_summary(diagnostic["aggregate"]),
        "poc_result": result,
        "acceptance": _acceptance(result),
        "decision": _decision(result),
        "next_work_order": _next_work_order(result),
    }


def _poc_result(
    deep_miss: dict[str, Any],
    diagnostic: dict[str, Any],
) -> dict[str, Any]:
    deep_aggregate = deep_miss["aggregate"]
    coverage_aggregate = diagnostic["aggregate"]
    candidate = str(coverage_aggregate["best_deep_recovery_candidate"])
    baseline_summary = coverage_aggregate["candidate_summaries"]["baseline"]
    candidate_summary = coverage_aggregate["candidate_summaries"][candidate]
    reduction = int(coverage_aggregate["max_deep_miss_reduction_from_baseline"])
    total_remaining = max(0, int(deep_aggregate["deep_miss_count"]) - reduction)
    return {
        "selected_candidate": candidate,
        "embedding_coverage_queries": int(
            coverage_aggregate["evaluated_embedding_coverage_queries"]
        ),
        "baseline_embedding_remaining": int(
            baseline_summary["deep_miss_remaining_count"]
        ),
        "candidate_embedding_remaining": int(
            candidate_summary["deep_miss_remaining_count"]
        ),
        "embedding_deep_miss_reduction": reduction,
        "projected_total_deep_miss_remaining": total_remaining,
        "target_hit_deep_k_delta": float(
            coverage_aggregate["max_target_hit_deep_k_delta"]
        ),
        "candidate_negative_top1_count": int(candidate_summary["negative_top1_count"]),
        "baseline_negative_top1_count": int(baseline_summary["negative_top1_count"]),
        "negative_top1_delta": int(candidate_summary["negative_top1_count"])
        - int(baseline_summary["negative_top1_count"]),
        "candidate_negative_before_target_count": int(
            candidate_summary["negative_before_target_count"]
        ),
        "baseline_negative_before_target_count": int(
            baseline_summary["negative_before_target_count"]
        ),
        "non_embedding_blocker_count": _non_embedding_blocker_count(deep_aggregate),
    }


def _safe_deep_miss_summary(aggregate: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluated_queries": int(aggregate["evaluated_queries"]),
        "deep_miss_count": int(aggregate["deep_miss_count"]),
        "deep_miss_rate": float(aggregate["deep_miss_rate"]),
        "cause_family_counts": dict(aggregate["cause_family_counts"]),
    }


def _safe_coverage_summary(aggregate: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluated_embedding_coverage_queries": int(
            aggregate["evaluated_embedding_coverage_queries"]
        ),
        "best_deep_recovery_candidate": str(aggregate["best_deep_recovery_candidate"]),
        "max_deep_miss_reduction_from_baseline": int(
            aggregate["max_deep_miss_reduction_from_baseline"]
        ),
        "max_target_hit_deep_k_delta": float(
            aggregate["max_target_hit_deep_k_delta"]
        ),
        "negative_top1_regressed": bool(aggregate["negative_top1_regressed"]),
        "classification_counts": dict(aggregate["classification_counts"]),
        "primary_reason_counts": dict(aggregate["primary_reason_counts"]),
    }


def _non_embedding_blocker_count(deep_aggregate: dict[str, Any]) -> int:
    counts = deep_aggregate["cause_family_counts"]
    return sum(
        int(count)
        for family, count in counts.items()
        if family not in {"embedding", "embedding_or_query_embedding"}
    )


def _acceptance(result: dict[str, Any]) -> dict[str, bool]:
    return {
        "deep_miss_count_decreases": result["embedding_deep_miss_reduction"] > 0,
        "negative_top1_non_regression": result["negative_top1_delta"] <= 0,
        "remaining_blocker_recorded": (
            result["projected_total_deep_miss_remaining"] >= 0
        ),
        "product_runtime_unchanged": True,
        "public_claim_blocked": True,
    }


def _decision(result: dict[str, Any]) -> str:
    acceptance = _acceptance(result)
    if not all(acceptance.values()):
        return "hold-embedding-coverage-poc"
    if result["projected_total_deep_miss_remaining"] > 0:
        return "benchmark-only-coverage-improved-product-still-blocked"
    return "benchmark-only-coverage-cleared-product-decision-required"


def _next_work_order(result: dict[str, Any]) -> list[dict[str, str]]:
    if result["projected_total_deep_miss_remaining"] > 0:
        return [
            {
                "id": "LL-OCRTABLE-RANKING-REMAINING-BLOCKER-AUDIT",
                "depends_on": "LL-OCRTABLE-RANKING-EMBEDDING-COVERAGE-POC",
                "scope": "audit the remaining extractor/mixed/unrecovered embedding blockers",
                "acceptance_tests": "ordinal-only report, no raw query/body, repair path separated",
                "risk_level": "medium",
                "rollback_plan": "keep benchmark-only embedding coverage evidence",
            },
            {
                "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
                "depends_on": "LL-OCRTABLE-RANKING-REMAINING-BLOCKER-AUDIT",
                "scope": "decide whether any signal can become a default-off product POC",
                "acceptance_tests": "explicit approval, same-fixture non-regression, public claim blocked",
                "risk_level": "high",
                "rollback_plan": "leave product runtime unchanged",
            },
        ]
    return [
        {
            "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
            "depends_on": "LL-OCRTABLE-RANKING-EMBEDDING-COVERAGE-POC",
            "scope": "decide whether benchmark-only signal can become default-off product POC",
            "acceptance_tests": "explicit approval, same-fixture non-regression, public claim blocked",
            "risk_level": "high",
            "rollback_plan": "leave product runtime unchanged",
        }
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run benchmark-only OCR/table embedding coverage POC."
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
