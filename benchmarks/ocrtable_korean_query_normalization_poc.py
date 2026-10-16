from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.korean_query_normalizer import (
    KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL,
    KOCR_QUERY_NORMALIZATION_OFF,
)
from locallens.retrieval.search_service import SearchService
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact

from benchmarks.ocrtable_cache_safety_live_eval import _default_blocked_terms_file
from benchmarks.ocrtable_cache_safety_live_eval import _raw_report_key_findings
from benchmarks.ocrtable_korean_harder_fixture_poc import DEFAULT_KOREAN_GOLDEN
from benchmarks.ocrtable_korean_harder_fixture_poc import HARDER_VARIANTS
from benchmarks.ocrtable_korean_harder_fixture_poc import _evaluate_items
from benchmarks.ocrtable_korean_harder_fixture_poc import _harder_items
from benchmarks.ocrtable_korean_harder_fixture_poc import _improvement
from benchmarks.ocrtable_korean_harder_fixture_poc import _load_korean_queries
from benchmarks.ocrtable_korean_harder_fixture_poc import _settings_for_korean_ocr
from benchmarks.ocrtable_korean_harder_fixture_poc import _sync_summary


SCHEMA_VERSION = "ocrtable-korean-query-normalization-poc-v1"
PRODUCT_OFF = "product_off"
PRODUCT_ALIAS_BACKFILL = "product_alias_backfill"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_korean_query_normalization_poc(
        pdf_dir=Path(args.pdf_dir),
        golden_path=Path(args.golden),
        tesseract_cmd=args.tesseract_cmd,
        tessdata_dir=args.tessdata_dir,
        ocr_lang=args.ocr_lang,
        tesseract_psm=args.tesseract_psm,
        require_semantic_backend=args.require_semantic_backend,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-korean-query-normalization-poc",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    findings.extend(
        _raw_report_key_findings(
            report,
            args.out or "ocrtable-korean-query-normalization-poc",
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


def run_korean_query_normalization_poc(
    *,
    pdf_dir: Path,
    golden_path: Path = DEFAULT_KOREAN_GOLDEN,
    tesseract_cmd: str = "tesseract",
    tessdata_dir: str = "",
    ocr_lang: str = "kor",
    tesseract_psm: str = "6",
    require_semantic_backend: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    run = _run_product_path_poc(
        pdf_dir=pdf_dir,
        golden_path=golden_path,
        tesseract_cmd=tesseract_cmd,
        tessdata_dir=tessdata_dir,
        ocr_lang=ocr_lang,
        tesseract_psm=tesseract_psm,
        require_semantic_backend=require_semantic_backend,
    )
    original_off = run["candidate_summaries"][PRODUCT_OFF]["original"]
    harder_off = run["candidate_summaries"][PRODUCT_OFF]["harder"]
    original_alias = run["candidate_summaries"][PRODUCT_ALIAS_BACKFILL]["original"]
    harder_alias = run["candidate_summaries"][PRODUCT_ALIAS_BACKFILL]["harder"]
    original_improvement = _improvement(original_alias, original_off)
    harder_improvement = _improvement(harder_alias, harder_off)
    acceptance = _acceptance(
        original_off=original_off,
        original_alias=original_alias,
        harder_off=harder_off,
        harder_alias=harder_alias,
        harder_improvement=harder_improvement,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "local-live",
        "product_path_poc": True,
        "benchmark_only": False,
        "default_enabled": False,
        "product_default_changed": False,
        "product_runtime_changed": True,
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
            "normalization_modes": [
                KOCR_QUERY_NORMALIZATION_OFF,
                KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL,
            ],
            "normalizer_scope": "text-search-embedding-and-text-lexical-rerank-only",
            "image_query_unchanged": True,
            "table_rerank_query_unchanged": True,
            "external_reranker_query_unchanged": True,
        },
        "indexed_units": run["indexed_units"],
        "manifest_units": run["manifest_units"],
        "sync": run["sync"],
        "index_latency_ms": run["index_latency_ms"],
        "variant_counts": run["variant_counts"],
        "candidate_summaries": run["candidate_summaries"],
        "improvement_vs_product_off": {
            "original": original_improvement,
            "harder": harder_improvement,
        },
        "acceptance": acceptance,
        "decision": _decision(acceptance),
        "next_work_order": _next_work_order(acceptance),
    }


def _run_product_path_poc(
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
    with tempfile.TemporaryDirectory(prefix="locallens-kocr-normalizer-poc-") as temp_root:
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
        settings = replace(
            settings,
            workspace_id="ocrtable-korean-query-normalization-poc",
            kocr_query_normalization_mode=KOCR_QUERY_NORMALIZATION_OFF,
        )
        store = QdrantStore(settings, in_memory=True)
        manifest = ManifestStore(settings.manifest_path)
        sync = SyncService(settings, store=store, manifest=manifest)
        index_started = time.perf_counter()
        sync_report = sync.sync_folder(source)
        index_ms = (time.perf_counter() - index_started) * 1000
        search_off = SearchService(settings, store=store, manifest=manifest)
        alias_settings = replace(
            search_off.settings,
            kocr_query_normalization_mode=KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL,
        )
        search_alias = SearchService(alias_settings, store=store, manifest=manifest)
        candidate_summaries = {
            PRODUCT_OFF: {
                "original": _evaluate_items(
                    original_items,
                    searcher=lambda query: search_off.search(
                        query,
                        top_k=10,
                        modality="text",
                    ),
                    query_transform=lambda query: query,
                ),
                "harder": _evaluate_items(
                    harder_items,
                    searcher=lambda query: search_off.search(
                        query,
                        top_k=10,
                        modality="text",
                    ),
                    query_transform=lambda query: query,
                ),
            },
            PRODUCT_ALIAS_BACKFILL: {
                "original": _evaluate_items(
                    original_items,
                    searcher=lambda query: search_alias.search(
                        query,
                        top_k=10,
                        modality="text",
                    ),
                    query_transform=lambda query: query,
                ),
                "harder": _evaluate_items(
                    harder_items,
                    searcher=lambda query: search_alias.search(
                        query,
                        top_k=10,
                        modality="text",
                    ),
                    query_transform=lambda query: query,
                ),
            },
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
        "variant_counts": _variant_counts(harder_items),
        "candidate_summaries": candidate_summaries,
    }


def _acceptance(
    *,
    original_off: dict[str, Any],
    original_alias: dict[str, Any],
    harder_off: dict[str, Any],
    harder_alias: dict[str, Any],
    harder_improvement: dict[str, Any],
) -> dict[str, bool]:
    return {
        "default_off_preserved": True,
        "original_recall_at_5_non_regression": float(original_alias["recall_at_5"])
        >= float(original_off["recall_at_5"]),
        "original_mrr_at_10_non_regression": float(original_alias["mrr_at_10"])
        >= float(original_off["mrr_at_10"]),
        "harder_queries_recorded": int(harder_off["evaluated_queries"]) >= 50,
        "harder_recall_at_5_gate": float(harder_alias["recall_at_5"]) >= 0.95,
        "harder_mrr_at_10_gate": float(harder_alias["mrr_at_10"]) >= 0.85,
        "harder_top1_gate": float(harder_alias["top1_accuracy"]) >= 0.85,
        "harder_miss_count_non_regression": int(
            harder_improvement["miss_at_5_count_delta"]
        )
        <= 0,
        "product_scope_limited": True,
        "public_claim_blocked": True,
    }


def _decision(acceptance: dict[str, bool]) -> str:
    if all(acceptance.values()):
        return "default-off-kocr-query-normalization-candidate-ready-private"
    return "hold-default-off-kocr-query-normalization-poc"


def _next_work_order(acceptance: dict[str, bool]) -> list[dict[str, str]]:
    if all(acceptance.values()):
        return [
            {
                "id": "LL-OCRTABLE-007-KOCR-QUERY-NORMALIZATION-COMMIT",
                "depends_on": "LL-OCRTABLE-007-KOCR-QUERY-NORMALIZATION-POC",
                "scope": "review and commit the default-off KOCR query normalization POC",
                "acceptance_tests": "pytest pass, scans 0, diff reviewed",
                "risk_level": "low",
                "rollback_plan": "revert normalizer, settings, product POC harness, and tests before commit",
            },
            {
                "id": "LL-OCRTABLE-010-PUBLIC-EVIDENCE-DECIDE",
                "depends_on": "LL-OCRTABLE-007-KOCR-QUERY-NORMALIZATION-POC",
                "scope": "decide whether private KOCR normalization evidence can be promoted to public evidence",
                "acceptance_tests": "docs, claims, evidence, and release gate pass together",
                "risk_level": "medium",
                "rollback_plan": "keep evidence private and public claim unchanged",
            },
        ]
    return [
        {
            "id": "LL-OCRTABLE-007-KOCR-QUERY-NORMALIZATION-HOLD",
            "depends_on": "LL-OCRTABLE-007-KOCR-QUERY-NORMALIZATION-POC",
            "scope": "record why default-off KOCR query normalization did not pass product POC acceptance",
            "acceptance_tests": "hold reason and failed acceptance fields recorded",
            "risk_level": "medium",
            "rollback_plan": "keep current Korean OCR evidence",
        }
    ]


def _variant_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        variant = str(item.get("variant_type") or "")
        counts[variant] = counts.get(variant, 0) + 1
    return dict(sorted(counts.items()))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure default-off KOCR query normalization through the product "
            "SearchService path without recording raw query or document content."
        )
    )
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--golden", default=str(DEFAULT_KOREAN_GOLDEN))
    parser.add_argument("--out")
    parser.add_argument("--tesseract-cmd", default="tesseract")
    parser.add_argument("--tessdata-dir", default="")
    parser.add_argument("--ocr-lang", default="kor")
    parser.add_argument("--tesseract-psm", default="6")
    parser.add_argument("--require-semantic-backend", action="store_true")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument(
        "--blocked-terms-file",
        default=_default_blocked_terms_file(),
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
