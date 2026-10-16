from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locallens.extractors.pdf_extractor import PdfExtractor
from locallens.ingestion.scanner import Scanner
from locallens.retrieval.search_service import _query_terms
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact

from benchmarks.generate_pdf_expansion import KOREAN_OCR_CASES
from benchmarks.generate_pdf_expansion import OCR_CASES
from benchmarks.ocrtable_cache_safety_live_eval import DEFAULT_CACHE_SAFETY_GOLDEN
from benchmarks.ocrtable_cache_safety_live_eval import _cache_safety_queries
from benchmarks.ocrtable_cache_safety_live_eval import _default_blocked_terms_file
from benchmarks.ocrtable_cache_safety_live_eval import _mode_for_unit_type
from benchmarks.ocrtable_cache_safety_live_eval import _settings_for_mode
from benchmarks.ocrtable_sparse_target_contract_audit import SPARSE_REASON
from benchmarks.ocrtable_sparse_target_contract_audit import _sparse_report_key_findings
from benchmarks.ocrtable_sparse_target_contract_audit import run_sparse_target_contract_audit


SCHEMA_VERSION = "ocrtable-sparse-target-repair-spec-v1"
DEFAULT_PSM_PROFILES = ("", "4", "6", "7", "11", "12")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_sparse_target_repair_spec(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        min_preview_terms=args.min_preview_terms,
        min_query_overlap=args.min_query_overlap,
        tesseract_cmd=args.tesseract_cmd,
        ocr_lang=args.ocr_lang,
        psm_profiles=tuple(args.psm_profile or DEFAULT_PSM_PROFILES),
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-sparse-target-repair-spec",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _sparse_report_key_findings(
            report,
            args.out or "ocrtable-sparse-target-repair-spec",
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


def run_sparse_target_repair_spec(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_CACHE_SAFETY_GOLDEN,
    min_preview_terms: int = 4,
    min_query_overlap: int = 4,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    psm_profiles: tuple[str, ...] = DEFAULT_PSM_PROFILES,
) -> dict[str, Any]:
    if min_preview_terms < 1:
        raise ValueError("min_preview_terms must be positive")
    if min_query_overlap < 1:
        raise ValueError("min_query_overlap must be positive")
    started = time.perf_counter()
    pdf_dir = pdf_dir.resolve()
    contract_report = run_sparse_target_contract_audit(
        pdf_dir=pdf_dir,
        golden_path=golden_path,
        min_preview_terms=min_preview_terms,
        tesseract_cmd=tesseract_cmd,
        ocr_lang=ocr_lang,
        tesseract_psm="6",
        run_table=False,
        run_ocr=True,
    )
    sparse_cases = contract_report["modes"]["ocr"]["sparse_target_queries"]
    queries = [
        item
        for item in _cache_safety_queries(golden_path)
        if item.get("scenario") == "hard-negative"
    ]
    ocr_queries = [
        item
        for item in queries
        if _mode_for_unit_type(
            str(((item.get("relevant") or [{}])[0]).get("unit_type") or "")
        )
        == "ocr"
    ]
    case_reports = [
        _repair_case_report(
            ordinal,
            item,
            pdf_dir=pdf_dir,
            min_preview_terms=min_preview_terms,
            min_query_overlap=min_query_overlap,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            psm_profiles=psm_profiles,
        )
        for ordinal, item in enumerate(ocr_queries, start=1)
        if _is_sparse_ordinal(ordinal, sparse_cases)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "execution_scope": "local-live",
        "default_enabled": False,
        "benchmark_only": True,
        "product_runtime_changed": False,
        "product_repair_approved": False,
        "public_quality_claim_allowed": False,
        "query_content_recorded": False,
        "document_body_recorded": False,
        "stable_document_identifier_recorded": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "corpus": {
            "pdf_files": len(list(pdf_dir.glob("*.pdf"))),
            "fixture_artifact_recorded": False,
            "hard_negative_queries": len(queries),
            "sparse_target_queries": len(case_reports),
            "min_preview_terms": min_preview_terms,
            "min_query_overlap": min_query_overlap,
        },
        "audit_contract": {
            "target_text_used_for_query_expansion": False,
            "target_label_used_for_query_expansion": False,
            "query_content_output": False,
            "document_body_output": False,
            "stable_document_identifier_output": False,
            "repair_implemented": False,
        },
        "case_reports": case_reports,
        "aggregate": _aggregate_repair_spec(case_reports),
        "work_order": _work_order(case_reports),
    }


def _repair_case_report(
    ordinal: int,
    item: dict[str, Any],
    *,
    pdf_dir: Path,
    min_preview_terms: int,
    min_query_overlap: int,
    tesseract_cmd: str,
    ocr_lang: str,
    psm_profiles: tuple[str, ...],
) -> dict[str, Any]:
    target = (item.get("relevant") or [{}])[0]
    query_terms = _query_terms(str(item.get("query") or ""))
    intent_terms = _fixture_intent_terms(str(target.get("relative_path") or ""))
    query_intent_overlap = len(query_terms & intent_terms)
    profile_reports = [
        _ocr_profile_report(
            profile,
            item,
            pdf_dir=pdf_dir,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
        )
        for profile in psm_profiles
    ]
    best_profile = max(
        profile_reports,
        key=lambda row: (
            int(row["passes_preview_contract"]),
            int(row["preview_query_overlap_count"]),
            int(row["passes_full_unit_contract"]),
            int(row["unit_query_overlap_count"]),
            int(row["preview_term_count"]),
        ),
    )
    root_cause = _root_cause(
        intent_term_count=len(intent_terms),
        query_intent_overlap=query_intent_overlap,
        best_profile=best_profile,
        min_preview_terms=min_preview_terms,
        min_query_overlap=min_query_overlap,
    )
    fixture_intent_status = _fixture_intent_status(
        intent_term_count=len(intent_terms),
        query_intent_overlap=query_intent_overlap,
        min_preview_terms=min_preview_terms,
        min_query_overlap=min_query_overlap,
    )
    return {
        "case_ordinal": ordinal,
        "mode": "ocr",
        "target_unit_type": str(target.get("unit_type") or ""),
        "query_term_count": len(query_terms),
        "fixture_intent_term_count": len(intent_terms),
        "fixture_intent_query_overlap_count": query_intent_overlap,
        "fixture_intent_status": fixture_intent_status,
        "fixture_intent_contract_sufficient": (
            fixture_intent_status == "sufficient"
        ),
        "ocr_profile_count": len(profile_reports),
        "ocr_profile_reports": profile_reports,
        "best_profile_summary": {
            "profile_ordinal": best_profile["profile_ordinal"],
            "unit_term_count": best_profile["unit_term_count"],
            "unit_query_overlap_count": best_profile["unit_query_overlap_count"],
            "preview_term_count": best_profile["preview_term_count"],
            "preview_query_overlap_count": best_profile["preview_query_overlap_count"],
            "preview_loss_query_term_count": best_profile[
                "preview_loss_query_term_count"
            ],
            "passes_full_unit_contract": best_profile["passes_full_unit_contract"],
            "passes_preview_contract": best_profile["passes_preview_contract"],
        },
        "root_cause_decision": root_cause,
        "recommended_action": _recommended_action(root_cause),
        "product_runtime_changed": False,
        "product_repair_approved": False,
    }


def _is_sparse_ordinal(ordinal: int, sparse_cases: list[dict[str, Any]]) -> bool:
    return any(int(row["case_ordinal"]) == ordinal for row in sparse_cases)


def _fixture_intent_terms(relative_path: str) -> set[str]:
    for filename, title, detail, _style in [*OCR_CASES, *KOREAN_OCR_CASES]:
        if filename == relative_path:
            return _query_terms(f"{title} {detail}")
    return set()


def _ocr_profile_report(
    profile: str,
    item: dict[str, Any],
    *,
    pdf_dir: Path,
    tesseract_cmd: str,
    ocr_lang: str,
) -> dict[str, Any]:
    target = (item.get("relevant") or [{}])[0]
    query_terms = _query_terms(str(item.get("query") or ""))
    units = _ocr_units_for_single_target(
        pdf_dir=pdf_dir,
        target=item,
        tesseract_cmd=tesseract_cmd,
        ocr_lang=ocr_lang,
        tesseract_psm=profile,
    )
    target_units = [
        unit
        for unit in units
        if unit.unit_type == target.get("unit_type")
        and str(unit.image_no or 0) == str(target.get("image_no") or 0)
    ]
    unit_terms: set[str] = set()
    preview_terms: set[str] = set()
    for unit in target_units:
        unit_terms.update(_query_terms(unit.text))
        preview_terms.update(_query_terms(unit.text_preview))
    profile_ordinal = _profile_ordinal(profile)
    unit_overlap_count = len(query_terms & unit_terms)
    preview_overlap_count = len(query_terms & preview_terms)
    preview_loss_count = len((query_terms & unit_terms) - preview_terms)
    return {
        "profile_ordinal": profile_ordinal,
        "profile_label": _profile_label(profile),
        "target_payload_count": len(target_units),
        "unit_term_count": len(unit_terms),
        "unit_query_overlap_count": unit_overlap_count,
        "unit_query_overlap_ratio": _rate(unit_overlap_count, len(query_terms)),
        "preview_term_count": len(preview_terms),
        "preview_query_overlap_count": preview_overlap_count,
        "preview_query_overlap_ratio": _rate(preview_overlap_count, len(query_terms)),
        "preview_loss_query_term_count": preview_loss_count,
        "passes_full_unit_contract": len(unit_terms) >= 4 and unit_overlap_count >= 4,
        "passes_preview_contract": len(preview_terms) >= 4
        and preview_overlap_count >= 4,
    }


def _ocr_units_for_single_target(
    *,
    pdf_dir: Path,
    target: dict[str, Any],
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> list:
    relative_path = str((target.get("relevant") or [{}])[0].get("relative_path") or "")
    if not relative_path:
        return []
    with tempfile.TemporaryDirectory(prefix="locallens-sparse-repair-spec-") as temp_root:
        temp = Path(temp_root)
        source_dir = temp / "source"
        data_dir = temp / "data"
        source_dir.mkdir()
        (source_dir / relative_path).write_bytes((pdf_dir / relative_path).read_bytes())
        settings = _settings_for_mode(
            data_dir=data_dir,
            mode="ocr",
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
        scanner = Scanner(settings)
        scan_report = scanner.scan(source_dir)
        if not scan_report.files:
            return []
        extractor = PdfExtractor(settings)
        units = extractor.extract(scan_report.files[0])
    return units


def _profile_ordinal(profile: str) -> int:
    if profile == "":
        return 0
    try:
        return int(profile)
    except ValueError:
        return -1


def _profile_label(profile: str) -> str:
    return "default" if profile == "" else "explicit"


def _root_cause(
    *,
    intent_term_count: int,
    query_intent_overlap: int,
    best_profile: dict[str, Any],
    min_preview_terms: int,
    min_query_overlap: int,
) -> str:
    if best_profile["passes_preview_contract"]:
        if intent_term_count == 0:
            return "fixture_intent_catalog_missing_with_extractor_profile_candidate"
        if query_intent_overlap < min_query_overlap:
            return "fixture_query_contract_insufficient_with_extractor_profile_candidate"
        return "extractor_profile_repair_candidate"
    if intent_term_count == 0:
        return "fixture_intent_catalog_missing"
    if intent_term_count < min_preview_terms or query_intent_overlap < min_query_overlap:
        return "fixture_query_contract_insufficient"
    if best_profile["passes_full_unit_contract"]:
        return "extractor_preview_repair_required"
    if int(best_profile["unit_term_count"]) >= min_preview_terms:
        return "extractor_preview_overlap_insufficient"
    return "extractor_output_sparse"


def _fixture_intent_status(
    *,
    intent_term_count: int,
    query_intent_overlap: int,
    min_preview_terms: int,
    min_query_overlap: int,
) -> str:
    if intent_term_count == 0:
        return "intent_catalog_missing"
    if intent_term_count < min_preview_terms or query_intent_overlap < min_query_overlap:
        return "insufficient"
    return "sufficient"


def _recommended_action(root_cause: str) -> str:
    if root_cause == "fixture_intent_catalog_missing_with_extractor_profile_candidate":
        return "repair_fixture_intent_catalog_then_measure_profile_candidate"
    if root_cause == "fixture_query_contract_insufficient_with_extractor_profile_candidate":
        return "repair_fixture_query_contract_then_measure_profile_candidate"
    if root_cause == "fixture_intent_catalog_missing":
        return "repair_fixture_intent_catalog_before_004e2"
    if root_cause == "fixture_query_contract_insufficient":
        return "repair_fixture_or_query_contract_before_004e2"
    if root_cause == "extractor_profile_repair_candidate":
        return "measure_same_fixture_with_candidate_profile_before_runtime_change"
    if root_cause == "extractor_preview_repair_required":
        return "repair_preview_contract_before_runtime_change"
    if root_cause == "extractor_preview_overlap_insufficient":
        return "audit_ocr_quality_before_fixture_repair"
    return "repair_extractor_preview_or_fixture_surface_before_004e2"


def _aggregate_repair_spec(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    decisions: dict[str, int] = {}
    actions: dict[str, int] = {}
    for row in case_reports:
        decisions[row["root_cause_decision"]] = (
            decisions.get(row["root_cause_decision"], 0) + 1
        )
        actions[row["recommended_action"]] = actions.get(row["recommended_action"], 0) + 1
    return {
        "evaluated_sparse_target_queries": len(case_reports),
        "root_cause_decision_counts": dict(sorted(decisions.items())),
        "recommended_action_counts": dict(sorted(actions.items())),
        "product_runtime_changed": False,
        "product_repair_approved": False,
        "ll_corpus_004e2_approval_allowed": False,
        "public_quality_claim_allowed": False,
        "recommended_next": _aggregate_next(case_reports),
    }


def _aggregate_next(case_reports: list[dict[str, Any]]) -> str:
    if not case_reports:
        return "no sparse target cases remain; review 004e2 approval"
    if any(
        row["root_cause_decision"]
        in {
            "extractor_profile_repair_candidate",
            "fixture_intent_catalog_missing_with_extractor_profile_candidate",
            "fixture_query_contract_insufficient_with_extractor_profile_candidate",
        }
        for row in case_reports
    ):
        return "repair fixture intent contract, then run benchmark-only OCR profile repair POC"
    if any(
        row["root_cause_decision"] == "extractor_preview_repair_required"
        for row in case_reports
    ):
        return "write benchmark-only extractor preview repair POC"
    return "repair sparse fixture or extractor surface before 004e2 approval"


def _work_order(case_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not case_reports:
        return []
    return [
        {
            "id": "LL-CORPUS-004E4-REPAIR-POC-APPROVAL",
            "depends_on": "LL-CORPUS-004E4-SPARSE-TARGET-REPAIR-SPEC",
            "scope": "approve benchmark-only sparse-target repair POC",
            "acceptance_tests": (
                "same 120-PDF fixture, no target-derived query terms, no public claim"
            ),
            "risk_level": "medium",
            "rollback_plan": "keep sparse-target hold decision",
        },
        {
            "id": "LL-CORPUS-004E4-REPAIR-POC",
            "depends_on": "LL-CORPUS-004E4-REPAIR-POC-APPROVAL",
            "scope": "run approved repair candidate without product runtime change",
            "acceptance_tests": (
                "preview contract passes, negative_top1 remains 0, cache/safety non-regression"
            ),
            "risk_level": "high",
            "rollback_plan": "discard repair candidate and keep 004E4 evidence",
        },
        {
            "id": "LL-CORPUS-004E2-APPROVAL",
            "depends_on": "LL-CORPUS-004E4-REPAIR-POC",
            "scope": "decide whether same-fixture repair POC can proceed",
            "acceptance_tests": (
                "004E3 and 004E4 blockers closed or explicitly held with caveat"
            ),
            "risk_level": "high",
            "rollback_plan": "keep benchmark-only evidence",
        },
    ]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a sanitized sparse-target repair specification report."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=DEFAULT_CACHE_SAFETY_GOLDEN.as_posix())
    parser.add_argument("--out")
    parser.add_argument("--min-preview-terms", type=int, default=4)
    parser.add_argument("--min-query-overlap", type=int, default=4)
    parser.add_argument("--tesseract-cmd", default="tesseract")
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--psm-profile", action="append", default=[])
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=_default_blocked_terms_file())
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
