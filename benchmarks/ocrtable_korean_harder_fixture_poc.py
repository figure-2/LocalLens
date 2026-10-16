from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locallens.core.config import Settings
from locallens.core.types import SearchResult
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.korean_query_normalizer import (
    KOREAN_TO_ENGLISH_ALIAS,
    normalize_korean_ocr_query,
)
from locallens.retrieval.search_service import SearchService
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact

from benchmarks.ocrtable_cache_safety_live_eval import _default_blocked_terms_file
from benchmarks.ocrtable_cache_safety_live_eval import _raw_report_key_findings
from benchmarks.ocrtable_cache_safety_live_eval import _target_rank


SCHEMA_VERSION = "ocrtable-korean-harder-fixture-poc-v1"
DEFAULT_KOREAN_GOLDEN = Path("benchmarks/fixtures/golden_pdf_ocr_korean_queries.json")
HARDER_VARIANTS = ("compact_korean", "syllable_spaced", "english_alias")
REFERENCE_CANDIDATE = "harder_as_is"
REPAIR_CANDIDATE = "alias_backfill"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_korean_harder_fixture_poc(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        min_original_recall_at_5=args.min_original_recall_at_5,
        tesseract_cmd=args.tesseract_cmd,
        tessdata_dir=args.tessdata_dir,
        ocr_lang=args.ocr_lang,
        tesseract_psm=args.tesseract_psm,
        require_semantic_backend=args.require_semantic_backend,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-korean-harder-fixture-poc",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-korean-harder-fixture-poc",
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


def run_korean_harder_fixture_poc(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_KOREAN_GOLDEN,
    min_original_recall_at_5: float = 0.95,
    tesseract_cmd: str = "tesseract",
    tessdata_dir: str = "",
    ocr_lang: str = "kor",
    tesseract_psm: str = "6",
    require_semantic_backend: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    run = _run_korean_harder_fixture(
        pdf_dir=pdf_dir,
        golden_path=golden_path,
        tesseract_cmd=tesseract_cmd,
        tessdata_dir=tessdata_dir,
        ocr_lang=ocr_lang,
        tesseract_psm=tesseract_psm,
        require_semantic_backend=require_semantic_backend,
    )
    original = run["candidate_summaries"]["original_as_is"]
    reference = run["candidate_summaries"][REFERENCE_CANDIDATE]
    candidate = run["candidate_summaries"][REPAIR_CANDIDATE]
    improvement = _improvement(candidate, reference)
    acceptance = _acceptance(
        original=original,
        reference=reference,
        candidate=candidate,
        improvement=improvement,
        min_original_recall_at_5=min_original_recall_at_5,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "local-live",
        "benchmark_only": True,
        "default_enabled": False,
        "product_runtime_changed": False,
        "product_repair_approved": False,
        "public_quality_claim_allowed": False,
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
            "original_korean_queries": run["corpus"]["original_korean_queries"],
            "harder_variant_queries": run["corpus"]["harder_variant_queries"],
            "harder_variant_count": len(HARDER_VARIANTS),
            "harder_variants": list(HARDER_VARIANTS),
        },
        "runtime": {
            "text_embedding_profile": run["runtime"]["text_embedding_profile"],
            "ocr_language": ocr_lang,
            "tesseract_psm": tesseract_psm,
            "tessdata_dir_configured": bool(tessdata_dir),
            "semantic_backend_required": require_semantic_backend,
        },
        "indexed_units": run["indexed_units"],
        "manifest_units": run["manifest_units"],
        "sync": run["sync"],
        "index_latency_ms": run["index_latency_ms"],
        "variant_counts": run["variant_counts"],
        "candidate_summaries": run["candidate_summaries"],
        "harder_variant_summaries": run["harder_variant_summaries"],
        "reference_candidate": REFERENCE_CANDIDATE,
        "repair_candidate": REPAIR_CANDIDATE,
        "improvement_vs_reference": improvement,
        "acceptance": acceptance,
        "decision": _decision(acceptance, improvement),
        "next_work_order": _next_work_order(acceptance, improvement),
    }


def _run_korean_harder_fixture(
    *,
    pdf_dir: Path,
    golden_path: Path,
    tesseract_cmd: str,
    tessdata_dir: str,
    ocr_lang: str,
    tesseract_psm: str,
    require_semantic_backend: bool,
) -> dict[str, Any]:
    pdf_dir = pdf_dir.resolve()
    docs = sorted(path.name for path in pdf_dir.glob("*.pdf"))
    original_items = _load_korean_queries(golden_path)
    harder_items = _harder_items(original_items)
    with tempfile.TemporaryDirectory(prefix="locallens-kocr-harder-poc-") as temp_root:
        temp = Path(temp_root)
        source = temp / "source"
        data_dir = temp / "data"
        source.mkdir()
        for name in docs:
            (source / name).write_bytes((pdf_dir / name).read_bytes())
        settings = _settings_for_korean_ocr(
            data_dir=data_dir,
            tesseract_cmd=tesseract_cmd,
            tessdata_dir=tessdata_dir,
            ocr_lang=ocr_lang,
            tesseract_psm=tesseract_psm,
            require_semantic_backend=require_semantic_backend,
        )
        store = QdrantStore(settings, in_memory=True)
        manifest = ManifestStore(settings.manifest_path)
        sync = SyncService(settings, store=store, manifest=manifest)
        index_started = time.perf_counter()
        sync_report = sync.sync_folder(source)
        index_ms = (time.perf_counter() - index_started) * 1000
        search = SearchService(settings, store=store, manifest=manifest)
        original_summary = _evaluate_items(
            original_items,
            searcher=lambda query: search.search(query, top_k=10, modality="text"),
            query_transform=lambda query: query,
        )
        harder_as_is = _evaluate_items(
            harder_items,
            searcher=lambda query: search.search(query, top_k=10, modality="text"),
            query_transform=lambda query: query,
        )
        harder_repaired = _evaluate_items(
            harder_items,
            searcher=lambda query: search.search(query, top_k=10, modality="text"),
            query_transform=_alias_backfill_query,
        )
        harder_variant_summaries = {
            variant: {
                REFERENCE_CANDIDATE: _evaluate_items(
                    [item for item in harder_items if item["variant_type"] == variant],
                    searcher=lambda query: search.search(query, top_k=10, modality="text"),
                    query_transform=lambda query: query,
                ),
                REPAIR_CANDIDATE: _evaluate_items(
                    [item for item in harder_items if item["variant_type"] == variant],
                    searcher=lambda query: search.search(query, top_k=10, modality="text"),
                    query_transform=_alias_backfill_query,
                ),
            }
            for variant in HARDER_VARIANTS
        }
        manifest_units = manifest.unit_count()
        store_units = store.count()
        text_profile = sync.settings.text_embedding_profile
        store.close()
    return {
        "corpus": {
            "pdf_files": len(docs),
            "original_korean_queries": len(original_items),
            "harder_variant_queries": len(harder_items),
        },
        "indexed_units": store_units,
        "manifest_units": manifest_units,
        "sync": _sync_summary(sync_report),
        "index_latency_ms": round(index_ms, 6),
        "runtime": {"text_embedding_profile": text_profile},
        "variant_counts": dict(
            sorted(Counter(item["variant_type"] for item in harder_items).items())
        ),
        "candidate_summaries": {
            "original_as_is": original_summary,
            REFERENCE_CANDIDATE: harder_as_is,
            REPAIR_CANDIDATE: harder_repaired,
        },
        "harder_variant_summaries": harder_variant_summaries,
    }


def _settings_for_korean_ocr(
    *,
    data_dir: Path,
    tesseract_cmd: str,
    tessdata_dir: str,
    ocr_lang: str,
    tesseract_psm: str,
    require_semantic_backend: bool,
) -> Settings:
    base = Settings.from_env()
    settings = replace(
        base,
        data_dir=data_dir,
        workspace_id="ocrtable-korean-harder-fixture",
        pdf_ocr_mode="local-ocr",
        pdf_ocr_lang=ocr_lang,
        tesseract_cmd=tesseract_cmd,
        tessdata_dir=tessdata_dir,
        tesseract_psm=tesseract_psm,
        pdf_ocr_table_cache_mode="read-through",
    )
    if require_semantic_backend and settings.text_embedding_backend != "sentence-transformers":
        raise ValueError("semantic backend is required for this POC")
    return settings


def _load_korean_queries(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    queries = raw.get("queries", raw) if isinstance(raw, dict) else raw
    return [item for item in queries if _has_korean(str(item.get("query") or ""))]


def _harder_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        query = str(item.get("query") or "")
        for variant in HARDER_VARIANTS:
            transformed = _variant_query(query, variant)
            if not transformed:
                continue
            result.append({**item, "query": transformed, "variant_type": variant})
    return result


def _variant_query(query: str, variant: str) -> str:
    if variant == "compact_korean":
        return re.sub(r"\s+", "", query).strip()
    if variant == "syllable_spaced":
        return _syllable_spaced(query)
    if variant == "english_alias":
        return _english_alias_query(query)
    raise ValueError(f"unsupported KOCR harder query variant: {variant}")


def _syllable_spaced(query: str) -> str:
    parts: list[str] = []
    for term in query.split():
        if _has_korean(term):
            parts.extend(char for char in term if "가" <= char <= "힣")
        else:
            parts.append(term)
    return " ".join(parts)


def _english_alias_query(query: str) -> str:
    return " ".join(KOREAN_TO_ENGLISH_ALIAS.get(token, token) for token in query.split())


def _alias_backfill_query(query: str) -> str:
    return normalize_korean_ocr_query(query, "alias-backfill")


def _evaluate_items(
    items: list[dict[str, Any]],
    *,
    searcher: Callable[[str], list[SearchResult]],
    query_transform: Callable[[str], str],
) -> dict[str, Any]:
    latencies: list[float] = []
    rows = []
    for item in items:
        query = query_transform(str(item.get("query") or ""))
        started = time.perf_counter()
        results = searcher(query)
        latencies.append((time.perf_counter() - started) * 1000)
        target = (item.get("relevant") or [{}])[0]
        rank = _target_rank(results, target)
        rows.append(
            {
                "variant_type": str(item.get("variant_type") or "original"),
                "rank": rank,
                "hit_at_1": rank == 1,
                "recall_at_5": 0 < rank <= 5,
                "mrr_at_10": (1 / rank) if 0 < rank <= 10 else 0.0,
            }
        )
    evaluated = len(rows)
    return {
        "evaluated_queries": evaluated,
        "recall_at_5": _mean(1.0 if row["recall_at_5"] else 0.0 for row in rows),
        "mrr_at_10": _mean(float(row["mrr_at_10"]) for row in rows),
        "top1_accuracy": _mean(1.0 if row["hit_at_1"] else 0.0 for row in rows),
        "top1_failures": sum(1 for row in rows if not row["hit_at_1"]),
        "miss_at_5_count": sum(1 for row in rows if not row["recall_at_5"]),
        "search_latency_ms": {
            "p50": _median(latencies),
            "p95": _p95(latencies),
        },
    }


def _improvement(candidate: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "recall_at_5_delta": _delta(candidate["recall_at_5"], reference["recall_at_5"]),
        "mrr_at_10_delta": _delta(candidate["mrr_at_10"], reference["mrr_at_10"]),
        "top1_accuracy_delta": _delta(
            candidate["top1_accuracy"],
            reference["top1_accuracy"],
        ),
        "miss_at_5_count_delta": int(candidate["miss_at_5_count"])
        - int(reference["miss_at_5_count"]),
        "top1_failures_delta": int(candidate["top1_failures"])
        - int(reference["top1_failures"]),
    }


def _acceptance(
    *,
    original: dict[str, Any],
    reference: dict[str, Any],
    candidate: dict[str, Any],
    improvement: dict[str, Any],
    min_original_recall_at_5: float,
) -> dict[str, bool]:
    return {
        "original_recall_at_5_non_regression": float(original["recall_at_5"])
        >= min_original_recall_at_5,
        "harder_queries_recorded": int(reference["evaluated_queries"]) >= 50,
        "candidate_recall_at_5_non_regression": float(
            improvement["recall_at_5_delta"]
        )
        >= 0.0,
        "candidate_top1_or_mrr_measured": candidate["top1_accuracy"] is not None
        and candidate["mrr_at_10"] is not None,
        "product_runtime_unchanged": True,
        "public_claim_blocked": True,
    }


def _decision(
    acceptance: dict[str, bool],
    improvement: dict[str, Any],
) -> str:
    if not all(acceptance.values()):
        return "hold-kocr-harder-fixture-poc"
    if (
        float(improvement["top1_accuracy_delta"]) > 0
        or float(improvement["mrr_at_10_delta"]) > 0
    ):
        return "benchmark-only-kocr-query-repair-signal-recorded"
    return "kocr-harder-fixture-recorded-no-repair-signal"


def _next_work_order(
    acceptance: dict[str, bool],
    improvement: dict[str, Any],
) -> list[dict[str, str]]:
    if not all(acceptance.values()):
        return [
            {
                "id": "LL-OCRTABLE-007-KOCR-HARDER-FIXTURE-HOLD",
                "depends_on": "LL-OCRTABLE-007-KOCR-HARDER-FIXTURE",
                "scope": "record why the harder KOCR fixture POC did not meet acceptance",
                "acceptance_tests": "private evidence only, public KOCR claim unchanged",
                "risk_level": "medium",
                "rollback_plan": "keep current Korean OCR evidence",
            }
        ]
    if (
        float(improvement["top1_accuracy_delta"]) > 0
        or float(improvement["mrr_at_10_delta"]) > 0
    ):
        return [
            {
                "id": "LL-OCRTABLE-007-KOCR-QUERY-NORMALIZATION-DECIDE",
                "depends_on": "LL-OCRTABLE-007-KOCR-HARDER-FIXTURE",
                "scope": "decide whether alias backfill can become a default-off KOCR query-normalization product POC",
                "acceptance_tests": "explicit approval, same-fixture non-regression, public claim blocked",
                "risk_level": "high",
                "rollback_plan": "keep benchmark-only evidence",
            }
        ]
    return [
        {
            "id": "LL-OCRTABLE-007-KOCR-HARDER-FIXTURE-SCALE-DECIDE",
            "depends_on": "LL-OCRTABLE-007-KOCR-HARDER-FIXTURE",
            "scope": "decide whether to add more KOCR documents or shift back to portfolio/release work",
            "acceptance_tests": "query/corpus count and hold boundary recorded",
            "risk_level": "medium",
            "rollback_plan": "keep current Korean OCR evidence",
        }
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


def _has_korean(value: str) -> bool:
    return any("가" <= char <= "힣" for char in value)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _mean(values) -> float:
    values = list(values)
    return round(sum(values) / len(values), 6) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return round(values[mid], 6)
    return round((values[mid - 1] + values[mid]) / 2, 6)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95 + 0.999999) - 1))
    return round(ordered[index], 6)


def _delta(left: float, right: float) -> float:
    return round(float(left) - float(right), 6)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run benchmark-only Korean OCR harder fixture POC."
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=DEFAULT_KOREAN_GOLDEN.as_posix())
    parser.add_argument("--out")
    parser.add_argument("--min-original-recall-at-5", type=float, default=0.95)
    parser.add_argument("--tesseract-cmd", default="tesseract")
    parser.add_argument("--tessdata-dir", default="")
    parser.add_argument("--ocr-lang", default="kor")
    parser.add_argument("--tesseract-psm", default="6")
    parser.add_argument("--require-semantic-backend", action="store_true")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=_default_blocked_terms_file())
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
