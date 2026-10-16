from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locallens.core.config import Settings
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.search_service import SearchService
from locallens.security.artifact_scan import ArtifactFinding
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact

from benchmarks.ocrtable_extractor_readthrough_live_eval import OCR_DOCS
from benchmarks.ocrtable_extractor_readthrough_live_eval import TABLE_DOCS
from benchmarks.ocrtable_extractor_readthrough_live_eval import _optional_signatures


SCHEMA_VERSION = "ocrtable-cache-safety-live-eval-v1"
DEFAULT_CACHE_SAFETY_GOLDEN = Path("benchmarks/fixtures/golden_pdf_cache_safety_queries.json")
CACHE_SCENARIO_CASES = {
    "search-source-negative": "cache_blob_removed",
    "manifest-removed": "index_manifest_removed",
    "stale-content": "stale_content",
    "corrupt-blob": "corrupt_blob",
}
RAW_REPORT_KEYS = {
    "absolute_path",
    "blob_path",
    "blob_rel_path",
    "cache_blob_path",
    "cache_blob_paths",
    "extracted_text",
    "full_text",
    "ocr_text",
    "private_path",
    "raw_payload",
    "table_text",
    "text",
    "text_preview",
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_cache_safety_live_eval(
        pdf_dir=Path(args.pdf_dir),
        table_doc=args.table_doc,
        ocr_doc=args.ocr_doc,
        cache_safety_golden=Path(args.cache_safety_golden)
        if args.cache_safety_golden
        else None,
        tesseract_cmd=args.tesseract_cmd,
        ocr_lang=args.ocr_lang,
        tesseract_psm=args.tesseract_psm,
        run_table=not args.skip_table,
        run_ocr=not args.skip_ocr,
        run_corpus_cache_eval=args.corpus_cache_eval,
        warm_repeats=args.warm_repeats,
        corpus_doc_limit=args.corpus_doc_limit,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-cache-safety-live-eval",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(report, args.out or "ocrtable-cache-safety-live-eval")
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


def run_cache_safety_live_eval(
    *,
    pdf_dir: Path,
    table_doc: str | None = None,
    ocr_doc: str | None = None,
    cache_safety_golden: Path | None = DEFAULT_CACHE_SAFETY_GOLDEN,
    tesseract_cmd: str = "tesseract",
    ocr_lang: str = "eng",
    tesseract_psm: str = "6",
    run_table: bool = True,
    run_ocr: bool = True,
    run_corpus_cache_eval: bool = False,
    warm_repeats: int = 3,
    corpus_doc_limit: int | None = None,
) -> dict[str, Any]:
    pdf_dir = pdf_dir.resolve()
    binding = _cache_safety_binding(pdf_dir, cache_safety_golden)
    selected_table_doc = table_doc or _selected_doc(binding, "table", TABLE_DOCS[0])
    selected_ocr_doc = ocr_doc or _selected_doc(binding, "ocr", OCR_DOCS[0])
    started = time.perf_counter()
    modes: dict[str, dict[str, Any]] = {}
    if run_table:
        modes["table"] = _run_mode(
            pdf_dir=pdf_dir,
            doc_name=selected_table_doc,
            mode="table",
            case_docs=_case_docs_for_mode(binding, "table"),
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    if run_ocr:
        modes["ocr"] = _run_mode(
            pdf_dir=pdf_dir,
            doc_name=selected_ocr_doc,
            mode="ocr",
            case_docs=_case_docs_for_mode(binding, "ocr"),
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    corpus_cache_eval = (
        _run_corpus_cache_eval(
            pdf_dir=pdf_dir,
            cache_safety_golden=cache_safety_golden,
            warm_repeats=warm_repeats,
            corpus_doc_limit=corpus_doc_limit,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
            run_table=run_table,
            run_ocr=run_ocr,
        )
        if run_corpus_cache_eval
        else {"enabled": False}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "local-live",
        "default_enabled": False,
        "search_time_cache_source_allowed": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "query_binding": binding,
        "modes": modes,
        "corpus_cache_eval": corpus_cache_eval,
        "aggregate": _aggregate_decision(modes, binding, corpus_cache_eval),
    }


def _cache_safety_queries(golden_path: Path | None) -> list[dict[str, Any]]:
    if not golden_path or not golden_path.exists():
        return []
    raw = json.loads(golden_path.read_text(encoding="utf-8"))
    queries = raw.get("queries", raw) if isinstance(raw, dict) else raw
    return [item for item in queries if isinstance(item, dict)]


def _cache_safety_binding(pdf_dir: Path, golden_path: Path | None) -> dict[str, Any]:
    queries = _cache_safety_queries(golden_path)
    if not queries:
        return _unbound_cache_safety()
    scenario_counts: dict[str, int] = {}
    case_bindings: dict[str, dict[str, dict[str, Any]]] = {"table": {}, "ocr": {}}
    target_paths: set[str] = set()
    negative_paths: set[str] = set()
    hard_negative_queries = 0
    invalid_query_count = 0
    query_set_ids: set[str] = set()
    for item in queries:
        if not isinstance(item, dict):
            invalid_query_count += 1
            continue
        query_set_id = str(item.get("query_set_id") or "")
        if query_set_id:
            query_set_ids.add(query_set_id)
        scenario = str(item.get("scenario") or "unbound")
        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
        relevant = item.get("relevant") or []
        if not relevant:
            invalid_query_count += 1
            continue
        target = relevant[0]
        relative_path = str(target.get("relative_path") or "")
        unit_type = str(target.get("unit_type") or "")
        if not relative_path or not unit_type:
            invalid_query_count += 1
            continue
        target_paths.add(relative_path)
        item_negative_paths = [str(path) for path in item.get("negative_paths", [])]
        negative_paths.update(item_negative_paths)
        if scenario == "hard-negative":
            hard_negative_queries += 1
            continue
        case_name = CACHE_SCENARIO_CASES.get(scenario)
        mode = _mode_for_unit_type(unit_type)
        if not case_name or not mode:
            continue
        case_bindings[mode].setdefault(
            case_name,
            _query_binding_entry(item, relative_path, unit_type, scenario),
        )
    target_paths_exist = all((pdf_dir / path).exists() for path in target_paths)
    negative_paths_exist = all((pdf_dir / path).exists() for path in negative_paths)
    lifecycle_cases_bound = all(
        case_name in case_bindings[mode]
        for mode in ("table", "ocr")
        for case_name in (
            "cache_blob_removed",
            "index_manifest_removed",
            "stale_content",
            "corrupt_blob",
        )
    )
    scenario_counts = dict(sorted(scenario_counts.items()))
    return {
        "enabled": True,
        "artifact": golden_path.name if golden_path else None,
        "query_set_ids": sorted(query_set_ids),
        "queries_loaded": len(queries),
        "invalid_query_count": invalid_query_count,
        "scenario_counts": scenario_counts,
        "hard_negative_queries": hard_negative_queries,
        "negative_paths": len(negative_paths),
        "target_documents": len(target_paths),
        "case_bindings": case_bindings,
        "acceptance": {
            "query_set_bound": query_set_ids == {"golden-pdf-cache-safety-v1"},
            "targets_exist": target_paths_exist,
            "negative_paths_exist": negative_paths_exist,
            "lifecycle_cases_bound": lifecycle_cases_bound,
            "invalid_query_count_zero": invalid_query_count == 0,
            "hard_negative_paths_present": hard_negative_queries > 0
            and len(negative_paths) >= hard_negative_queries,
        },
    }


def _run_corpus_cache_eval(
    *,
    pdf_dir: Path,
    cache_safety_golden: Path | None,
    warm_repeats: int,
    corpus_doc_limit: int | None,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
    run_table: bool,
    run_ocr: bool,
) -> dict[str, Any]:
    if warm_repeats < 1:
        raise ValueError("warm_repeats must be at least 1")
    started = time.perf_counter()
    docs = sorted(path.name for path in pdf_dir.glob("*.pdf"))
    if corpus_doc_limit is not None:
        docs = docs[:corpus_doc_limit]
    queries = _cache_safety_queries(cache_safety_golden)
    modes: dict[str, dict[str, Any]] = {}
    if run_table:
        modes["table"] = _run_corpus_mode_cache_eval(
            pdf_dir=pdf_dir,
            docs=docs,
            queries=queries,
            mode="table",
            warm_repeats=warm_repeats,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    if run_ocr:
        modes["ocr"] = _run_corpus_mode_cache_eval(
            pdf_dir=pdf_dir,
            docs=docs,
            queries=queries,
            mode="ocr",
            warm_repeats=warm_repeats,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    return {
        "enabled": True,
        "source_pdf_files": len(docs),
        "warm_repeats": warm_repeats,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "modes": modes,
        "aggregate": _corpus_cache_aggregate(modes),
    }


def _run_corpus_mode_cache_eval(
    *,
    pdf_dir: Path,
    docs: list[str],
    queries: list[dict[str, Any]],
    mode: str,
    warm_repeats: int,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    missing = [name for name in docs if not (pdf_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing fixture PDFs: {', '.join(missing)}")
    with tempfile.TemporaryDirectory(prefix=f"locallens-{mode}-corpus-cache-") as temp_root:
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
        cold_started = time.perf_counter()
        cold = sync.sync_folder(source)
        cold_latency_ms = (time.perf_counter() - cold_started) * 1000
        cold_signatures = _optional_signatures(store.payload_records())

        warm_reports = []
        warm_latencies = []
        warm_signature_matches = []
        for _ in range(warm_repeats):
            _touch_all(source)
            warm_started = time.perf_counter()
            warm = sync.sync_folder(source)
            warm_latencies.append((time.perf_counter() - warm_started) * 1000)
            warm_reports.append(warm)
            warm_signature_matches.append(
                _optional_signatures(store.payload_records()) == cold_signatures
            )
        ranking = _hard_negative_ranking_checks(
            queries=queries,
            mode=mode,
            searcher=lambda query, top_k: SearchService(
                settings,
                store=store,
                manifest=manifest,
            ).search(query, top_k=top_k, modality="text"),
        )
        manifest_cache_entries = manifest.cache_entry_count(state="committed")
        store.close()
    return _corpus_mode_report(
        mode=mode,
        docs=docs,
        cold=cold,
        cold_latency_ms=cold_latency_ms,
        warm_reports=warm_reports,
        warm_latencies=warm_latencies,
        warm_signature_matches=warm_signature_matches,
        cold_optional_units=len(cold_signatures),
        manifest_cache_entries=manifest_cache_entries,
        hard_negative_ranking=ranking,
    )


def _corpus_mode_report(
    *,
    mode: str,
    docs: list[str],
    cold,
    cold_latency_ms: float,
    warm_reports: list[Any],
    warm_latencies: list[float],
    warm_signature_matches: list[bool],
    cold_optional_units: int,
    manifest_cache_entries: int,
    hard_negative_ranking: dict[str, Any],
) -> dict[str, Any]:
    warm_hits = sum(report.cache_result_hits for report in warm_reports)
    warm_misses = sum(report.cache_result_misses for report in warm_reports)
    warm_reads = warm_hits + warm_misses
    warm_hit_rate = warm_hits / warm_reads if warm_reads else 0.0
    cold_dict = asdict(cold)
    warm_dicts = [asdict(report) for report in warm_reports]
    attempted_field = "table_attempted" if mode == "table" else "ocr_attempted"
    succeeded_field = "table_succeeded" if mode == "table" else "ocr_succeeded"
    return {
        "mode": mode,
        "documents": len(docs),
        "actual_extractor_used": cold_dict[attempted_field] > 0,
        "cold_report": cold_dict,
        "warm_reports": warm_dicts,
        "cold_optional_units": cold_optional_units,
        "manifest_cache_entries": manifest_cache_entries,
        "warm_cache_result_hits": warm_hits,
        "warm_cache_result_misses": warm_misses,
        "warm_cache_hit_rate": round(warm_hit_rate, 6),
        "quality_non_regression": all(warm_signature_matches),
        "cold_success_nonzero": cold_dict[succeeded_field] > 0,
        "failures_zero": cold.failed == 0 and all(report.failed == 0 for report in warm_reports),
        "latency_ms": {
            "cold_sync": round(cold_latency_ms, 6),
            "warm_sync_p50": _median(warm_latencies),
            "warm_sync_p95": _p95(warm_latencies),
            "warm_sync_values": [round(value, 6) for value in warm_latencies],
        },
        "cache_effect": {
            "extractor_attempts_skipped_on_warm": all(
                asdict(report)[attempted_field] == 0 for report in warm_reports
            ),
            "warm_hit_rate_is_1": warm_hit_rate == 1.0,
        },
        "hard_negative_ranking": hard_negative_ranking,
    }


def _hard_negative_ranking_checks(
    *,
    queries: list[dict[str, Any]],
    mode: str,
    searcher,
) -> dict[str, Any]:
    mode_queries = [
        item
        for item in queries
        if item.get("scenario") == "hard-negative"
        and _mode_for_unit_type(
            str(((item.get("relevant") or [{}])[0]).get("unit_type") or "")
        )
        == mode
    ]
    details = []
    target_hit_count = 0
    target_within_max_rank_count = 0
    negative_within_top_k_count = 0
    negative_top1_count = 0
    negative_before_target_total = 0
    for item in mode_queries:
        relevant = item.get("relevant") or [{}]
        target = relevant[0]
        top_k = int(item.get("top_k") or 10)
        max_rank = int(target.get("max_rank") or top_k)
        results = searcher(str(item.get("query") or ""), top_k)
        target_rank = _target_rank(results, target)
        negative_ranks = _negative_ranks(results, item.get("negative_paths", []))
        negative_best_rank = min(negative_ranks) if negative_ranks else 0
        negative_before_target = (
            sum(1 for rank in negative_ranks if rank < target_rank)
            if target_rank
            else len(negative_ranks)
        )
        negative_top1 = bool(negative_ranks and min(negative_ranks) == 1)
        target_hit = target_rank > 0
        target_within_max_rank = target_hit and target_rank <= max_rank
        passed = target_within_max_rank and not negative_top1 and negative_before_target == 0
        target_hit_count += int(target_hit)
        target_within_max_rank_count += int(target_within_max_rank)
        negative_within_top_k_count += int(bool(negative_ranks))
        negative_top1_count += int(negative_top1)
        negative_before_target_total += negative_before_target
        details.append(
            {
                "query_id": str(item.get("query_id") or item.get("id") or ""),
                "target_rank": target_rank,
                "target_max_rank": max_rank,
                "negative_best_rank": negative_best_rank,
                "negative_before_target_count": negative_before_target,
                "negative_top1": negative_top1,
                "passed": passed,
            }
        )
    evaluated = len(mode_queries)
    return {
        "evaluated_queries": evaluated,
        "target_hit_count": target_hit_count,
        "target_hit_rate": round(target_hit_count / evaluated, 6) if evaluated else 0.0,
        "target_within_max_rank_count": target_within_max_rank_count,
        "negative_within_top_k_count": negative_within_top_k_count,
        "negative_top1_count": negative_top1_count,
        "negative_before_target_count": negative_before_target_total,
        "passed": bool(evaluated)
        and target_within_max_rank_count == evaluated
        and negative_top1_count == 0
        and negative_before_target_total == 0,
        "details": details,
    }


def _target_rank(results: list[Any], target: dict[str, Any]) -> int:
    for index, result in enumerate(results, start=1):
        if _result_matches_target(result, target):
            return index
    return 0


def _result_matches_target(result: Any, target: dict[str, Any]) -> bool:
    if result.relative_path != target.get("relative_path"):
        return False
    if target.get("unit_type") and result.unit_type != target.get("unit_type"):
        return False
    if target.get("page_no") is not None and result.page_no != target.get("page_no"):
        return False
    for payload_key in ("image_no", "table_no"):
        expected = target.get(payload_key)
        if expected is not None and result.payload.get(payload_key) != expected:
            return False
    return True


def _negative_ranks(results: list[Any], negative_paths: list[str]) -> list[int]:
    negatives = set(str(path) for path in negative_paths)
    return [
        index
        for index, result in enumerate(results, start=1)
        if result.relative_path in negatives
    ]


def _corpus_cache_aggregate(modes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mode_values = list(modes.values())
    cache_live_passed = bool(mode_values) and all(
        mode["actual_extractor_used"]
        and mode["failures_zero"]
        and mode["quality_non_regression"]
        and mode["cache_effect"]["warm_hit_rate_is_1"]
        for mode in mode_values
    )
    ranking_checked = bool(mode_values) and all(
        mode["hard_negative_ranking"]["evaluated_queries"] > 0
        for mode in mode_values
    )
    ranking_passed = ranking_checked and all(
        mode["hard_negative_ranking"]["passed"] for mode in mode_values
    )
    return {
        "cache_live_eval_passed": cache_live_passed,
        "hard_negative_ranking_checked": ranking_checked,
        "hard_negative_ranking_passed": ranking_passed,
        "release_scale_eval_passed": cache_live_passed and ranking_checked,
        "public_performance_claim_allowed": False,
        "public_evidence_decision": "hold",
    }


def _unbound_cache_safety() -> dict[str, Any]:
    return {
        "enabled": False,
        "artifact": None,
        "query_set_ids": [],
        "queries_loaded": 0,
        "invalid_query_count": 0,
        "scenario_counts": {},
        "hard_negative_queries": 0,
        "negative_paths": 0,
        "target_documents": 0,
        "case_bindings": {"table": {}, "ocr": {}},
        "acceptance": {
            "query_set_bound": False,
            "targets_exist": False,
            "negative_paths_exist": False,
            "lifecycle_cases_bound": False,
            "invalid_query_count_zero": True,
            "hard_negative_paths_present": False,
        },
    }


def _query_binding_entry(
    item: dict[str, Any],
    relative_path: str,
    unit_type: str,
    scenario: str,
) -> dict[str, Any]:
    return {
        "query_id": str(item.get("query_id") or item.get("id") or ""),
        "document": relative_path,
        "unit_type": unit_type,
        "scenario": scenario,
        "negative_path_count": len(item.get("negative_paths", [])),
    }


def _mode_for_unit_type(unit_type: str) -> str | None:
    if unit_type == "pdf_table":
        return "table"
    if unit_type == "pdf_ocr_text":
        return "ocr"
    return None


def _selected_doc(binding: dict[str, Any], mode: str, fallback: str) -> str:
    case_docs = _case_docs_for_mode(binding, mode)
    for case_name in (
        "cache_blob_removed",
        "index_manifest_removed",
        "stale_content",
        "corrupt_blob",
    ):
        if case_name in case_docs:
            return case_docs[case_name]
    return fallback


def _case_docs_for_mode(binding: dict[str, Any], mode: str) -> dict[str, str]:
    mode_bindings = binding.get("case_bindings", {}).get(mode, {})
    return {
        case_name: str(entry["document"])
        for case_name, entry in mode_bindings.items()
        if entry.get("document")
    }


def _run_mode(
    *,
    pdf_dir: Path,
    doc_name: str,
    mode: str,
    case_docs: dict[str, str] | None,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    cases = {
        "cache_blob_removed": _run_bound_case(
            _cache_blob_removed_case,
            pdf_dir,
            doc_name,
            "cache_blob_removed",
            mode,
            case_docs or {},
            tesseract_cmd,
            ocr_lang,
            tesseract_psm,
        ),
        "index_manifest_removed": _run_bound_case(
            _index_manifest_removed_case,
            pdf_dir,
            doc_name,
            "index_manifest_removed",
            mode,
            case_docs or {},
            tesseract_cmd,
            ocr_lang,
            tesseract_psm,
        ),
        "stale_content": _run_bound_case(
            _stale_content_case,
            pdf_dir,
            doc_name,
            "stale_content",
            mode,
            case_docs or {},
            tesseract_cmd,
            ocr_lang,
            tesseract_psm,
        ),
        "corrupt_blob": _run_bound_case(
            _corrupt_blob_case,
            pdf_dir,
            doc_name,
            "corrupt_blob",
            mode,
            case_docs or {},
            tesseract_cmd,
            ocr_lang,
            tesseract_psm,
        ),
    }
    return {
        "mode": mode,
        "document": doc_name,
        "case_documents": _case_documents(doc_name, case_docs or {}),
        "cases": cases,
        "acceptance": _mode_acceptance(cases),
    }


def _run_bound_case(
    runner,
    pdf_dir: Path,
    fallback_doc: str,
    case_name: str,
    mode: str,
    case_docs: dict[str, str],
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    doc_name = case_docs.get(case_name, fallback_doc)
    source_pdf = pdf_dir / doc_name
    if not source_pdf.exists():
        raise FileNotFoundError(f"missing fixture PDF: {doc_name}")
    result = runner(source_pdf, doc_name, mode, tesseract_cmd, ocr_lang, tesseract_psm)
    result["bound_document"] = doc_name
    return result


def _case_documents(fallback_doc: str, case_docs: dict[str, str]) -> dict[str, str]:
    return {
        case_name: case_docs.get(case_name, fallback_doc)
        for case_name in (
            "cache_blob_removed",
            "index_manifest_removed",
            "stale_content",
            "corrupt_blob",
        )
    }


def _cache_blob_removed_case(
    source_pdf: Path,
    doc_name: str,
    mode: str,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    with _prepared_case(
        source_pdf,
        doc_name,
        mode,
        tesseract_cmd,
        ocr_lang,
        tesseract_psm,
    ) as ctx:
        baseline = _search_signatures(ctx)
        cache_payload_fields = _search_cache_payload_field_count(ctx)
        blobs = _cache_blob_paths(ctx.settings, ctx.manifest)
        for blob in blobs:
            if blob.exists():
                blob.unlink()
        after = _search_signatures(ctx)
        return {
            "cache_entries_before": len(blobs),
            "cache_blobs_removed": len(blobs),
            "baseline_result_count": len(baseline),
            "after_result_count": len(after),
            "search_results_unchanged": baseline == after and bool(baseline),
            "search_result_cache_payload_fields": cache_payload_fields,
        }


def _index_manifest_removed_case(
    source_pdf: Path,
    doc_name: str,
    mode: str,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    with _prepared_case(
        source_pdf,
        doc_name,
        mode,
        tesseract_cmd,
        ocr_lang,
        tesseract_psm,
    ) as ctx:
        baseline = _search_signatures(ctx)
        cache_entries = ctx.manifest.cache_entry_count(state="committed")
        _remove_index_and_manifest(ctx)
        after = _search_signatures(ctx)
        return {
            "cache_entries_before": cache_entries,
            "baseline_result_count": len(baseline),
            "after_result_count": len(after),
            "cache_recovery_blocked": bool(baseline) and after == [],
        }


def _stale_content_case(
    source_pdf: Path,
    doc_name: str,
    mode: str,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    with _prepared_case(
        source_pdf,
        doc_name,
        mode,
        tesseract_cmd,
        ocr_lang,
        tesseract_psm,
    ) as ctx:
        original = ctx.target.read_bytes()
        ctx.target.write_bytes(original + b"\n% locallens stale safety probe\n")
        started = time.perf_counter()
        report = ctx.sync.sync_folder(ctx.source)
        latency_ms = (time.perf_counter() - started) * 1000
        return {
            "stale_hit_count": report.cache_result_hits,
            "cache_result_misses": report.cache_result_misses,
            "cache_stale_deleted": report.cache_stale_deleted,
            "cache_entries_written": report.cache_entries_written,
            "quality_non_regression": bool(_search_signatures(ctx)),
            "latency_ms": round(latency_ms, 6),
            "sync": _sync_summary(report),
        }


def _corrupt_blob_case(
    source_pdf: Path,
    doc_name: str,
    mode: str,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    with _prepared_case(
        source_pdf,
        doc_name,
        mode,
        tesseract_cmd,
        ocr_lang,
        tesseract_psm,
    ) as ctx:
        blobs = _cache_blob_paths(ctx.settings, ctx.manifest)
        for blob in blobs:
            blob.write_text('{"corrupt": true}\n', encoding="utf-8")
        _touch(ctx.target)
        started = time.perf_counter()
        report = ctx.sync.sync_folder(ctx.source)
        latency_ms = (time.perf_counter() - started) * 1000
        return {
            "cache_result_hits": report.cache_result_hits,
            "cache_result_misses": report.cache_result_misses,
            "cache_corrupt_skipped": report.cache_corrupt_skipped,
            "cache_entries_written": report.cache_entries_written,
            "quality_non_regression": bool(_search_signatures(ctx)),
            "latency_ms": round(latency_ms, 6),
            "sync": _sync_summary(report),
        }


class _PreparedCase:
    def __init__(
        self,
        source_pdf: Path,
        doc_name: str,
        mode: str,
        tesseract_cmd: str,
        ocr_lang: str,
        tesseract_psm: str,
    ):
        self.temp_root = None
        self.store = None
        try:
            self.temp_root = tempfile.TemporaryDirectory(
                prefix=f"locallens-{mode}-safety-"
            )
            self.temp = Path(self.temp_root.name)
            self.source = self.temp / "source"
            self.data_dir = self.temp / "data"
            self.source.mkdir()
            self.target = self.source / doc_name
            self.target.write_bytes(source_pdf.read_bytes())
            self.settings = _settings_for_mode(
                data_dir=self.data_dir,
                mode=mode,
                tesseract_cmd=tesseract_cmd,
                ocr_lang=ocr_lang,
                tesseract_psm=tesseract_psm,
            )
            self.store = QdrantStore(self.settings, in_memory=True)
            self.manifest = ManifestStore(self.settings.manifest_path)
            self.sync = SyncService(
                self.settings,
                store=self.store,
                manifest=self.manifest,
            )
            self.cold_report = self.sync.sync_folder(self.source)
            self.signatures = _optional_signatures(self.store.payload_records())
            if not self.signatures:
                raise RuntimeError(f"{mode} safety fixture produced no optional units")
            if self.cold_report.cache_entries_written <= 0:
                raise RuntimeError(f"{mode} safety fixture produced no cache entry")
            self.query = _query_from_signature(self.signatures[0])
        except Exception:
            self._cleanup()
            raise

    def __enter__(self) -> "_PreparedCase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        if self.store is not None:
            self.store.close()
            self.store = None
        if self.temp_root is not None:
            self.temp_root.cleanup()
            self.temp_root = None


def _prepared_case(
    source_pdf: Path,
    doc_name: str,
    mode: str,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> _PreparedCase:
    return _PreparedCase(source_pdf, doc_name, mode, tesseract_cmd, ocr_lang, tesseract_psm)


def _settings_for_mode(
    *,
    data_dir: Path,
    mode: str,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> Settings:
    if mode == "table":
        return Settings(
            data_dir=data_dir,
            workspace_id="ocrtable-safety-table",
            pdf_table_mode="local-table",
            pdf_ocr_table_cache_mode="read-through",
        )
    if mode == "ocr":
        return Settings(
            data_dir=data_dir,
            workspace_id="ocrtable-safety-ocr",
            pdf_ocr_mode="local-ocr",
            pdf_ocr_lang=ocr_lang,
            tesseract_cmd=tesseract_cmd,
            tesseract_psm=tesseract_psm,
            pdf_ocr_table_cache_mode="read-through",
        )
    raise ValueError(f"unsupported mode: {mode}")


def _search_signatures(ctx: _PreparedCase) -> list[dict[str, Any]]:
    results = _search_results(ctx)
    return [
        {
            "relative_path": result.relative_path,
            "unit_type": result.unit_type,
            "page_no": result.page_no,
            "image_no": result.payload.get("image_no"),
            "table_no": result.payload.get("table_no"),
        }
        for result in results
    ]


def _search_cache_payload_field_count(ctx: _PreparedCase) -> int:
    count = 0
    for result in _search_results(ctx):
        count += sum(1 for key in result.payload if str(key).startswith("cache"))
    return count


def _search_results(ctx: _PreparedCase):
    return SearchService(ctx.settings, store=ctx.store, manifest=ctx.manifest).search(
        ctx.query,
        top_k=5,
        modality="text",
    )


def _query_from_signature(signature: dict[str, Any]) -> str:
    preview = str(signature.get("text_preview") or "").strip()
    if preview:
        return preview
    return str(signature.get("relative_path") or "PDF optional unit")


def _cache_blob_paths(settings: Settings, manifest: ManifestStore) -> list[Path]:
    with sqlite3.connect(manifest.path) as conn:
        rows = conn.execute(
            "SELECT blob_rel_path FROM cache_entries WHERE state='committed'"
        ).fetchall()
    return [settings.cache_dir / str(row[0]) for row in rows]


def _remove_index_and_manifest(ctx: _PreparedCase) -> None:
    with sqlite3.connect(ctx.manifest.path) as conn:
        file_rows = conn.execute(
            "SELECT workspace_id, root_id, relative_path FROM files"
        ).fetchall()
        point_rows = conn.execute("SELECT point_id FROM units").fetchall()
    ctx.store.delete_points([int(row[0]) for row in point_rows])
    for workspace_id, root_id, relative_path in file_rows:
        ctx.manifest.remove_file(str(workspace_id), str(root_id), str(relative_path))


def _mode_acceptance(cases: dict[str, dict[str, Any]]) -> dict[str, bool]:
    return {
        "cache_blob_removal_search_invariant": cases["cache_blob_removed"][
            "search_results_unchanged"
        ],
        "search_payload_cache_fields_zero": cases["cache_blob_removed"][
            "search_result_cache_payload_fields"
        ]
        == 0,
        "cache_cannot_recover_removed_index": cases["index_manifest_removed"][
            "cache_recovery_blocked"
        ],
        "stale_hit_zero": cases["stale_content"]["stale_hit_count"] == 0,
        "corrupt_fallback_counted": (
            cases["corrupt_blob"]["cache_result_hits"] == 0
            and cases["corrupt_blob"]["cache_corrupt_skipped"] > 0
        ),
        "quality_non_regression": (
            cases["stale_content"]["quality_non_regression"]
            and cases["corrupt_blob"]["quality_non_regression"]
        ),
    }


def _aggregate_decision(
    modes: dict[str, dict[str, Any]],
    query_binding: dict[str, Any] | None = None,
    corpus_cache_eval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode_values = list(modes.values())
    modes_passed = bool(mode_values) and all(
        all(mode["acceptance"].values()) for mode in mode_values
    )
    binding_acceptance = (query_binding or {}).get("acceptance", {})
    binding_passed = not query_binding or bool(query_binding.get("enabled")) and all(
        bool(value) for value in binding_acceptance.values()
    )
    passed = modes_passed and binding_passed
    hold_reasons: list[str] = []
    if query_binding and not binding_passed:
        hold_reasons.append("cache-safety query binding acceptance failed")
    corpus_aggregate = (corpus_cache_eval or {}).get("aggregate", {})
    corpus_enabled = bool((corpus_cache_eval or {}).get("enabled"))
    if not corpus_enabled:
        hold_reasons.append("requires release-scale live cache corpus")
    else:
        if int((corpus_cache_eval or {}).get("source_pdf_files") or 0) < 120:
            hold_reasons.append("release-scale corpus is below 120 PDFs")
        if not corpus_aggregate.get("cache_live_eval_passed", False):
            hold_reasons.append("release-scale cache live eval acceptance failed")
        if not corpus_aggregate.get("hard_negative_ranking_checked", False):
            hold_reasons.append("hard-negative ranking checks were not executed")
        elif not corpus_aggregate.get("hard_negative_ranking_passed", False):
            hold_reasons.append("hard-negative ranking checks failed")
    return {
        "safety_live_eval_passed": passed,
        "query_binding_passed": binding_passed,
        "release_scale_cache_eval_passed": corpus_aggregate.get(
            "cache_live_eval_passed",
            False,
        )
        if corpus_enabled
        else False,
        "hard_negative_ranking_checked": corpus_aggregate.get(
            "hard_negative_ranking_checked",
            False,
        )
        if corpus_enabled
        else False,
        "hard_negative_ranking_passed": corpus_aggregate.get(
            "hard_negative_ranking_passed",
            False,
        )
        if corpus_enabled
        else False,
        "public_cache_claim_allowed": False,
        "public_evidence_decision": "hold",
        "hold_reasons": hold_reasons
        or ["public promotion requires explicit release-evidence decision"],
    }


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
            "cache_entries_deleted",
            "cache_stale_deleted",
            "cache_corrupt_skipped",
        )
    }


def _raw_report_key_findings(value: Any, artifact_name: str) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []
    _collect_raw_report_key_findings(value, artifact_name, findings)
    return findings


def _collect_raw_report_key_findings(
    value: Any,
    artifact_name: str,
    findings: list[ArtifactFinding],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_raw_report_key(str(key)):
                findings.append(
                    ArtifactFinding(
                        artifact_name,
                        "raw report field",
                        f"raw-report-field-{key}",
                    )
                )
            _collect_raw_report_key_findings(item, artifact_name, findings)
    elif isinstance(value, list):
        for item in value:
            _collect_raw_report_key_findings(item, artifact_name, findings)


def _is_raw_report_key(key: str) -> bool:
    normalized = key.lower()
    return (
        normalized in RAW_REPORT_KEYS
        or normalized.startswith("raw_")
        or normalized.endswith("_raw")
        or normalized.endswith("_text")
    )


def _touch(path: Path) -> None:
    now_ns = time.time_ns() + 1_000_000_000
    import os

    os.utime(path, ns=(now_ns, now_ns))


def _touch_all(source: Path) -> None:
    now_ns = time.time_ns() + 1_000_000_000
    import os

    for index, path in enumerate(sorted(source.glob("*.pdf"))):
        tick = now_ns + index
        os.utime(path, ns=(tick, tick))


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 6) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95 + 0.999999) - 1))
    return round(ordered[index], 6)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run live OCR/table cache safety checks."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--out")
    parser.add_argument("--cache-safety-golden", default=DEFAULT_CACHE_SAFETY_GOLDEN.as_posix())
    parser.add_argument("--table-doc")
    parser.add_argument("--ocr-doc")
    parser.add_argument("--tesseract-cmd", default="tesseract")
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--tesseract-psm", default="6")
    parser.add_argument("--skip-table", action="store_true")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--corpus-cache-eval", action="store_true")
    parser.add_argument("--warm-repeats", type=int, default=3)
    parser.add_argument("--corpus-doc-limit", type=int)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=_default_blocked_terms_file())
    return parser


def _default_blocked_terms_file() -> str | None:
    path = Path(".locallens/publication-terms.txt")
    if path.exists():
        return path.as_posix()
    return None


if __name__ == "__main__":
    raise SystemExit(main())
