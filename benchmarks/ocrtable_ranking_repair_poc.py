from __future__ import annotations

import argparse
import json
import os
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
from benchmarks.ocrtable_ranking_diagnostic import run_ranking_diagnostic


SCHEMA_VERSION = "ocrtable-ranking-repair-poc-v1"
DEFAULT_CANDIDATE = "combined_product_available"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_ranking_repair_poc(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        candidate=args.candidate,
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
        args.out or "ocrtable-ranking-repair-poc",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-ranking-repair-poc",
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


def run_ranking_repair_poc(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_CACHE_SAFETY_GOLDEN,
    candidate: str = DEFAULT_CANDIDATE,
    top_k: int = 10,
    deep_top_k: int = 50,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    tesseract_psm: str = "6",
    run_table: bool = True,
    run_ocr: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    diagnostic = run_ranking_diagnostic(
        pdf_dir=pdf_dir,
        golden_path=golden_path,
        top_k=top_k,
        deep_top_k=deep_top_k,
        tesseract_cmd=tesseract_cmd,
        ocr_lang=ocr_lang,
        tesseract_psm=tesseract_psm,
        run_table=run_table,
        run_ocr=run_ocr,
    )
    candidate_summaries = diagnostic["aggregate"]["candidate_summaries"]
    if candidate not in candidate_summaries:
        raise ValueError(f"unsupported ranking repair candidate: {candidate}")
    baseline = candidate_summaries["baseline"]
    repaired = candidate_summaries[candidate]
    improvement = _repair_improvement(baseline, repaired)
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
        "tesseract_command_recorded": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "corpus": {
            "pdf_files": diagnostic["corpus"]["pdf_files"],
            "hard_negative_queries": diagnostic["corpus"]["hard_negative_queries"],
            "top_k": top_k,
            "deep_top_k": deep_top_k,
        },
        "candidate": candidate,
        "baseline": _safe_summary(baseline),
        "candidate_result": _safe_summary(repaired),
        "improvement": improvement,
        "modes": {
            mode: _mode_repair_summary(row["summary"], candidate)
            for mode, row in diagnostic["modes"].items()
        },
        "acceptance": _acceptance(improvement),
        "decision": _decision(improvement),
        "next_work_order": _next_work_order(improvement),
    }


def _mode_repair_summary(
    summaries: dict[str, dict[str, Any]],
    candidate: str,
) -> dict[str, Any]:
    return {
        "baseline": _safe_summary(summaries["baseline"]),
        "candidate_result": _safe_summary(summaries[candidate]),
        "improvement": _repair_improvement(summaries["baseline"], summaries[candidate]),
    }


def _safe_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluated_queries": int(summary["evaluated_queries"]),
        "passed_queries": int(summary["passed_queries"]),
        "pass_rate": float(summary["pass_rate"]),
        "target_hit_top_k_count": int(summary["target_hit_top_k_count"]),
        "target_hit_top_k_rate": float(summary["target_hit_top_k_rate"]),
        "target_hit_deep_k_count": int(summary["target_hit_deep_k_count"]),
        "target_hit_deep_k_rate": float(summary["target_hit_deep_k_rate"]),
        "target_within_max_rank_count": int(summary["target_within_max_rank_count"]),
        "negative_top1_count": int(summary["negative_top1_count"]),
        "negative_before_target_count": int(summary["negative_before_target_count"]),
        "failure_bucket_counts": dict(summary["failure_bucket_counts"]),
    }


def _repair_improvement(
    baseline: dict[str, Any],
    repaired: dict[str, Any],
) -> dict[str, Any]:
    return {
        "pass_rate_delta": _delta(repaired["pass_rate"], baseline["pass_rate"]),
        "target_hit_top_k_rate_delta": _delta(
            repaired["target_hit_top_k_rate"],
            baseline["target_hit_top_k_rate"],
        ),
        "target_hit_top_k_count_delta": int(repaired["target_hit_top_k_count"])
        - int(baseline["target_hit_top_k_count"]),
        "passed_query_count_delta": int(repaired["passed_queries"])
        - int(baseline["passed_queries"]),
        "negative_top1_count_delta": int(repaired["negative_top1_count"])
        - int(baseline["negative_top1_count"]),
        "negative_before_target_count_delta": int(
            repaired["negative_before_target_count"]
        )
        - int(baseline["negative_before_target_count"]),
        "deep_miss_remaining_count": int(repaired["evaluated_queries"])
        - int(repaired["target_hit_deep_k_count"]),
    }


def _acceptance(improvement: dict[str, Any]) -> dict[str, bool]:
    return {
        "same_fixture_metric_improved": improvement["pass_rate_delta"] > 0
        and improvement["target_hit_top_k_rate_delta"] > 0,
        "negative_top1_non_regression": improvement["negative_top1_count_delta"] <= 0,
        "negative_before_target_non_regression": (
            improvement["negative_before_target_count_delta"] <= 0
        ),
        "deep_miss_blocker_remaining_recorded": (
            improvement["deep_miss_remaining_count"] >= 0
        ),
        "product_runtime_unchanged": True,
        "public_claim_blocked": True,
    }


def _decision(improvement: dict[str, Any]) -> str:
    acceptance = _acceptance(improvement)
    if not all(acceptance.values()):
        return "hold-repair"
    if improvement["deep_miss_remaining_count"] > 0:
        return "benchmark-only-improved-but-product-blocked"
    return "benchmark-only-candidate-ready-for-approval"


def _next_work_order(improvement: dict[str, Any]) -> list[dict[str, str]]:
    if _decision(improvement) != "benchmark-only-improved-but-product-blocked":
        return [
            {
                "id": "LL-OCRTABLE-RANKING-REPAIR-HOLD",
                "depends_on": "LL-OCRTABLE-NEXT",
                "scope": "keep current OCR/table evidence and audit remaining blocker",
                "acceptance_tests": "same fixture, scans 0, no public claim",
                "risk_level": "medium",
                "rollback_plan": "retain current ranking diagnostic evidence",
            }
        ]
    return [
        {
            "id": "LL-OCRTABLE-RANKING-DEEP-MISS-AUDIT",
            "depends_on": "LL-OCRTABLE-NEXT",
            "scope": "decompose the remaining target_not_in_deep_top_k cases",
            "acceptance_tests": (
                "query ordinal only, no raw query/body, fixture/extractor/embedding "
                "cause separated"
            ),
            "risk_level": "medium",
            "rollback_plan": "keep benchmark-only repair evidence",
        },
        {
            "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
            "depends_on": "LL-OCRTABLE-RANKING-DEEP-MISS-AUDIT",
            "scope": "decide whether product-available rerank can become a default-off POC",
            "acceptance_tests": (
                "explicit approval, same fixture non-regression, search-time cache "
                "source remains forbidden"
            ),
            "risk_level": "high",
            "rollback_plan": "keep product runtime unchanged",
        },
    ]


def _delta(left: float, right: float) -> float:
    return round(float(left) - float(right), 6)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a sanitized benchmark-only OCR/table ranking repair POC."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=DEFAULT_CACHE_SAFETY_GOLDEN.as_posix())
    parser.add_argument("--out")
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--deep-top-k", type=int, default=50)
    parser.add_argument(
        "--tesseract-cmd",
        default=os.getenv("LOCALLENS_TESSERACT_CMD", "tesseract"),
    )
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--tesseract-psm", default="6")
    parser.add_argument("--skip-table", action="store_true")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=_default_blocked_terms_file())
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
