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
from benchmarks.ocrtable_remaining_blocker_audit import run_remaining_blocker_audit


SCHEMA_VERSION = "ocrtable-targeted-repair-spec-v1"
EXTRACTOR_FAMILIES = {"extractor_contract"}
QUERY_EMBEDDING_FAMILIES = {"mixed_query_embedding", "unrecovered_embedding"}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_targeted_repair_spec(
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
        args.out or "ocrtable-targeted-repair-spec",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-targeted-repair-spec",
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


def run_targeted_repair_spec(
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
    audit = run_remaining_blocker_audit(
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
    cases = list(audit.get("cases", []))
    extractor_cases = _cases_for_families(cases, EXTRACTOR_FAMILIES)
    query_embedding_cases = _cases_for_families(cases, QUERY_EMBEDDING_FAMILIES)
    specs = {
        "extractor_preview_repair": _extractor_preview_spec(extractor_cases),
        "query_embedding_repair": _query_embedding_spec(query_embedding_cases),
    }
    acceptance = _acceptance(specs)
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
        "case_identifier_values_recorded": False,
        "tesseract_command_recorded": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "corpus": {
            "pdf_files": int(audit["corpus"]["pdf_files"]),
            "hard_negative_queries": int(audit["corpus"]["hard_negative_queries"]),
            "top_k": top_k,
            "deep_top_k": deep_top_k,
            "max_extra_terms": max_extra_terms,
        },
        "input_audit": {
            "baseline_deep_miss_count": int(audit["baseline_deep_miss_count"]),
            "remaining_blocker_count": int(audit["remaining_blocker_count"]),
            "blocker_family_counts": dict(audit["blocker_family_counts"]),
            "recommended_repair_track_counts": dict(
                audit["recommended_repair_track_counts"]
            ),
        },
        "repair_specs": specs,
        "aggregate": _aggregate(specs),
        "acceptance": acceptance,
        "decision": _decision(acceptance),
        "next_work_order": _next_work_order(specs),
    }


def _cases_for_families(
    cases: list[dict[str, Any]], families: set[str]
) -> list[dict[str, Any]]:
    return [
        case
        for case in cases
        if str(case.get("blocker_family") or "") in families
    ]


def _extractor_preview_spec(cases: list[dict[str, Any]]) -> dict[str, Any]:
    family_counts = _family_counts(cases)
    track_counts = _track_counts(cases)
    return {
        "id": "LL-OCRTABLE-RANKING-EXTRACTOR-PREVIEW-REPAIR-SPEC",
        "status": "specified" if cases else "not_applicable",
        "benchmark_only": True,
        "default_enabled": False,
        "product_runtime_changed": False,
        "case_count": len(cases),
        "blocker_family_counts": family_counts,
        "repair_track_counts": track_counts,
        "candidate_strategy": (
            "measure OCR profile and preview-budget candidates before any product "
            "extractor change"
        ),
        "allowed_signals": [
            "mode",
            "target unit type",
            "preview term count",
            "preview overlap ratio",
            "full unit term count",
            "OCR profile ordinal",
        ],
        "forbidden_inputs": _forbidden_inputs(),
        "measurement_plan": [
            "run same-fixture benchmark-only preview/profile POC",
            "compare target hit deep-k before and after candidate profile",
            "verify negative top1 remains zero",
            "verify product runtime and public claims remain unchanged",
        ],
        "acceptance_tests": [
            "remaining extractor blocker count decreases",
            "negative_top1 remains 0",
            "deep miss count does not regress outside the extractor track",
            "artifact scan 0",
        ],
        "risk_level": "medium",
        "rollback_plan": "keep remaining-blocker audit evidence and leave extractor defaults unchanged",
    }


def _query_embedding_spec(cases: list[dict[str, Any]]) -> dict[str, Any]:
    family_counts = _family_counts(cases)
    track_counts = _track_counts(cases)
    return {
        "id": "LL-OCRTABLE-RANKING-QUERY-EMBEDDING-REPAIR-SPEC",
        "status": "specified" if cases else "not_applicable",
        "benchmark_only": True,
        "default_enabled": False,
        "product_runtime_changed": False,
        "case_count": len(cases),
        "blocker_family_counts": family_counts,
        "repair_track_counts": track_counts,
        "candidate_strategy": (
            "test benchmark-only query normalization and embedding-profile candidates "
            "without product search changes"
        ),
        "allowed_signals": [
            "mode",
            "target unit type",
            "preview term count",
            "preview overlap ratio",
            "negative seen deep-k flag",
            "selected embedding candidate name",
        ],
        "forbidden_inputs": _forbidden_inputs(),
        "measurement_plan": [
            "run query-family coverage POC on the same 120-PDF fixture",
            "measure remaining blocker reduction by blocker family",
            "verify negative top1 remains zero",
            "separate mixed query-contract cases from unrecovered embedding cases",
        ],
        "acceptance_tests": [
            "remaining blocker count decreases",
            "negative_top1 remains 0",
            "product runtime unchanged",
            "artifact scan 0",
        ],
        "risk_level": "high",
        "rollback_plan": "keep embedding coverage POC evidence and leave product query path unchanged",
    }


def _forbidden_inputs() -> list[str]:
    return [
        "query content",
        "document body",
        "stable document identifier",
        "absolute filesystem location",
        "target label as repair input",
        "external provider fallback",
        "search-time cache source",
    ]


def _family_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        sorted(Counter(str(case.get("blocker_family") or "") for case in cases).items())
    )


def _track_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        sorted(
            Counter(
                str(case.get("recommended_repair_track") or "") for case in cases
            ).items()
        )
    )


def _aggregate(specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total_cases = sum(int(spec["case_count"]) for spec in specs.values())
    specified_specs = [
        name for name, spec in specs.items() if str(spec["status"]) == "specified"
    ]
    return {
        "specified_spec_count": len(specified_specs),
        "remaining_cases_covered_by_specs": total_cases,
        "specified_specs": specified_specs,
        "product_runtime_changed": False,
        "product_repair_approved": False,
        "public_quality_claim_allowed": False,
        "recommended_next": _recommended_next(specified_specs),
    }


def _recommended_next(specified_specs: list[str]) -> str:
    if not specified_specs:
        return "no targeted repair spec required; revisit product POC decision"
    return "run benchmark-only targeted repair POCs before product POC decision"


def _acceptance(specs: dict[str, dict[str, Any]]) -> dict[str, bool]:
    return {
        "at_least_one_targeted_spec": any(
            str(spec["status"]) == "specified" for spec in specs.values()
        ),
        "product_runtime_unchanged": all(
            not bool(spec["product_runtime_changed"]) for spec in specs.values()
        ),
        "default_off": all(not bool(spec["default_enabled"]) for spec in specs.values()),
        "forbidden_inputs_declared": all(
            bool(spec["forbidden_inputs"]) for spec in specs.values()
        ),
        "public_claim_blocked": True,
    }


def _decision(acceptance: dict[str, bool]) -> str:
    if not all(acceptance.values()):
        return "hold-targeted-repair-spec"
    return "targeted-repair-spec-ready-benchmark-poc-required"


def _next_work_order(specs: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    work: list[dict[str, str]] = []
    if specs["extractor_preview_repair"]["case_count"]:
        work.append(
            {
                "id": "LL-OCRTABLE-RANKING-EXTRACTOR-PREVIEW-REPAIR-POC",
                "depends_on": "LL-OCRTABLE-RANKING-EXTRACTOR-PREVIEW-REPAIR-SPEC",
                "scope": "run benchmark-only OCR preview/profile repair POC",
                "acceptance_tests": "extractor blocker decreases, negative_top1 0, scans 0",
                "risk_level": "high",
                "rollback_plan": "keep extractor repair spec evidence only",
            }
        )
    if specs["query_embedding_repair"]["case_count"]:
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write sanitized targeted OCR/table repair specifications."
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
