from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from locallens.benchmarks.runner import run_benchmark
from locallens.core.config import Settings
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vision-model-compare")
    parser.add_argument("--corpus", default="benchmarks/fixtures/image_corpus")
    parser.add_argument("--golden", default="benchmarks/fixtures/golden_quality_queries.json")
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)

    report = compare_vision_models(
        corpus=Path(args.corpus),
        golden=Path(args.golden),
        model_names=args.model,
        settings=Settings.from_env(),
    )
    content = json.dumps(report, indent=2)
    findings = scan_text_artifact(
        content,
        args.out or "vision-model-compare",
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
    has_failures = any(row.get("status") != "ok" for row in report["models"])
    if has_failures and not args.allow_failures:
        print(content)
        return 1
    if args.out:
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    print(content)
    return 0


def compare_vision_models(
    corpus: Path,
    golden: Path,
    model_names: list[str],
    settings: Settings | None = None,
) -> dict:
    rows = []
    base_settings = settings or Settings.from_env()
    query_metadata = _load_query_metadata(golden)
    for model_name in model_names:
        with tempfile.TemporaryDirectory(prefix="locallens-vision-model-") as temp_dir:
            run_settings = replace(
                base_settings,
                data_dir=Path(temp_dir) / "data",
                text_embedding_backend="hash",
                vision_embedding_backend="transformers",
                vision_model_name=model_name,
            )
            try:
                report = run_benchmark(corpus, [], run_settings, golden_path=golden)
            except Exception as exc:
                rows.append(_failed_model_row(model_name, exc))
                continue
            rows.append(_model_row(model_name, report, query_metadata))
    return {
        "corpus": _path_label(corpus),
        "golden": _path_label(golden),
        "models": rows,
        "scope": "small curated whole-image text-to-image retrieval smoke",
        "corpus_style": _corpus_style(query_metadata),
        "attribute_source": _attribute_source(query_metadata),
    }


def _model_row(model_name: str, report, query_metadata: dict[str, dict]) -> dict:
    query_results = [
        _attach_query_metadata(row, query_metadata)
        for row in report.query_results
    ]
    hard_negative = report.quality_slices.get("tag:hard-negative", {})
    synthetic = report.quality_slices.get("tag:synthetic", {})
    hard_negative_slices = _hard_negative_slices(query_results)
    return {
        "status": "ok",
        "model": model_name,
        "selection_criteria": {
            "primary_metric": "hard-negative recall@5 and top1 accuracy",
            "secondary_metric": "p50/p95 query latency",
            "offline_reproducibility": "cache-only transformer loading required for release evidence",
        },
        "vision_embedding_profile": report.vision_embedding_profile,
        "vision_dimension": report.vision_dimension,
        "files": report.files,
        "units": report.units,
        "evaluated_queries": report.evaluated_queries,
        "skipped_queries": report.skipped_queries,
        "top1_accuracy": report.top1_accuracy,
        "recall_at_5": report.recall_at_5,
        "mrr_at_10": report.mrr_at_10,
        "search_latency_ms": report.search_latency_ms,
        "indexing_seconds": report.indexing_seconds,
        "hard_negative": {
            "evaluated_queries": hard_negative.get("evaluated_queries"),
            "top1_accuracy": hard_negative.get("top1_accuracy"),
            "recall_at_5": hard_negative.get("recall_at_5"),
            "mrr_at_10": hard_negative.get("mrr_at_10"),
        },
        "hard_negative_slices": hard_negative_slices,
        "hard_negative_repair_targets": _repair_targets(hard_negative_slices),
        "hard_negative_oracle_repair_experiment": _oracle_repair_experiment(
            query_results,
            hard_negative_slices,
        ),
        "filename_independence": _filename_independence_summary(query_results),
        "synthetic": {
            "evaluated_queries": synthetic.get("evaluated_queries"),
            "top1_accuracy": synthetic.get("top1_accuracy"),
            "recall_at_5": synthetic.get("recall_at_5"),
            "mrr_at_10": synthetic.get("mrr_at_10"),
        },
    }


def _hard_negative_slices(query_results: list[dict]) -> dict[str, dict]:
    grouped = _group_hard_negative_rows(query_results)
    return {
        name: _hard_negative_summary(rows)
        for name, rows in sorted(grouped.items())
        if rows
    }


def _group_hard_negative_rows(query_results: list[dict]) -> dict[str, list[dict]]:
    hard_rows = [
        row for row in query_results if "hard-negative" in set(row.get("tags", []))
    ]
    grouped: dict[str, list[dict]] = {"all": hard_rows}
    for row in hard_rows:
        image_key = _image_key(row)
        for prefix, value in image_key.items():
            if value:
                grouped.setdefault(f"{prefix}:{value}", []).append(row)
    return grouped


def _hard_negative_summary(rows: list[dict]) -> dict:
    failure_modes = _failure_modes(rows)
    top1_failure_count = sum(1 for row in rows if row.get("first_hit_rank") != 1)
    slice_overlap_count = sum(
        1 for row in rows if {"hard-negative", "synthetic"}.issubset(set(row.get("tags", [])))
    )
    failures = [
        {
            "query_id": row.get("id", ""),
            "expected_path": _first_expected_path(row),
            "expected_key": _image_key(row),
            "first_hit_rank": row.get("first_hit_rank"),
            "hard_negative_type": _hard_negative_type(row),
            "contrast_pair_id": _contrast_pair_id(row),
            "confusable_attribute": _confusable_attribute(row),
            "top_results": [
                {
                    "rank": item.get("rank"),
                    "relative_path": item.get("relative_path", ""),
                    "image_key": _path_image_key(item.get("relative_path", "")),
                }
                for item in row.get("top_results", [])[:3]
            ],
        }
        for row in rows
        if row.get("first_hit_rank") != 1
    ][:5]
    return {
        "evaluated_queries": len(rows),
        "slice_dimensions": ["object", "color", "context"],
        "slice_definition": _slice_definition(rows),
        "metadata_key_count": sum(
            1 for row in rows if row.get("_image_key_source") == "golden:image_key"
        ),
        "tag_overlap_policy": "hard-negative may overlap synthetic; overlap count is reported",
        "slice_overlap_count": slice_overlap_count,
        "overlap_with_synthetic": slice_overlap_count,
        "top1_failure_count": top1_failure_count,
        "null_first_hit_count": sum(1 for row in rows if row.get("first_hit_rank") is None),
        "top1_accuracy": _mean(1.0 if row.get("first_hit_rank") == 1 else 0.0 for row in rows),
        "recall_at_5": _mean(float(row.get("recall_at_5") or 0.0) for row in rows),
        "mrr_at_10": _mean(float(row.get("mrr_at_10") or 0.0) for row in rows),
        "failure_modes": failure_modes,
        "top1_failure_examples": failures,
    }


def _failure_modes(rows: list[dict]) -> dict[str, int]:
    modes: dict[str, int] = {}
    for row in rows:
        if row.get("first_hit_rank") == 1:
            continue
        mode = _hard_negative_type(row)
        modes[mode] = modes.get(mode, 0) + 1
    return dict(sorted(modes.items()))


def _repair_targets(slices: dict[str, dict]) -> list[dict]:
    targets = []
    for name, summary in slices.items():
        if name == "all":
            continue
        evaluated = int(summary.get("evaluated_queries") or 0)
        if evaluated < 1:
            continue
        top1 = float(summary.get("top1_accuracy") or 0.0)
        recall_at_5 = float(summary.get("recall_at_5") or 0.0)
        if top1 < 0.90 or recall_at_5 < 0.95:
            targets.append(
                {
                    "slice": name,
                    "evaluated_queries": evaluated,
                    "top1_accuracy": top1,
                    "recall_at_5": recall_at_5,
                    "failure_modes": summary.get("failure_modes", {}),
                    "suggested_action": "add sanitized contrast pairs or rewrite ambiguous queries for this slice",
                }
            )
    return sorted(
        targets,
        key=lambda item: (item["top1_accuracy"], item["recall_at_5"], item["slice"]),
    )[:10]


def _oracle_repair_experiment(
    query_results: list[dict],
    slices: dict[str, dict],
) -> dict:
    grouped = _group_hard_negative_rows(query_results)
    all_rows = grouped.get("all", [])
    return {
        "scope": "diagnostic upper bound from existing top-k results",
        "product_ranking_change": False,
        "non_regression_gate": {
            "top1_min": 0.90,
            "recall_at_5_min": 0.95,
            "mrr_at_10_min": 0.90,
            "passed": _summary_passes_selected_gate(slices.get("all", {})),
        },
        "all": _oracle_summary(all_rows),
        "weak_slices": [
            {
                "slice": name,
                **_oracle_summary(grouped[name]),
            }
            for name in _weak_slice_names(slices)
            if name in grouped
        ],
    }


def _summary_passes_selected_gate(summary: dict) -> bool:
    return (
        float(summary.get("top1_accuracy") or 0.0) >= 0.90
        and float(summary.get("recall_at_5") or 0.0) >= 0.95
        and float(summary.get("mrr_at_10") or 0.0) >= 0.90
    )


def _weak_slice_names(slices: dict[str, dict]) -> list[str]:
    names = []
    for name, summary in slices.items():
        if name == "all":
            continue
        if float(summary.get("top1_accuracy") or 0.0) < 0.90:
            names.append(name)
    return sorted(
        names,
        key=lambda item: (
            float(slices[item].get("top1_accuracy") or 0.0),
            float(slices[item].get("recall_at_5") or 0.0),
            item,
        ),
    )[:10]


def _oracle_summary(rows: list[dict]) -> dict:
    if not rows:
        return {
            "evaluated_queries": 0,
            "baseline_top1_accuracy": 0.0,
            "oracle_top1_accuracy": 0.0,
            "top1_repairable_count": 0,
            "missing_from_top5_count": 0,
            "status": "empty",
        }
    baseline_top1 = sum(1 for row in rows if row.get("first_hit_rank") == 1)
    repairable = [
        row
        for row in rows
        if row.get("first_hit_rank") != 1 and _expected_rank(row, limit=5) is not None
    ]
    missing = [
        row
        for row in rows
        if row.get("first_hit_rank") != 1 and _expected_rank(row, limit=5) is None
    ]
    oracle_top1 = baseline_top1 + len(repairable)
    return {
        "evaluated_queries": len(rows),
        "baseline_top1_accuracy": baseline_top1 / len(rows),
        "oracle_top1_accuracy": oracle_top1 / len(rows),
        "top1_repairable_count": len(repairable),
        "missing_from_top5_count": len(missing),
        "status": "improved" if repairable else "no-change",
    }


def _expected_rank(row: dict, *, limit: int) -> int | None:
    expected = _first_expected_path(row)
    for item in row.get("top_results", [])[:limit]:
        if item.get("relative_path") == expected:
            return int(item.get("rank") or 0)
    return None


def _image_key(row: dict) -> dict[str, str]:
    key = row.get("_image_key")
    if isinstance(key, dict):
        return {
            "object": str(key.get("object", "")),
            "color": str(key.get("color", "")),
            "context": str(key.get("context", "")),
        }
    return _path_image_key(_first_expected_path(row))


def _path_image_key(path: str) -> dict[str, str]:
    parts = Path(path).stem.split("_")
    return {
        "object": parts[0] if len(parts) >= 1 else "",
        "color": parts[1] if len(parts) >= 2 else "",
        "context": "_".join(parts[2:]) if len(parts) >= 3 else "",
    }


def _load_query_metadata(path: Path) -> dict[str, dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    queries = raw.get("queries", raw) if isinstance(raw, dict) else raw
    metadata = {}
    for item in queries:
        item_id = str(item.get("id", item.get("query", "")))
        metadata[item_id] = {
            "image_key": _normalize_image_key(item.get("image_key")),
            "tags": list(item.get("tags", [])),
        }
    return metadata


def _attach_query_metadata(row: dict, metadata: dict[str, dict]) -> dict:
    item = metadata.get(str(row.get("id", "")), {})
    image_key = item.get("image_key")
    if not image_key:
        return row
    return {
        **row,
        "_image_key": image_key,
        "_image_key_source": "golden:image_key",
    }


def _normalize_image_key(value) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {
        "object": str(value.get("object", "")),
        "color": str(value.get("color", "")),
        "context": str(value.get("context", "")),
    }


def _slice_definition(rows: list[dict]) -> str:
    if rows and all(row.get("_image_key_source") == "golden:image_key" for row in rows):
        return "golden image_key metadata; filename does not encode object_color_context"
    return "filename stem parsed as object_color_context"


def _filename_independence_summary(rows: list[dict]) -> dict:
    non_filename_rows = [
        row for row in rows if "non-filename" in set(row.get("tags", []))
    ]
    if not non_filename_rows:
        return {
            "evaluated_queries": 0,
            "metadata_key_count": 0,
            "semantic_filename_count": 0,
            "passed": False,
        }
    metadata_count = sum(
        1 for row in non_filename_rows if row.get("_image_key_source") == "golden:image_key"
    )
    semantic_filename_count = sum(
        1 for row in non_filename_rows if _semantic_filename_match(row)
    )
    return {
        "evaluated_queries": len(non_filename_rows),
        "metadata_key_count": metadata_count,
        "semantic_filename_count": semantic_filename_count,
        "attribute_source": "golden:image_key",
        "passed": metadata_count == len(non_filename_rows)
        and semantic_filename_count == 0,
    }


def _semantic_filename_match(row: dict) -> bool:
    key = _image_key(row)
    path_parts = set(Path(_first_expected_path(row)).stem.lower().split("_"))
    return any(value and value.lower() in path_parts for value in key.values())


def _corpus_style(metadata: dict[str, dict]) -> str:
    return "metadata-keyed" if _metadata_key_count(metadata) else "filename-keyed"


def _attribute_source(metadata: dict[str, dict]) -> str:
    return "golden:image_key" if _metadata_key_count(metadata) else "filename_stem"


def _metadata_key_count(metadata: dict[str, dict]) -> int:
    return sum(1 for item in metadata.values() if item.get("image_key"))


def _first_expected_path(row: dict) -> str:
    expected = row.get("expected_paths") or []
    return str(expected[0]) if expected else ""


def _hard_negative_type(row: dict) -> str:
    top = (row.get("top_results") or [{}])[0]
    expected = _image_key(row)
    observed = _path_image_key(str(top.get("relative_path", "")))
    changed = [
        key for key in ("object", "color", "context") if expected.get(key) != observed.get(key)
    ]
    return "+".join(changed) if changed else "top1-hit"


def _contrast_pair_id(row: dict) -> str:
    key = _image_key(row)
    return ":".join(
        part for part in [key.get("object", ""), key.get("context", "")] if part
    )


def _confusable_attribute(row: dict) -> str:
    changed = _hard_negative_type(row)
    return "none" if changed == "top1-hit" else changed


def _mean(values) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _failed_model_row(model_name: str, exc: Exception) -> dict:
    return {
        "status": "failed",
        "model": model_name,
        "error_type": exc.__class__.__name__,
        "error": str(exc).splitlines()[0],
    }


def _path_label(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return f"<external>/{path.name}"


if __name__ == "__main__":
    raise SystemExit(main())
