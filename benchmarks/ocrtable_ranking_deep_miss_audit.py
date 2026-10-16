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
from benchmarks.ocrtable_deep_miss_audit import run_deep_miss_audit


SCHEMA_VERSION = "ocrtable-ranking-deep-miss-audit-v1"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_ranking_deep_miss_audit(
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
        args.out or "ocrtable-ranking-deep-miss-audit",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-ranking-deep-miss-audit",
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


def run_ranking_deep_miss_audit(
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
    started = time.perf_counter()
    pdf_dir = pdf_dir.resolve()
    source_docs = {path.name for path in pdf_dir.glob("*.pdf")}
    raw_report = run_deep_miss_audit(
        pdf_dir=pdf_dir,
        golden_path=golden_path,
        deep_top_k=deep_top_k,
        tesseract_cmd=tesseract_cmd,
        ocr_lang=ocr_lang,
        tesseract_psm=tesseract_psm,
        run_table=run_table,
        run_ocr=run_ocr,
    )
    cases = _sanitized_cases(raw_report, source_docs)
    cause_counts = Counter(str(case["cause_family"]) for case in cases)
    classification_counts = Counter(str(case["classification"]) for case in cases)
    reason_counts = Counter(str(case["primary_reason"]) for case in cases)
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
            "pdf_files": raw_report["corpus"]["pdf_files"],
            "hard_negative_queries": raw_report["corpus"]["hard_negative_queries"],
            "deep_top_k": deep_top_k,
        },
        "aggregate": {
            "evaluated_queries": raw_report["aggregate"]["evaluated_queries"],
            "deep_miss_count": len(cases),
            "deep_miss_rate": _rate(
                len(cases),
                int(raw_report["aggregate"]["evaluated_queries"]),
            ),
            "negative_seen_deep_k_count": sum(
                1 for case in cases if case["negative_seen_deep_k"]
            ),
            "cause_family_counts": dict(sorted(cause_counts.items())),
            "classification_counts": dict(sorted(classification_counts.items())),
            "primary_reason_counts": dict(sorted(reason_counts.items())),
        },
        "cases": cases,
        "acceptance": _acceptance(cases),
        "decision": _decision(cases),
        "next_work_order": _next_work_order(cases),
    }


def _sanitized_cases(
    raw_report: dict[str, Any],
    source_docs: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mode_name in sorted(raw_report.get("modes", {})):
        mode = raw_report["modes"][mode_name]
        for row in mode.get("deep_miss_queries", []):
            ordinal = len(rows) + 1
            target_document = str(row.get("target_document") or "")
            target_document_exists = target_document in source_docs
            cause_family = _cause_family(row, target_document_exists)
            rows.append(
                {
                    "case_ordinal": ordinal,
                    "mode": str(row.get("mode") or mode_name),
                    "target_unit_type": str(row.get("target_unit_type") or ""),
                    "source_pdf_exists": target_document_exists,
                    "target_payload_present": int(row.get("target_payload_count") or 0)
                    > 0,
                    "target_preview_term_count": int(
                        row.get("target_preview_term_count") or 0
                    ),
                    "query_term_count": int(row.get("query_term_count") or 0),
                    "target_filename_overlap_ratio": float(
                        row.get("target_filename_overlap_ratio") or 0.0
                    ),
                    "target_preview_overlap_ratio": float(
                        row.get("target_preview_overlap_ratio") or 0.0
                    ),
                    "negative_preview_overlap_ratio": float(
                        row.get("negative_preview_overlap_ratio") or 0.0
                    ),
                    "negative_seen_deep_k": bool(row.get("negative_seen_deep_k")),
                    "classification": str(row.get("classification") or ""),
                    "primary_reason": str(row.get("primary_reason") or ""),
                    "cause_family": cause_family,
                    "recommended_repair_track": _recommended_track(cause_family),
                }
            )
    return rows


def _cause_family(row: dict[str, Any], target_document_exists: bool) -> str:
    reason = str(row.get("primary_reason") or "")
    target_payload_present = int(row.get("target_payload_count") or 0) > 0
    if not target_document_exists:
        return "fixture_contract"
    if not target_payload_present:
        return "extractor_contract"
    if reason == "target_preview_sparse":
        return "extractor_contract"
    if reason == "negative_lexical_signal_stronger":
        return "query_contract"
    if reason == "negative_present_and_target_missing":
        return "mixed_query_embedding"
    if reason == "target_lexically_strong_but_vector_missed":
        return "embedding"
    if reason == "target_and_negative_absent_from_deep_k":
        return "embedding_or_query_embedding"
    return "unclassified"


def _recommended_track(cause_family: str) -> str:
    tracks = {
        "fixture_contract": "fixture_target_contract_repair",
        "extractor_contract": "extractor_preview_or_ocr_profile_repair",
        "query_contract": "query_contract_or_distractor_contract_review",
        "mixed_query_embedding": "separate_query_contract_from_embedding_coverage",
        "embedding": "embedding_profile_or_query_embedding_audit",
        "embedding_or_query_embedding": "query_expansion_or_embedding_coverage_audit",
    }
    return tracks.get(cause_family, "manual_audit")


def _acceptance(cases: list[dict[str, Any]]) -> dict[str, bool]:
    serialized_keys = set()
    for case in cases:
        serialized_keys.update(case.keys())
    return {
        "deep_miss_cases_recorded": len(cases) > 0,
        "ordinal_only_cases": not (
            {"query_id", "target_document", "relative_path"} & serialized_keys
        ),
        "query_body_absent": not ({"query", "body", "text"} & serialized_keys),
        "cause_families_separated": all(
            str(case.get("cause_family") or "") not in {"", "unclassified"}
            for case in cases
        ),
        "product_runtime_unchanged": True,
        "public_claim_blocked": True,
    }


def _decision(cases: list[dict[str, Any]]) -> str:
    acceptance = _acceptance(cases)
    if not all(acceptance.values()):
        return "hold-audit"
    if any(case["cause_family"] in {"embedding", "embedding_or_query_embedding"} for case in cases):
        return "embedding-coverage-blocks-product-rerank"
    if any(case["cause_family"] == "extractor_contract" for case in cases):
        return "extractor-contract-repair-before-product-rerank"
    return "deep-miss-audit-complete-product-decision-required"


def _next_work_order(cases: list[dict[str, Any]]) -> list[dict[str, str]]:
    cause_counts = Counter(str(case["cause_family"]) for case in cases)
    if cause_counts.get("embedding", 0) or cause_counts.get(
        "embedding_or_query_embedding",
        0,
    ):
        return [
            {
                "id": "LL-OCRTABLE-RANKING-EMBEDDING-COVERAGE-POC",
                "depends_on": "LL-OCRTABLE-RANKING-DEEP-MISS-AUDIT",
                "scope": "benchmark-only query expansion or embedding-profile repair for remaining deep misses",
                "acceptance_tests": "deep miss count decreases, negative_top1 0, product runtime unchanged",
                "risk_level": "high",
                "rollback_plan": "keep current benchmark-only ranking repair evidence",
            },
            {
                "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
                "depends_on": "LL-OCRTABLE-RANKING-EMBEDDING-COVERAGE-POC",
                "scope": "decide whether any signal can become a default-off product POC",
                "acceptance_tests": "explicit approval, same-fixture non-regression, public claim blocked",
                "risk_level": "high",
                "rollback_plan": "leave product runtime unchanged",
            },
        ]
    return [
        {
            "id": "LL-OCRTABLE-RANKING-REPAIR-DECIDE",
            "depends_on": "LL-OCRTABLE-RANKING-DEEP-MISS-AUDIT",
            "scope": "decide whether benchmark-only signal can become default-off product POC",
            "acceptance_tests": "explicit approval, same-fixture non-regression, public claim blocked",
            "risk_level": "high",
            "rollback_plan": "leave product runtime unchanged",
        }
    ]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an ordinal-only OCR/table deep-miss audit report."
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
