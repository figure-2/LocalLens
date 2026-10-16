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
from benchmarks.ocrtable_cache_safety_live_eval import _negative_ranks
from benchmarks.ocrtable_cache_safety_live_eval import _raw_report_key_findings
from benchmarks.ocrtable_cache_safety_live_eval import _settings_for_mode
from benchmarks.ocrtable_cache_safety_live_eval import _target_rank


SCHEMA_VERSION = "ocrtable-hard-negative-audit-v1"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_hard_negative_audit(
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
        args.out or "ocrtable-hard-negative-audit",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(report, args.out or "ocrtable-hard-negative-audit")
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


def run_hard_negative_audit(
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
    if deep_top_k < 10:
        raise ValueError("deep_top_k must be at least 10")
    pdf_dir = pdf_dir.resolve()
    started = time.perf_counter()
    queries = [
        item
        for item in _cache_safety_queries(golden_path)
        if item.get("scenario") == "hard-negative"
    ]
    modes: dict[str, dict[str, Any]] = {}
    if run_table:
        modes["table"] = _run_mode_audit(
            pdf_dir=pdf_dir,
            queries=queries,
            mode="table",
            deep_top_k=deep_top_k,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    if run_ocr:
        modes["ocr"] = _run_mode_audit(
            pdf_dir=pdf_dir,
            queries=queries,
            mode="ocr",
            deep_top_k=deep_top_k,
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "local-live",
        "default_enabled": False,
        "query_content_recorded": False,
        "document_body_recorded": False,
        "api_key_required": False,
        "external_credentials_required": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "corpus": {
            "pdf_files": len(list(pdf_dir.glob("*.pdf"))),
            "golden_artifact": golden_path.name,
            "hard_negative_queries": len(queries),
            "deep_top_k": deep_top_k,
        },
        "modes": modes,
        "aggregate": _aggregate_audit(modes),
    }


def _run_mode_audit(
    *,
    pdf_dir: Path,
    queries: list[dict[str, Any]],
    mode: str,
    deep_top_k: int,
    tesseract_cmd: str,
    ocr_lang: str,
    tesseract_psm: str,
) -> dict[str, Any]:
    docs = sorted(path.name for path in pdf_dir.glob("*.pdf"))
    mode_queries = [
        item
        for item in queries
        if _mode_for_unit_type(
            str(((item.get("relevant") or [{}])[0]).get("unit_type") or "")
        )
        == mode
    ]
    with tempfile.TemporaryDirectory(prefix=f"locallens-{mode}-negative-audit-") as temp_root:
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
        index_started = time.perf_counter()
        sync_report = sync.sync_folder(source)
        index_ms = (time.perf_counter() - index_started) * 1000
        payloads = [record.get("payload") or {} for record in store.payload_records()]
        search = SearchService(settings, store=store, manifest=manifest)
        details = [
            _audit_query(
                item,
                payloads=payloads,
                source_docs=set(docs),
                searcher=lambda query, top_k: search.search(
                    query,
                    top_k=top_k,
                    modality="text",
                ),
                deep_top_k=deep_top_k,
            )
            for item in mode_queries
        ]
        manifest_units = manifest.unit_count()
        store_units = store.count()
        store.close()
    return {
        "mode": mode,
        "documents": len(docs),
        "indexed_units": store_units,
        "manifest_units": manifest_units,
        "sync": _sync_summary(sync_report),
        "index_latency_ms": round(index_ms, 6),
        "queries": details,
        "summary": _mode_summary(details),
    }


def _audit_query(
    item: dict[str, Any],
    *,
    payloads: list[dict[str, Any]],
    source_docs: set[str],
    searcher,
    deep_top_k: int,
) -> dict[str, Any]:
    relevant = item.get("relevant") or [{}]
    target = relevant[0]
    top_k = int(item.get("top_k") or 10)
    max_rank = int(target.get("max_rank") or top_k)
    results_top_k = searcher(str(item.get("query") or ""), top_k)
    results_deep = searcher(str(item.get("query") or ""), deep_top_k)
    target_rank_top_k = _target_rank(results_top_k, target)
    target_rank_deep = _target_rank(results_deep, target)
    negative_ranks_top_k = _negative_ranks(results_top_k, item.get("negative_paths", []))
    negative_ranks_deep = _negative_ranks(results_deep, item.get("negative_paths", []))
    target_doc = str(target.get("relative_path") or "")
    target_unit_count = _target_unit_count(payloads, target)
    target_path_unit_count = _target_path_unit_count(payloads, target_doc, target)
    negative_before_target = (
        sum(1 for rank in negative_ranks_top_k if rank < target_rank_top_k)
        if target_rank_top_k
        else len(negative_ranks_top_k)
    )
    top1_relation = _top1_relation(results_top_k, target, item.get("negative_paths", []))
    bucket = _failure_bucket(
        target_document_exists=target_doc in source_docs,
        target_unit_count=target_unit_count,
        target_rank_top_k=target_rank_top_k,
        target_rank_deep=target_rank_deep,
        max_rank=max_rank,
        negative_before_target=negative_before_target,
    )
    return {
        "query_id": str(item.get("query_id") or item.get("id") or ""),
        "mode": _mode_for_unit_type(str(target.get("unit_type") or "")) or "",
        "target_document": target_doc,
        "target_unit_type": str(target.get("unit_type") or ""),
        "target_document_exists": target_doc in source_docs,
        "target_unit_count": target_unit_count,
        "target_path_unit_count": target_path_unit_count,
        "target_rank_top_k": target_rank_top_k,
        "target_rank_deep_k": target_rank_deep,
        "target_max_rank": max_rank,
        "negative_best_rank_top_k": min(negative_ranks_top_k) if negative_ranks_top_k else 0,
        "negative_best_rank_deep_k": min(negative_ranks_deep) if negative_ranks_deep else 0,
        "negative_before_target_count": negative_before_target,
        "negative_top1": bool(negative_ranks_top_k and min(negative_ranks_top_k) == 1),
        "top1_relation": top1_relation,
        "passed": bucket == "pass",
        "failure_bucket": bucket,
    }


def _target_unit_count(payloads: list[dict[str, Any]], target: dict[str, Any]) -> int:
    return sum(1 for payload in payloads if _payload_matches_target(payload, target, strict=True))


def _target_path_unit_count(
    payloads: list[dict[str, Any]],
    target_doc: str,
    target: dict[str, Any],
) -> int:
    unit_type = str(target.get("unit_type") or "")
    return sum(
        1
        for payload in payloads
        if payload.get("relative_path") == target_doc and payload.get("unit_type") == unit_type
    )


def _payload_matches_target(
    payload: dict[str, Any],
    target: dict[str, Any],
    *,
    strict: bool,
) -> bool:
    if payload.get("relative_path") != target.get("relative_path"):
        return False
    if payload.get("unit_type") != target.get("unit_type"):
        return False
    if not strict:
        return True
    for key in ("page_no", "image_no", "table_no"):
        expected = target.get(key)
        if expected is not None and str(payload.get(key)) != str(expected):
            return False
    return True


def _top1_relation(results: list[Any], target: dict[str, Any], negative_paths: list[str]) -> str:
    if not results:
        return "empty"
    first = results[0]
    if _target_rank([first], target) == 1:
        return "target"
    if first.relative_path in {str(path) for path in negative_paths}:
        return "negative"
    return "other"


def _failure_bucket(
    *,
    target_document_exists: bool,
    target_unit_count: int,
    target_rank_top_k: int,
    target_rank_deep: int,
    max_rank: int,
    negative_before_target: int,
) -> str:
    if not target_document_exists:
        return "target_document_missing"
    if target_unit_count <= 0:
        return "target_unit_not_indexed"
    if target_rank_top_k > 0 and target_rank_top_k <= max_rank and negative_before_target == 0:
        return "pass"
    if negative_before_target > 0:
        return "negative_before_target"
    if target_rank_top_k > max_rank:
        return "target_below_max_rank"
    if target_rank_deep > 0:
        return "target_below_top_k"
    return "target_not_in_deep_top_k"


def _mode_summary(details: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = len(details)
    bucket_counts = Counter(str(item["failure_bucket"]) for item in details)
    target_unit_indexed = sum(1 for item in details if item["target_unit_count"] > 0)
    target_hit_top_k = sum(1 for item in details if item["target_rank_top_k"] > 0)
    target_hit_deep = sum(1 for item in details if item["target_rank_deep_k"] > 0)
    target_within_max_rank = sum(
        1
        for item in details
        if item["target_rank_top_k"] > 0
        and item["target_rank_top_k"] <= item["target_max_rank"]
    )
    negative_top1 = sum(1 for item in details if item["negative_top1"])
    negative_before_target = sum(
        int(item["negative_before_target_count"]) for item in details
    )
    passed = sum(1 for item in details if item["passed"])
    return {
        "evaluated_queries": evaluated,
        "passed_queries": passed,
        "pass_rate": _rate(passed, evaluated),
        "target_unit_indexed_count": target_unit_indexed,
        "target_unit_indexed_rate": _rate(target_unit_indexed, evaluated),
        "target_hit_top_k_count": target_hit_top_k,
        "target_hit_top_k_rate": _rate(target_hit_top_k, evaluated),
        "target_hit_deep_k_count": target_hit_deep,
        "target_hit_deep_k_rate": _rate(target_hit_deep, evaluated),
        "target_within_max_rank_count": target_within_max_rank,
        "negative_top1_count": negative_top1,
        "negative_before_target_count": negative_before_target,
        "failure_bucket_counts": dict(sorted(bucket_counts.items())),
    }


def _aggregate_audit(modes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summaries = [mode["summary"] for mode in modes.values()]
    evaluated = sum(summary["evaluated_queries"] for summary in summaries)
    passed = sum(summary["passed_queries"] for summary in summaries)
    target_unit_indexed = sum(summary["target_unit_indexed_count"] for summary in summaries)
    target_hit_top_k = sum(summary["target_hit_top_k_count"] for summary in summaries)
    target_hit_deep = sum(summary["target_hit_deep_k_count"] for summary in summaries)
    negative_top1 = sum(summary["negative_top1_count"] for summary in summaries)
    negative_before_target = sum(summary["negative_before_target_count"] for summary in summaries)
    buckets = Counter()
    for summary in summaries:
        buckets.update(summary["failure_bucket_counts"])
    return {
        "evaluated_queries": evaluated,
        "passed_queries": passed,
        "pass_rate": _rate(passed, evaluated),
        "target_unit_indexed_count": target_unit_indexed,
        "target_unit_indexed_rate": _rate(target_unit_indexed, evaluated),
        "target_hit_top_k_count": target_hit_top_k,
        "target_hit_top_k_rate": _rate(target_hit_top_k, evaluated),
        "target_hit_deep_k_count": target_hit_deep,
        "target_hit_deep_k_rate": _rate(target_hit_deep, evaluated),
        "negative_top1_count": negative_top1,
        "negative_before_target_count": negative_before_target,
        "failure_bucket_counts": dict(sorted(buckets.items())),
        "public_quality_claim_allowed": False,
        "recommended_next": _recommended_next(buckets),
    }


def _recommended_next(buckets: Counter[str]) -> str:
    if buckets.get("target_unit_not_indexed", 0) > 0:
        return "audit extractor target-unit contract before ranking repair"
    if buckets.get("target_not_in_deep_top_k", 0) > 0:
        return "audit query contract and embedding/rerank alignment before corpus expansion"
    if buckets.get("target_below_top_k", 0) or buckets.get("target_below_max_rank", 0):
        return "consider benchmark-only rerank diagnostic before product ranking change"
    if buckets.get("negative_before_target", 0):
        return "audit distractor specificity and ranking boost before repair"
    return "hold public claim and proceed only after explicit repair decision"


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
        )
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit OCR/table hard-negative ranking failures without raw query output."
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
