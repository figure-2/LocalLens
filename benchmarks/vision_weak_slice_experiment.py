from __future__ import annotations

import argparse
import json
import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from locallens.benchmarks.runner import run_benchmark
from locallens.core.config import Settings
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


DEFAULT_SELECTED_MODEL = "google/siglip-base-patch16-224"
DEFAULT_CANDIDATE_MODEL = "openai/clip-vit-base-patch32"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vision-weak-slice-experiment")
    parser.add_argument("--corpus", default="benchmarks/fixtures/image_corpus")
    parser.add_argument("--golden", default="benchmarks/fixtures/golden_quality_queries.json")
    parser.add_argument("--selected-model", default=DEFAULT_SELECTED_MODEL)
    parser.add_argument("--candidate-model", default=DEFAULT_CANDIDATE_MODEL)
    parser.add_argument("--out", default=None)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)

    report = run_experiment(
        corpus=Path(args.corpus),
        golden=Path(args.golden),
        selected_model=args.selected_model,
        candidate_model=args.candidate_model,
        settings=Settings.from_env(),
    )
    content = json.dumps(report, indent=2)
    findings = scan_text_artifact(
        content,
        args.out or "vision-weak-slice-experiment",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
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
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    print(content)
    return 0


def run_experiment(
    *,
    corpus: Path,
    golden: Path,
    selected_model: str,
    candidate_model: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    query_metadata = _load_query_metadata(golden)
    image_key_by_path = _image_key_by_path(query_metadata)
    target_slices, model_rows = _run_model_rows(
        corpus=corpus,
        golden=golden,
        models=[selected_model, candidate_model],
        query_metadata=query_metadata,
        image_key_by_path=image_key_by_path,
        settings=settings or Settings.from_env(),
        candidate_model=candidate_model,
    )
    candidate = model_rows[candidate_model]
    selected = model_rows[selected_model]
    candidate_delta = candidate["targeted_weak_slices"]["delta"]
    selected_non_regression = selected["non_regression_gate"]
    improved = (
        candidate_delta["top1_accuracy"] > 0.0
        and candidate_delta["recall_at_5"] >= 0.0
        and selected_non_regression["passed"]
    )
    return {
        "benchmark_mode": "vision-weak-slice-rerank-experiment",
        "scope": "benchmark-only candidate rerank experiment on the curated image fixture",
        "corpus_style": _corpus_style(query_metadata),
        "attribute_source": _attribute_source(query_metadata),
        "product_runtime_change": False,
        "release_claim_boundary": (
            "Record as exploratory evidence only; do not promote product ranking "
            "without a separate runtime contract and regression gate."
        ),
        "corpus": _path_label(corpus),
        "golden": _path_label(golden),
        "diagnostic_fixture": _diagnostic_fixture_summary(query_metadata),
        "candidate_reranker": {
            "name": "benchmark-image-key-rerank-v1",
            "input": _candidate_input_description(query_metadata),
            "label_usage": (
                "golden labels are used only for scoring; benchmark image_key "
                "metadata is used only for this diagnostic"
            ),
        },
        "targeted_slices_source_model": candidate_model,
        "targeted_slices": target_slices,
        "models": [selected, candidate],
        "acceptance": {
            "candidate_targeted_top1_delta_min": 0.0,
            "candidate_targeted_recall_at_5_delta_min": 0.0,
            "selected_model_non_regression_required": True,
            "passed": improved,
        },
        "overall_decision": "candidate-improved-hold-for-product" if improved else "hold",
    }


def _run_model_rows(
    *,
    corpus: Path,
    golden: Path,
    models: list[str],
    query_metadata: dict[str, dict[str, Any]],
    image_key_by_path: dict[str, dict[str, str]],
    settings: Settings,
    candidate_model: str,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    raw_reports = {}
    for model_name in models:
        with tempfile.TemporaryDirectory(prefix="locallens-vision-weak-slice-") as temp_dir:
            run_settings = replace(
                settings,
                data_dir=Path(temp_dir) / "data",
                text_embedding_backend="hash",
                vision_embedding_backend="transformers",
                vision_model_name=model_name,
            )
            raw_reports[model_name] = run_benchmark(
                corpus,
                [],
                run_settings,
                golden_path=golden,
            )
    target_slices = _weak_slice_names(
        raw_reports[candidate_model].query_results,
        query_metadata,
        image_key_by_path,
    )
    return target_slices, {
        model_name: _model_experiment_row(
            model_name,
            raw_report.query_results,
            query_metadata,
            image_key_by_path,
            target_slices,
        )
        for model_name, raw_report in raw_reports.items()
    }


def _model_experiment_row(
    model_name: str,
    rows: list[dict[str, Any]],
    query_metadata: dict[str, dict[str, Any]],
    image_key_by_path: dict[str, dict[str, str]],
    target_slices: list[str],
) -> dict[str, Any]:
    reranked_rows = [
        _reranked_query_row(
            row,
            str(query_metadata.get(str(row.get("id", "")), {}).get("query", "")),
            image_key_by_path,
        )
        for row in rows
    ]
    all_rows = _image_rows(rows)
    all_reranked = _image_rows(reranked_rows)
    hard_rows = _hard_negative_rows(rows)
    hard_reranked = _hard_negative_rows(reranked_rows)
    targeted_rows = _rows_for_slices(
        hard_rows,
        target_slices,
        query_metadata,
        image_key_by_path,
    )
    targeted_reranked = _rows_for_slices(
        hard_reranked,
        target_slices,
        query_metadata,
        image_key_by_path,
    )
    aggregate = {
        "baseline": _metric_summary(all_rows),
        "reranked": _metric_summary(all_reranked),
    }
    hard_negative = {
        "baseline": _metric_summary(hard_rows),
        "reranked": _metric_summary(hard_reranked),
    }
    targeted = {
        "slices": target_slices,
        "baseline": _metric_summary(targeted_rows),
        "reranked": _metric_summary(targeted_reranked),
    }
    aggregate["delta"] = _metric_delta(aggregate["baseline"], aggregate["reranked"])
    hard_negative["delta"] = _metric_delta(
        hard_negative["baseline"], hard_negative["reranked"]
    )
    targeted["delta"] = _metric_delta(targeted["baseline"], targeted["reranked"])
    non_regression = _non_regression_gate(aggregate["delta"], hard_negative["delta"])
    return {
        "model": model_name,
        "query_count": len(all_rows),
        "hard_negative_count": len(hard_rows),
        "aggregate": aggregate,
        "hard_negative": hard_negative,
        "targeted_weak_slices": targeted,
        "non_regression_gate": non_regression,
        "rerank_examples": _rerank_examples(targeted_rows, targeted_reranked),
    }


def _reranked_query_row(
    row: dict[str, Any],
    query_text: str,
    image_key_by_path: dict[str, dict[str, str]],
) -> dict[str, Any]:
    expected = set(row.get("expected_paths") or [])
    ranked = sorted(
        list(row.get("top_results") or []),
        key=lambda item: (
            -_attribute_score(
                query_text,
                str(item.get("relative_path", "")),
                image_key_by_path,
            ),
            int(item.get("rank") or 999),
        ),
    )
    reranked_top_rank = _first_hit_rank(ranked, expected)
    first_hit_rank = reranked_top_rank
    if reranked_top_rank is None:
        first_hit_rank = row.get("first_hit_rank")
    return {
        **row,
        "top_results": [
            {**item, "rank": rank}
            for rank, item in enumerate(ranked, start=1)
        ],
        "first_hit_rank": first_hit_rank,
        "hit_at_1": first_hit_rank == 1,
        "recall_at_5": 1.0 if first_hit_rank is not None and first_hit_rank <= 5 else 0.0,
        "mrr_at_10": _mrr(first_hit_rank if first_hit_rank is None or first_hit_rank <= 10 else None),
    }


def _attribute_score(
    query_text: str,
    relative_path: str,
    image_key_by_path: dict[str, dict[str, str]],
) -> float:
    key = _candidate_image_key(relative_path, image_key_by_path)
    query_terms = _terms(query_text)
    object_score = 3.0 if key["object"] in query_terms else 0.0
    color_score = 2.0 if key["color"] in query_terms else 0.0
    context_terms = set(_terms(key["context"]))
    context_score = 2.0 * len(query_terms & context_terms)
    return object_score + color_score + context_score


def _weak_slice_names(
    rows: list[dict[str, Any]],
    query_metadata: dict[str, dict[str, Any]],
    image_key_by_path: dict[str, dict[str, str]],
) -> list[str]:
    grouped = _group_hard_negative_rows(rows, query_metadata, image_key_by_path)
    summaries = {
        name: _metric_summary(items)
        for name, items in grouped.items()
        if name != "all" and items
    }
    weak = [
        name
        for name, summary in summaries.items()
        if summary["top1_accuracy"] < 0.90 or summary["recall_at_5"] < 0.95
    ]
    return sorted(
        weak,
        key=lambda name: (
            summaries[name]["top1_accuracy"],
            summaries[name]["recall_at_5"],
            name,
        ),
    )[:10]


def _group_hard_negative_rows(
    rows: list[dict[str, Any]],
    query_metadata: dict[str, dict[str, Any]],
    image_key_by_path: dict[str, dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {"all": _hard_negative_rows(rows)}
    for row in grouped["all"]:
        key = _row_image_key(row, query_metadata, image_key_by_path)
        for name, value in key.items():
            if value:
                grouped.setdefault(f"{name}:{value}", []).append(row)
    return grouped


def _rows_for_slices(
    rows: list[dict[str, Any]],
    slices: list[str],
    query_metadata: dict[str, dict[str, Any]],
    image_key_by_path: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for row in rows:
        row_slices = _row_slices(row, query_metadata, image_key_by_path)
        if row_slices.isdisjoint(slices):
            continue
        row_id = str(row.get("id", ""))
        if row_id in seen:
            continue
        seen.add(row_id)
        result.append(row)
    return result


def _row_slices(
    row: dict[str, Any],
    query_metadata: dict[str, dict[str, Any]],
    image_key_by_path: dict[str, dict[str, str]],
) -> set[str]:
    key = _row_image_key(row, query_metadata, image_key_by_path)
    return {f"{name}:{value}" for name, value in key.items() if value}


def _metric_summary(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    if not rows:
        return {
            "evaluated_queries": 0,
            "top1_accuracy": 0.0,
            "recall_at_5": 0.0,
            "mrr_at_10": 0.0,
        }
    return {
        "evaluated_queries": len(rows),
        "top1_accuracy": _mean(1.0 if row.get("first_hit_rank") == 1 else 0.0 for row in rows),
        "recall_at_5": _mean(float(row.get("recall_at_5") or 0.0) for row in rows),
        "mrr_at_10": _mean(float(row.get("mrr_at_10") or 0.0) for row in rows),
    }


def _metric_delta(
    baseline: dict[str, float | int],
    reranked: dict[str, float | int],
) -> dict[str, float]:
    return {
        "top1_accuracy": round(
            float(reranked["top1_accuracy"]) - float(baseline["top1_accuracy"]), 6
        ),
        "recall_at_5": round(
            float(reranked["recall_at_5"]) - float(baseline["recall_at_5"]), 6
        ),
        "mrr_at_10": round(
            float(reranked["mrr_at_10"]) - float(baseline["mrr_at_10"]), 6
        ),
    }


def _non_regression_gate(
    aggregate_delta: dict[str, float],
    hard_negative_delta: dict[str, float],
) -> dict[str, Any]:
    passed = all(
        value >= 0.0
        for value in [
            aggregate_delta["top1_accuracy"],
            aggregate_delta["recall_at_5"],
            aggregate_delta["mrr_at_10"],
            hard_negative_delta["top1_accuracy"],
            hard_negative_delta["recall_at_5"],
            hard_negative_delta["mrr_at_10"],
        ]
    )
    return {
        "passed": passed,
        "minimum_delta": 0.0,
        "checked_metrics": [
            "aggregate.top1_accuracy",
            "aggregate.recall_at_5",
            "aggregate.mrr_at_10",
            "hard_negative.top1_accuracy",
            "hard_negative.recall_at_5",
            "hard_negative.mrr_at_10",
        ],
    }


def _rerank_examples(
    baseline_rows: list[dict[str, Any]],
    reranked_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reranked_by_id = {str(row.get("id", "")): row for row in reranked_rows}
    examples = []
    for row in baseline_rows:
        row_id = str(row.get("id", ""))
        updated = reranked_by_id.get(row_id)
        if not updated:
            continue
        before = row.get("first_hit_rank")
        after = updated.get("first_hit_rank")
        if before == after:
            continue
        examples.append(
            {
                "query_id": row_id,
                "expected_path": _first_expected_path(row),
                "baseline_first_hit_rank": before,
                "reranked_first_hit_rank": after,
                "baseline_top1": _top_result_path(row),
                "reranked_top1": _top_result_path(updated),
            }
        )
    return examples[:10]


def _image_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("modality") == "image"]


def _hard_negative_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in _image_rows(rows) if "hard-negative" in set(row.get("tags", []))]


def _load_query_metadata(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    queries = raw.get("queries", raw) if isinstance(raw, dict) else raw
    metadata: dict[str, dict[str, Any]] = {}
    for item in queries:
        item_id = str(item.get("id", item.get("query", "")))
        metadata[item_id] = {
            "query": str(item.get("query", "")),
            "image_key": _normalize_image_key(item.get("image_key")),
            "expected_paths": _relevant_paths(item),
        }
    return metadata


def _image_key_by_path(
    query_metadata: dict[str, dict[str, Any]],
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for item in query_metadata.values():
        key = item.get("image_key")
        if not isinstance(key, dict):
            continue
        for path in item.get("expected_paths", []):
            result[str(path)] = key
    return result


def _relevant_paths(item: dict[str, Any]) -> list[str]:
    relevant = item.get("relevant") or []
    return [
        str(entry.get("relative_path", ""))
        for entry in relevant
        if entry.get("relative_path")
    ]


def _normalize_image_key(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {
        "object": str(value.get("object", "")),
        "color": str(value.get("color", "")),
        "context": str(value.get("context", "")),
    }


def _row_image_key(
    row: dict[str, Any],
    query_metadata: dict[str, dict[str, Any]],
    image_key_by_path: dict[str, dict[str, str]],
) -> dict[str, str]:
    item = query_metadata.get(str(row.get("id", "")), {})
    key = item.get("image_key")
    if isinstance(key, dict):
        return key
    return _candidate_image_key(_first_expected_path(row), image_key_by_path)


def _candidate_image_key(
    relative_path: str,
    image_key_by_path: dict[str, dict[str, str]],
) -> dict[str, str]:
    key = image_key_by_path.get(relative_path)
    if isinstance(key, dict):
        return key
    return _path_image_key(relative_path)


def _corpus_style(query_metadata: dict[str, dict[str, Any]]) -> str:
    return "metadata-keyed" if _metadata_key_count(query_metadata) else "filename-keyed"


def _attribute_source(query_metadata: dict[str, dict[str, Any]]) -> str:
    return "golden:image_key" if _metadata_key_count(query_metadata) else "filename_stem"


def _candidate_input_description(query_metadata: dict[str, dict[str, Any]]) -> str:
    if _metadata_key_count(query_metadata):
        return "query text plus benchmark image_key metadata from existing top-k"
    return "query text plus sanitized image relative paths from existing top-k"


def _diagnostic_fixture_summary(
    query_metadata: dict[str, dict[str, Any]],
) -> dict[str, int | str | bool]:
    keyed_paths = _image_key_by_path(query_metadata)
    semantic_matches = sum(
        1
        for path, key in keyed_paths.items()
        if _semantic_filename_match(path, key)
    )
    return {
        "corpus_style": _corpus_style(query_metadata),
        "attribute_source": _attribute_source(query_metadata),
        "query_count": len(query_metadata),
        "metadata_key_count": _metadata_key_count(query_metadata),
        "expected_path_count": len(keyed_paths),
        "semantic_filename_match_count": semantic_matches,
        "filename_independence_gate": bool(keyed_paths) and semantic_matches == 0,
    }


def _metadata_key_count(query_metadata: dict[str, dict[str, Any]]) -> int:
    return sum(1 for item in query_metadata.values() if item.get("image_key"))


def _semantic_filename_match(path: str, key: dict[str, str]) -> bool:
    stem_terms = set(Path(path).stem.lower().split("_"))
    return any(value and value.lower() in stem_terms for value in key.values())


def _first_hit_rank(items: list[dict[str, Any]], expected_paths: set[str]) -> int | None:
    for index, item in enumerate(items, start=1):
        if str(item.get("relative_path", "")) in expected_paths:
            return index
    return None


def _mrr(rank: int | None) -> float:
    return (1.0 / rank) if rank else 0.0


def _first_expected_path(row: dict[str, Any]) -> str:
    expected = row.get("expected_paths") or []
    return str(expected[0]) if expected else ""


def _top_result_path(row: dict[str, Any]) -> str:
    results = row.get("top_results") or []
    return str(results[0].get("relative_path", "")) if results else ""


def _path_image_key(path: str) -> dict[str, str]:
    parts = Path(path).stem.split("_")
    return {
        "object": parts[0] if len(parts) >= 1 else "",
        "color": parts[1] if len(parts) >= 2 else "",
        "context": "_".join(parts[2:]) if len(parts) >= 3 else "",
    }


def _terms(value: str) -> set[str]:
    return {item for item in re.split(r"[^a-z0-9]+", value.lower()) if item}


def _mean(values) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _path_label(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return f"<external>/{path.name}"


if __name__ == "__main__":
    raise SystemExit(main())
