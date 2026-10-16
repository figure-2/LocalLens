from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
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


SCHEMA_VERSION = "ocrtable-remaining-blocker-audit-v1"
EMBEDDING_FAMILIES = {"embedding", "embedding_or_query_embedding"}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_remaining_blocker_audit(
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
        args.out or "ocrtable-remaining-blocker-audit",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-remaining-blocker-audit",
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


def run_remaining_blocker_audit(
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
    coverage = run_embedding_coverage_diagnostic(
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
    selected = str(coverage["aggregate"]["best_deep_recovery_candidate"])
    cases = _remaining_cases(
        deep_miss=deep_miss,
        coverage=coverage,
        selected_candidate=selected,
    )
    family_counts = Counter(str(case["blocker_family"]) for case in cases)
    track_counts = Counter(str(case["recommended_repair_track"]) for case in cases)
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
        "case_identifier_policy": "ordinal-only",
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
        "selected_embedding_candidate": selected,
        "baseline_deep_miss_count": int(deep_miss["aggregate"]["deep_miss_count"]),
        "remaining_blocker_count": len(cases),
        "blocker_family_counts": dict(sorted(family_counts.items())),
        "recommended_repair_track_counts": dict(sorted(track_counts.items())),
        "cases": cases,
        "acceptance": _acceptance(cases),
        "decision": _decision(cases),
        "next_work_order": _next_work_order(cases),
    }


def _remaining_cases(
    *,
    deep_miss: dict[str, Any],
    coverage: dict[str, Any],
    selected_candidate: str,
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for case in deep_miss.get("cases", []):
        family = str(case.get("cause_family") or "")
        if family not in EMBEDDING_FAMILIES:
            cases.append(
                _base_case(
                    case,
                    blocker_family=family,
                    selected_candidate="not_applicable",
                    selected_candidate_target_hit_deep_k=False,
                    selected_candidate_negative_top1=False,
                    selected_candidate_negative_before_target_count=0,
                )
            )
    for mode_name in sorted(coverage.get("modes", {})):
        for row in coverage["modes"][mode_name].get("coverage_queries", []):
            candidate = row["candidates"][selected_candidate]
            if not bool(candidate["target_hit_deep_k"]):
                cases.append(
                    _base_case(
                        row,
                        blocker_family="unrecovered_embedding",
                        selected_candidate=selected_candidate,
                        selected_candidate_target_hit_deep_k=bool(
                            candidate["target_hit_deep_k"]
                        ),
                        selected_candidate_negative_top1=bool(
                            candidate["negative_top1"]
                        ),
                        selected_candidate_negative_before_target_count=int(
                            candidate["negative_before_target_count"]
                        ),
                    )
                )
    return [
        {
            **case,
            "case_ordinal": ordinal,
        }
        for ordinal, case in enumerate(
            sorted(cases, key=lambda item: (item["blocker_family"], item["mode"])),
            start=1,
        )
    ]


def _base_case(
    row: dict[str, Any],
    *,
    blocker_family: str,
    selected_candidate: str,
    selected_candidate_target_hit_deep_k: bool,
    selected_candidate_negative_top1: bool,
    selected_candidate_negative_before_target_count: int,
) -> dict[str, Any]:
    primary_reason = str(
        row.get("primary_reason") or row.get("deep_miss_primary_reason") or ""
    )
    return {
        "mode": str(row.get("mode") or ""),
        "target_unit_type": str(row.get("target_unit_type") or ""),
        "blocker_family": blocker_family,
        "primary_reason": primary_reason,
        "target_preview_term_count": int(row.get("target_preview_term_count") or 0),
        "target_preview_overlap_ratio": float(
            row.get("target_preview_overlap_ratio") or 0.0
        ),
        "negative_preview_overlap_ratio": float(
            row.get("negative_preview_overlap_ratio") or 0.0
        ),
        "negative_seen_deep_k": bool(row.get("negative_seen_deep_k")),
        "selected_candidate": selected_candidate,
        "selected_candidate_target_hit_deep_k": selected_candidate_target_hit_deep_k,
        "selected_candidate_negative_top1": selected_candidate_negative_top1,
        "selected_candidate_negative_before_target_count": (
            selected_candidate_negative_before_target_count
        ),
        "recommended_repair_track": _recommended_track(blocker_family, primary_reason),
    }


def _recommended_track(blocker_family: str, primary_reason: str) -> str:
    if blocker_family == "extractor_contract":
        return "extractor_preview_or_ocr_profile_repair"
    if blocker_family == "mixed_query_embedding":
        return "separate_query_contract_from_embedding_coverage"
    if blocker_family == "unrecovered_embedding":
        if primary_reason == "target_and_negative_absent_from_deep_k":
            return "query_expansion_or_embedding_profile_repair"
        return "embedding_profile_or_query_embedding_repair"
    return "manual_remaining_blocker_audit"


def _acceptance(cases: list[dict[str, Any]]) -> dict[str, bool]:
    serialized_keys = set()
    for case in cases:
        serialized_keys.update(case.keys())
    return {
        "remaining_blockers_recorded": len(cases) > 0,
        "ordinal_only_cases": not (
            {"query_id", "target_document", "relative_path"} & serialized_keys
        ),
        "query_body_absent": not ({"query", "body", "text"} & serialized_keys),
        "repair_paths_separated": all(
            str(case.get("recommended_repair_track") or "") for case in cases
        ),
        "product_runtime_unchanged": True,
        "public_claim_blocked": True,
    }


def _decision(cases: list[dict[str, Any]]) -> str:
    acceptance = _acceptance(cases)
    if not all(acceptance.values()):
        return "hold-remaining-blocker-audit"
    families = {str(case["blocker_family"]) for case in cases}
    if {"extractor_contract", "mixed_query_embedding"} & families:
        return "targeted-repair-plan-required-before-product-poc"
    if "unrecovered_embedding" in families:
        return "embedding-profile-repair-required-before-product-poc"
    return "remaining-blockers-cleared-product-decision-required"


def _next_work_order(cases: list[dict[str, Any]]) -> list[dict[str, str]]:
    families = {str(case["blocker_family"]) for case in cases}
    work: list[dict[str, str]] = []
    if "extractor_contract" in families:
        work.append(
            {
                "id": "LL-OCRTABLE-RANKING-EXTRACTOR-PREVIEW-REPAIR-SPEC",
                "depends_on": "LL-OCRTABLE-RANKING-REMAINING-BLOCKER-AUDIT",
                "scope": "design benchmark-only extractor preview or OCR profile repair for sparse target preview",
                "acceptance_tests": "same fixture, no raw query/body, deep miss non-regression",
                "risk_level": "medium",
                "rollback_plan": "keep remaining-blocker audit evidence",
            }
        )
    if "mixed_query_embedding" in families or "unrecovered_embedding" in families:
        work.append(
            {
                "id": "LL-OCRTABLE-RANKING-QUERY-EMBEDDING-REPAIR-SPEC",
                "depends_on": "LL-OCRTABLE-RANKING-REMAINING-BLOCKER-AUDIT",
                "scope": "design benchmark-only query normalization or embedding-profile repair for unrecovered blockers",
                "acceptance_tests": "remaining blockers decrease, negative_top1 0, product runtime unchanged",
                "risk_level": "high",
                "rollback_plan": "keep embedding coverage POC evidence",
            }
        )
    work.append(
        {
            "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
            "depends_on": "targeted repair spec or POC",
            "scope": "decide whether any signal can become default-off product POC",
            "acceptance_tests": "explicit approval, same-fixture non-regression, public claim blocked",
            "risk_level": "high",
            "rollback_plan": "leave product runtime unchanged",
        }
    )
    return work


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit remaining OCR/table blockers after embedding coverage POC."
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
