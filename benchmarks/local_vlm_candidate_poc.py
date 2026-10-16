from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from locallens.benchmarks.runner import (
    _latency_summary,
    _load_golden_queries,
    _quality_metrics,
    _query_result_details,
)
from locallens.core.config import Settings
from locallens.core.types import ExtractionStats, IndexedUnit, SearchResult
from locallens.extractors.pdf_extractor import PdfExtractor
from locallens.extractors.pdf_vlm_adapter import build_local_vlm_captioner
from locallens.ingestion.scanner import Scanner
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="local-vlm-candidate-poc")
    parser.add_argument("folder")
    parser.add_argument("--golden", default=None)
    parser.add_argument("--baseline-report", action="append", default=[])
    parser.add_argument("--out", default=None)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)

    try:
        report = run_local_vlm_candidate_poc(
            folder=Path(args.folder),
            settings=Settings.from_env(),
            golden_path=Path(args.golden) if args.golden else None,
            baseline_reports=[Path(path) for path in args.baseline_report],
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1

    content = json.dumps(report, indent=2)
    findings = scan_text_artifact(
        content,
        args.out or "local-vlm-candidate-poc",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    if findings:
        print(
            json.dumps(
                {
                    "error": "artifact scan failed",
                    "findings": public_findings(findings),
                },
                indent=2,
            )
        )
        return 1
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    print(content)
    return 0


def run_local_vlm_candidate_poc(
    folder: Path,
    settings: Settings,
    golden_path: Path | None = None,
    baseline_reports: list[Path] | None = None,
) -> dict:
    baseline_reports = baseline_reports or []
    scanner = Scanner(settings)
    scan_report = scanner.scan(folder)
    captioner = build_local_vlm_captioner(settings)
    stats = ExtractionStats()
    counts: dict[str, int] = {}
    caption_units: list[IndexedUnit] = []
    started = time.perf_counter()
    for scanned in scan_report.files:
        if scanned.file_type != "pdf":
            continue
        extractor = PdfExtractor(settings)
        units = extractor.extract(scanned)
        _merge_stats(stats, extractor.last_stats)
        for unit in units:
            counts[unit.unit_type] = counts.get(unit.unit_type, 0) + 1
            if unit.unit_type == "pdf_visual_caption":
                caption_units.append(unit)
    elapsed = time.perf_counter() - started
    caption_unit_count = counts.get("pdf_visual_caption", 0)
    locality = captioner.locality.to_payload()
    golden_queries = _load_golden_queries(golden_path) if golden_path else []
    quality = _caption_quality(caption_units, golden_queries)
    quality_passed = _quality_passed(quality)
    has_golden = bool(golden_queries)
    hold_reasons = _hold_reasons(
        settings,
        stats,
        caption_unit_count,
        locality,
        has_golden=has_golden,
        quality_passed=quality_passed,
    )
    hold_status = _hold_status(
        settings=settings,
        stats=stats,
        caption_units=caption_unit_count,
        locality=locality,
        has_golden=has_golden,
        quality_passed=quality_passed,
    )
    baselines = [_baseline_summary(path) for path in baseline_reports if path.exists()]
    return {
        "benchmark_mode": "local-vlm-candidate-poc",
        "fixture": _path_label(folder),
        "golden": _path_label(golden_path) if golden_path else None,
        "unit_contract": "pdf_visual_caption",
        "pdf_vlm_mode": settings.pdf_vlm_mode,
        "candidate": settings.pdf_vlm_model_name or "unconfigured",
        "profile": captioner.profile,
        "locality": locality,
        "files": len(scan_report.files),
        "excluded": len(scan_report.excluded),
        "unit_counts": counts,
        "extraction_seconds": elapsed,
        "sync": asdict(stats),
        "quality": quality,
        "weak_slice_analysis": _weak_slice_analysis(quality),
        "rerank_diagnostic": _caption_rerank_diagnostic(
            caption_units,
            golden_queries,
        ),
        "comparison_baselines": baselines,
        "comparison_decision": _comparison_decision(quality, baselines),
        "hold_status": hold_status,
        "promotion_decision": "candidate-ready" if hold_status == "candidate-ready" else "hold",
        "hold_reasons": hold_reasons,
    }


def _hold_reasons(
    settings: Settings,
    stats: ExtractionStats,
    caption_units: int,
    locality: dict,
    *,
    has_golden: bool,
    quality_passed: bool,
) -> list[str]:
    reasons = []
    if settings.pdf_vlm_mode != "local-vlm":
        reasons.append("pdf_vlm_mode_not_enabled")
    if locality.get("runtime_network_calls") != 0:
        reasons.append("runtime_network_calls_not_zero")
    if locality.get("automatic_model_downloads") != 0:
        reasons.append("automatic_model_downloads_not_zero")
    if locality.get("external_provider_fallbacks") != 0:
        reasons.append("external_provider_fallbacks_not_zero")
    if locality.get("local_cache_or_install_path") not in {
        "configured-local-cache",
        "configured-local-command",
    }:
        reasons.append("local_cache_or_install_path_not_configured")
    if stats.vlm_failed:
        reasons.append("vlm_failures_present")
    if stats.vlm_attempted == 0:
        reasons.append("no_visual_regions_attempted")
    if caption_units == 0:
        reasons.append("no_pdf_visual_caption_units")
    if caption_units > 0 and not has_golden:
        reasons.append("no_caption_golden_queries")
    if has_golden and not quality_passed:
        reasons.append("caption_quality_below_threshold")
    return reasons


def _hold_status(
    *,
    settings: Settings,
    stats: ExtractionStats,
    caption_units: int,
    locality: dict,
    has_golden: bool,
    quality_passed: bool,
) -> str:
    if settings.pdf_vlm_mode != "local-vlm":
        return "hold-unconfigured"
    if locality.get("local_cache_or_install_path") not in {
        "configured-local-cache",
        "configured-local-command",
    }:
        return "hold-unconfigured"
    if (
        locality.get("runtime_network_calls") != 0
        or locality.get("automatic_model_downloads") != 0
        or locality.get("external_provider_fallbacks") != 0
        or stats.vlm_failed
    ):
        return "hold-quality"
    if caption_units == 0:
        return "hold-zero-captions"
    if not has_golden:
        return "hold-no-golden"
    if not quality_passed:
        return "hold-quality"
    return "candidate-ready"


def _merge_stats(target: ExtractionStats, source: ExtractionStats) -> None:
    target.ocr_attempted += source.ocr_attempted
    target.ocr_succeeded += source.ocr_succeeded
    target.ocr_empty += source.ocr_empty
    target.table_attempted += source.table_attempted
    target.table_succeeded += source.table_succeeded
    target.table_empty += source.table_empty
    target.vlm_attempted += source.vlm_attempted
    target.vlm_succeeded += source.vlm_succeeded
    target.vlm_empty += source.vlm_empty
    target.vlm_failed += source.vlm_failed


def _caption_quality(caption_units: list[IndexedUnit], golden_queries: list[dict]) -> dict:
    if not caption_units:
        return {
            "status": "not-evaluated",
            "evaluated_queries": 0,
            "recall_at_5": None,
            "recall_at_10": None,
            "mrr_at_10": None,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "query_results": [],
        }
    if not golden_queries:
        return {
            "status": "requires-golden-set",
            "evaluated_queries": 0,
            "recall_at_5": None,
            "recall_at_10": None,
            "mrr_at_10": None,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "query_results": [],
        }
    latencies = []
    result_sets = []
    for query in golden_queries:
        started = time.perf_counter()
        result_sets.append(
            _rank_caption_units(
                caption_units,
                query["query"],
                top_k=int(query.get("top_k", 10)),
            )
        )
        latencies.append((time.perf_counter() - started) * 1000)
    metrics = _quality_metrics(golden_queries, result_sets)
    latency = _latency_summary(latencies)
    return {
        "status": "evaluated",
        "evaluated_queries": metrics["evaluated_queries"],
        "recall_at_5": metrics["recall_at_5"],
        "recall_at_10": metrics["recall_at_10"],
        "mrr_at_10": metrics["mrr_at_10"],
        "recall_at_1": metrics["recall_at_1"],
        "hit_at_1": metrics["hit_at_1"],
        "ndcg_at_10": metrics["ndcg_at_10"],
        "top1_accuracy": metrics["top1_accuracy"],
        "quality_slices": metrics["quality_slices"],
        "p50_ms": latency["p50"],
        "p95_ms": latency["p95"],
        "p99_ms": latency["p99"],
        "query_results": _query_result_details(golden_queries, result_sets),
    }


def _weak_slice_analysis(quality: dict) -> dict:
    if quality.get("status") != "evaluated":
        return {
            "status": "not-evaluated",
            "evaluated_queries": 0,
            "top1_failure_count": 0,
            "weak_slices": [],
            "top1_failure_examples": [],
            "repair_targets": [],
        }
    weak_slices = _weak_slices(quality.get("quality_slices", {}))
    failures = [
        _top1_failure_example(row)
        for row in quality.get("query_results", [])
        if row.get("first_hit_rank") != 1
    ]
    return {
        "status": "evaluated",
        "evaluated_queries": quality.get("evaluated_queries", 0),
        "top1_failure_count": len(failures),
        "weak_slices": weak_slices,
        "top1_failure_examples": failures,
        "repair_targets": _repair_targets(weak_slices),
    }


def _weak_slices(slices: dict[str, dict]) -> list[dict]:
    weak = []
    for name, summary in slices.items():
        if not name.startswith("tag:"):
            continue
        top1 = float(summary.get("top1_accuracy") or 0.0)
        mrr = float(summary.get("mrr_at_10") or 0.0)
        if top1 >= 1.0 and mrr >= 0.85:
            continue
        weak.append(
            {
                "slice": name,
                "evaluated_queries": summary.get("evaluated_queries", 0),
                "top1_accuracy": top1,
                "recall_at_5": summary.get("recall_at_5"),
                "mrr_at_10": mrr,
            }
        )
    return sorted(
        weak,
        key=lambda row: (
            row["top1_accuracy"],
            row["mrr_at_10"],
            str(row["slice"]),
        ),
    )


def _top1_failure_example(row: dict) -> dict:
    top_results = row.get("top_results", [])
    top1 = top_results[0] if top_results else {}
    expected_paths = [str(path) for path in row.get("expected_paths", [])]
    expected = _expected_result(top_results, expected_paths)
    top_score = top1.get("score")
    expected_score = expected.get("score") if expected else None
    return {
        "id": row.get("id"),
        "tags": row.get("tags", []),
        "expected_paths": expected_paths,
        "first_hit_rank": row.get("first_hit_rank"),
        "top1_path": top1.get("relative_path"),
        "top1_score": top_score,
        "expected_best_rank": expected.get("rank") if expected else None,
        "expected_best_score": expected_score,
        "score_gap": _score_gap(top_score, expected_score),
        "failure_mode": _failure_mode(row, top1, expected),
    }


def _expected_result(top_results: list[dict], expected_paths: list[str]) -> dict:
    matches = [
        result
        for result in top_results
        if str(result.get("relative_path")) in set(expected_paths)
    ]
    if not matches:
        return {}
    return sorted(matches, key=lambda result: int(result.get("rank") or 9999))[0]


def _score_gap(top_score: object, expected_score: object) -> float | None:
    if top_score is None or expected_score is None:
        return None
    return round(float(top_score) - float(expected_score), 6)


def _failure_mode(row: dict, top1: dict, expected: dict) -> str:
    if not top1:
        return "no-results"
    if not expected:
        return "expected-not-in-topk"
    if row.get("first_hit_rank") == 1:
        return "top1-hit"
    gap = _score_gap(top1.get("score"), expected.get("score"))
    if gap == 0:
        return "score-tie"
    if gap is not None and gap > 0:
        return "lower-caption-score"
    return "ranked-below-top1"


def _repair_targets(weak_slices: list[dict]) -> list[dict]:
    return [
        {
            "slice": row["slice"],
            "suggested_action": _slice_action(str(row["slice"])),
        }
        for row in weak_slices
    ]


def _slice_action(slice_name: str) -> str:
    if any(term in slice_name for term in ("multilingual", "korean", "english")):
        return "preserve visible text and language markers in captions"
    if "receipt" in slice_name:
        return "preserve document type and receipt-specific fields in captions"
    if "scanned-like" in slice_name:
        return "separate scanned-page and scanned-receipt visual descriptions"
    return "add caption-specific contrast examples or compare a second local model"


def _caption_rerank_diagnostic(
    caption_units: list[IndexedUnit],
    golden_queries: list[dict],
) -> dict:
    if not caption_units or not golden_queries:
        return {
            "status": "not-evaluated",
            "product_runtime_change": False,
            "decision": "hold",
        }
    baseline_sets = [
        _rank_caption_units(
            caption_units,
            query["query"],
            top_k=int(query.get("top_k", 10)),
        )
        for query in golden_queries
    ]
    candidate_sets = [
        _rank_caption_units(
            caption_units,
            query["query"],
            top_k=int(query.get("top_k", 10)),
            scorer="idf",
        )
        for query in golden_queries
    ]
    baseline = _metric_subset(_quality_metrics(golden_queries, baseline_sets))
    candidate = _metric_subset(_quality_metrics(golden_queries, candidate_sets))
    delta = _metric_delta(baseline, candidate)
    improved = delta["mrr_at_10"] > 0 or delta["top1_accuracy"] > 0
    return {
        "status": "evaluated",
        "name": "benchmark-caption-idf-rerank-v1",
        "product_runtime_change": False,
        "input": "query text and generated caption text only",
        "label_usage": "golden labels are used only for scoring",
        "baseline": baseline,
        "candidate": candidate,
        "delta": delta,
        "decision": "benchmark-improved-hold-for-product" if improved else "hold",
        "promotion_boundary": (
            "Diagnostic evidence only; product ranking must remain unchanged "
            "until a separate runtime contract and regression gate are approved."
        ),
    }


def _metric_subset(metrics: dict) -> dict:
    return {
        "evaluated_queries": metrics.get("evaluated_queries", 0),
        "top1_accuracy": metrics.get("top1_accuracy"),
        "recall_at_5": metrics.get("recall_at_5"),
        "mrr_at_10": metrics.get("mrr_at_10"),
    }


def _metric_delta(before: dict, after: dict) -> dict:
    return {
        key: round(float(after.get(key) or 0.0) - float(before.get(key) or 0.0), 6)
        for key in ("top1_accuracy", "recall_at_5", "mrr_at_10")
    }


def _rank_caption_units(
    caption_units: list[IndexedUnit],
    query: str,
    *,
    top_k: int,
    scorer: str = "overlap",
) -> list[SearchResult]:
    query_terms = _terms(query)
    if not query_terms:
        return []
    term_weights = _term_weights(caption_units) if scorer == "idf" else {}
    scored = []
    for unit in caption_units:
        score = (
            _weighted_lexical_score(query_terms, unit.text, term_weights)
            if scorer == "idf"
            else _lexical_score(query_terms, unit.text)
        )
        if score <= 0:
            continue
        scored.append((score, unit))
    scored.sort(key=lambda item: (-item[0], item[1].relative_path, item[1].image_no or 0))
    return [
        SearchResult(
            score=score,
            modality="text",
            relative_path=unit.relative_path,
            page_no=unit.page_no,
            snippet=unit.text_preview,
            unit_type=unit.unit_type,
            payload={
                "unit_id": unit.unit_id,
                "image_no": unit.image_no,
                "table_no": unit.table_no,
            },
        )
        for score, unit in scored[:top_k]
    ]


def _lexical_score(query_terms: set[str], text: str) -> float:
    text_terms = _terms(text)
    if not text_terms:
        return 0.0
    overlap = query_terms & text_terms
    if not overlap:
        return 0.0
    return len(overlap) / len(query_terms)


def _weighted_lexical_score(
    query_terms: set[str],
    text: str,
    term_weights: dict[str, float],
) -> float:
    text_terms = _terms(text)
    if not text_terms:
        return 0.0
    denominator = sum(term_weights.get(term, 1.0) for term in query_terms)
    if denominator <= 0:
        return 0.0
    overlap = query_terms & text_terms
    if not overlap:
        return 0.0
    return sum(term_weights.get(term, 1.0) for term in overlap) / denominator


def _term_weights(caption_units: list[IndexedUnit]) -> dict[str, float]:
    document_count = max(len(caption_units), 1)
    frequencies: dict[str, int] = {}
    for unit in caption_units:
        for term in _terms(unit.text):
            frequencies[term] = frequencies.get(term, 0) + 1
    return {
        term: math.log((1 + document_count) / (1 + frequency)) + 1.0
        for term, frequency in frequencies.items()
    }


def _terms(text: str) -> set[str]:
    return {
        term.lower()
        for term in re.findall(r"[0-9A-Za-z가-힣]+", text)
        if len(term) >= 2
    }


def _quality_passed(quality: dict) -> bool:
    return (
        quality.get("status") == "evaluated"
        and (quality.get("recall_at_5") or 0.0) >= 0.95
        and (quality.get("mrr_at_10") or 0.0) >= 0.85
    )


def _comparison_decision(quality: dict, baselines: list[dict]) -> dict:
    baseline_summaries = []
    for baseline in baselines:
        local = baseline.get("local", {})
        if not local:
            continue
        baseline_summaries.append(
            {
                "path": baseline.get("path"),
                "fixture": baseline.get("fixture"),
                "evaluated_queries": local.get("evaluated_queries"),
                "recall_at_5": local.get("recall_at_5"),
                "mrr_at_10": local.get("mrr_at_10"),
            }
        )
    if quality.get("status") != "evaluated":
        decision = "hold-not-evaluated"
    elif not _quality_passed(quality):
        decision = "hold-below-caption-threshold"
    else:
        decision = "candidate-ready-for-baseline-review"
    return {
        "decision": decision,
        "same_fixture_baselines": baseline_summaries,
        "note": "Baseline rows are contextual comparators; they do not promote VLM captioning without caption-specific golden quality.",
    }


def _baseline_summary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": _path_label(path),
        "benchmark_mode": data.get("benchmark_mode"),
        "fixture": data.get("fixture"),
        "golden": data.get("golden"),
        "local": _metric_summary(data.get("local", data)),
        "server": _metric_summary(data.get("server", {})),
    }


def _metric_summary(report: dict) -> dict:
    if not report:
        return {}
    quality = report.get("cold_pass", {}).get("quality", {})
    latency = report.get("warm_aggregate", {}).get("search_latency_ms", {})
    return {
        "files": report.get("files"),
        "units": report.get("units"),
        "evaluated_queries": report.get("evaluated_queries"),
        "recall_at_5": quality.get("recall_at_5"),
        "mrr_at_10": quality.get("mrr_at_10"),
        "warm_p50_ms": latency.get("p50", {}).get("p50"),
        "warm_p95_ms": latency.get("p95", {}).get("p50"),
        "warm_p99_ms": latency.get("p99", {}).get("p50"),
    }


def _path_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


if __name__ == "__main__":
    raise SystemExit(main())
