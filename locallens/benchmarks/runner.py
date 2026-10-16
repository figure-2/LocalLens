from __future__ import annotations

import json
import math
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from locallens.core.config import Settings
from locallens.core.types import BenchmarkReport
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.search_service import SearchService
from locallens.security.artifact_scan import scan_text_artifact


def run_benchmark(
    folder: str | Path,
    queries: list[str],
    settings: Settings,
    golden_path: str | Path | None = None,
    drop_collection: bool = False,
) -> BenchmarkReport:
    with tempfile.TemporaryDirectory(prefix="locallens-benchmark-") as temp_dir:
        isolated_settings = replace(settings, data_dir=Path(temp_dir) / "data")
        return _run_benchmark_isolated(
            folder,
            queries,
            isolated_settings,
            golden_path=golden_path,
            drop_collection=drop_collection,
        )


def _run_benchmark_isolated(
    folder: str | Path,
    queries: list[str],
    settings: Settings,
    golden_path: str | Path | None = None,
    drop_collection: bool = False,
) -> BenchmarkReport:
    golden_queries = _load_golden_queries(golden_path) if golden_path else []
    effective_queries = _effective_query_items(golden_queries, queries, settings)
    store = QdrantStore(settings)
    manifest = ManifestStore(settings.manifest_path)
    try:
        sync = SyncService(settings, store=store, manifest=manifest)
        start = time.perf_counter()
        sync_report = sync.sync_folder(folder)
        indexing_seconds = time.perf_counter() - start
        search = SearchService(settings, store=store, manifest=manifest)
        latencies = []
        result_sets = []
        for item in _query_items(effective_queries):
            query = item["query"]
            q_start = time.perf_counter()
            results = search.search(
                query,
                top_k=int(item.get("top_k", 10)),
                modality=item.get("modality"),
            )
            latencies.append((time.perf_counter() - q_start) * 1000)
            result_sets.append(results)
        units = store.count()
        manifest_units = manifest.unit_count()
        payload_records = store.payload_records()
        quality = _quality_metrics(
            effective_queries if golden_queries else [],
            result_sets,
        )
        files = sync_report.added + sync_report.updated + sync_report.skipped
        return BenchmarkReport(
            files=files,
            units=units,
            indexing_seconds=indexing_seconds,
            files_per_second=(files / indexing_seconds) if indexing_seconds else 0.0,
            units_per_second=(units / indexing_seconds) if indexing_seconds else 0.0,
            search_latency_ms=_latency_summary(latencies),
            collection_name=store.collection_name,
            text_embedding_profile=sync.settings.text_embedding_profile,
            vision_embedding_profile=sync.settings.vision_embedding_profile,
            text_dimension=sync.settings.text_dimension,
            vision_dimension=sync.settings.vision_dimension,
            evaluated_queries=len(effective_queries) if golden_queries else 0,
            recall_at_5=quality["recall_at_5"],
            recall_at_10=quality["recall_at_10"],
            mrr_at_10=quality["mrr_at_10"],
            stale_vector_count=_stale_vector_count(payload_records, manifest),
            duplicate_vector_count=_duplicate_vector_count(payload_records),
            qdrant_disk_bytes=_dir_size(settings.qdrant_path),
            sync=sync_report,
            skipped_queries=max(0, len(golden_queries) - len(effective_queries)),
            recall_at_1=quality["recall_at_1"],
            hit_at_1=quality["hit_at_1"],
            ndcg_at_10=quality["ndcg_at_10"],
            top1_accuracy=quality["top1_accuracy"],
            quality_slices=quality["quality_slices"],
            query_results=_query_result_details(
                effective_queries if golden_queries else [],
                result_sets,
            ),
        )
    finally:
        active_error = sys.exc_info()[0]
        cleanup_error = None
        if drop_collection:
            try:
                store.drop_collection()
            except Exception as exc:
                cleanup_error = exc
        try:
            store.close()
        finally:
            if cleanup_error is not None and active_error is None:
                raise cleanup_error


def write_report(
    report: BenchmarkReport,
    path: str | Path,
    banned_terms: list[str] | None = None,
) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    output_path = Path(path)
    content = json.dumps(asdict(report), indent=2)
    findings = _scan_text_artifact(content, output_path, banned_terms or [])
    if findings:
        details = ", ".join(
            f"{_artifact_label(item.path)}: {item.reason}" for item in findings
        )
        raise ValueError(f"Benchmark artifact scan failed: {details}")
    output_path.write_text(content, encoding="utf-8")


def _latency_summary(latencies: list[float]) -> dict[str, float]:
    if not latencies:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    ordered = sorted(latencies)
    return {
        "p50": statistics.median(ordered),
        "p95": _percentile(ordered, 95),
        "p99": _percentile(ordered, 99),
    }


def _percentile(values: list[float], percentile: int) -> float:
    if len(values) == 1:
        return values[0]
    index = int(round((percentile / 100) * (len(values) - 1)))
    return values[max(0, min(index, len(values) - 1))]


def _load_golden_queries(path: str | Path) -> list[dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    queries = raw.get("queries", raw) if isinstance(raw, dict) else raw
    result = []
    for item in queries:
        parsed = {
            "id": str(item.get("id", item["query"])),
            "query": str(item["query"]),
            "relevant_paths": [
                str(path)
                for path in item.get("relevant_paths", _paths_from_relevant(item))
            ],
            "modality": item.get("modality"),
            "backend_profile": item.get("backend_profile"),
            "top_k": int(item.get("top_k", 10)),
            "tags": item.get("tags", []),
        }
        if "relevant" in item:
            parsed["relevant"] = item["relevant"]
        for key in (
            "query_id",
            "query_set_id",
            "corpus_id",
            "corpus_version",
            "schema_version",
            "slice_tags",
            "claim_class",
            "scenario",
            "negative_paths",
        ):
            if key in item:
                parsed[key] = item[key]
        result.append(parsed)
    return result


def _paths_from_relevant(item: dict[str, Any]) -> list[str]:
    return [str(entry["relative_path"]) for entry in item.get("relevant", [])]


def _query_items(queries: list[str] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not queries:
        return []
    if isinstance(queries[0], dict):
        return queries
    return [{"query": str(query), "modality": None} for query in queries]


def _effective_query_items(
    golden_queries: list[dict[str, Any]],
    raw_queries: list[str],
    settings: Settings,
) -> list[dict[str, Any]]:
    if golden_queries:
        return [
            item
            for item in golden_queries
            if _matches_backend_profile(item.get("backend_profile"), item, settings)
        ]
    return _query_items(raw_queries)


def _matches_backend_profile(
    backend_profile: str | None,
    item: dict[str, Any],
    settings: Settings,
) -> bool:
    if not backend_profile or backend_profile == "any":
        return True
    if backend_profile == "hash":
        modality = item.get("modality")
        if modality == "image":
            return settings.vision_embedding_backend == "hash"
        if modality == "text":
            return settings.text_embedding_backend == "hash"
        return (
            settings.text_embedding_backend == "hash"
            and settings.vision_embedding_backend == "hash"
        )
    if backend_profile.startswith("sentence-transformers:"):
        model_name = backend_profile.split(":", 1)[1]
        return (
            settings.text_embedding_backend == "sentence-transformers"
            and settings.text_model_name == model_name
        )
    if backend_profile == "sentence-transformers":
        return settings.text_embedding_backend == "sentence-transformers"
    if backend_profile.startswith("transformers:"):
        model_name = backend_profile.split(":", 1)[1]
        return (
            settings.vision_embedding_backend == "transformers"
            and settings.vision_model_name == model_name
        )
    if backend_profile == "transformers":
        return settings.vision_embedding_backend == "transformers"
    return False


def _quality_metrics(
    golden_queries: list[dict[str, Any]], result_sets: list[list[Any]]
) -> dict:
    if not golden_queries:
        return {
            "recall_at_1": None,
            "recall_at_5": None,
            "recall_at_10": None,
            "mrr_at_10": None,
            "hit_at_1": None,
            "ndcg_at_10": None,
            "top1_accuracy": None,
            "quality_slices": {},
        }
    pairs = list(zip(golden_queries, result_sets, strict=False))
    summary = _quality_summary(pairs)
    summary["quality_slices"] = _quality_slices(pairs)
    return summary


def _quality_summary(pairs: list[tuple[dict[str, Any], list[Any]]]) -> dict:
    if not pairs:
        return {
            "recall_at_1": None,
            "recall_at_5": None,
            "recall_at_10": None,
            "mrr_at_10": None,
            "hit_at_1": None,
            "ndcg_at_10": None,
            "top1_accuracy": None,
            "evaluated_queries": 0,
        }
    recall_1 = []
    recall_5 = []
    recall_10 = []
    reciprocal_ranks = []
    hit_1 = []
    ndcg_10 = []
    for item, results in pairs:
        candidates = _unique_results(results)
        targets = _relevant_targets(item)
        recall_1.append(_recall_at(candidates[:1], targets))
        recall_5.append(_recall_at(candidates[:5], targets))
        recall_10.append(_recall_at(candidates[:10], targets))
        reciprocal_ranks.append(_reciprocal_rank(candidates[:10], targets))
        hit_1.append(1.0 if _first_hit(candidates[:1], targets) else 0.0)
        ndcg_10.append(_ndcg_at(candidates[:10], targets))
    return {
        "recall_at_1": statistics.mean(recall_1),
        "recall_at_5": statistics.mean(recall_5),
        "recall_at_10": statistics.mean(recall_10),
        "mrr_at_10": statistics.mean(reciprocal_ranks),
        "hit_at_1": statistics.mean(hit_1),
        "ndcg_at_10": statistics.mean(ndcg_10),
        "top1_accuracy": statistics.mean(hit_1),
        "evaluated_queries": len(pairs),
    }


def _quality_slices(
    pairs: list[tuple[dict[str, Any], list[Any]]]
) -> dict[str, dict[str, float | int | None]]:
    grouped: dict[str, list[tuple[dict[str, Any], list[Any]]]] = {}
    for item, results in pairs:
        modality = item.get("modality")
        if modality:
            grouped.setdefault(f"modality:{modality}", []).append((item, results))
        for tag in item.get("tags", []):
            grouped.setdefault(f"tag:{tag}", []).append((item, results))
    return {name: _quality_summary(items) for name, items in sorted(grouped.items())}


def _query_result_details(
    golden_queries: list[dict[str, Any]], result_sets: list[list[Any]]
) -> list[dict[str, Any]]:
    details = []
    for item, results in zip(golden_queries, result_sets, strict=False):
        candidates = _unique_results(results)
        targets = _relevant_targets(item)
        first_hit_rank = None
        for rank, result in enumerate(candidates[:10], start=1):
            if any(_target_matches_result(target, result, rank) for target in targets):
                first_hit_rank = rank
                break
        details.append(
            {
                "id": item.get("id", ""),
                "modality": item.get("modality"),
                "tags": list(item.get("tags", [])),
                "expected_paths": sorted(_relevant_paths(item)),
                "first_hit_rank": first_hit_rank,
                "hit_at_1": first_hit_rank == 1,
                "recall_at_5": _recall_at(candidates[:5], targets),
                "mrr_at_10": _reciprocal_rank(candidates[:10], targets),
                "top_results": [
                    {
                        "rank": rank,
                        "relative_path": getattr(result, "relative_path", ""),
                        "unit_type": getattr(result, "unit_type", ""),
                        "score": round(float(getattr(result, "score", 0.0)), 6),
                    }
                    for rank, result in enumerate(candidates[:5], start=1)
                ],
            }
        )
    return details


def _relevant_paths(item: dict[str, Any]) -> set[str]:
    if "relevant" in item:
        return {str(entry["relative_path"]) for entry in item["relevant"]}
    return set(item["relevant_paths"])


def _relevant_targets(item: dict[str, Any]) -> list[dict[str, Any]]:
    if "relevant" in item:
        return [dict(entry) for entry in item["relevant"]]
    return [{"relative_path": path, "gain": 1.0} for path in item["relevant_paths"]]


def _ndcg_at(results: list[Any], targets: list[dict[str, Any]]) -> float:
    if not targets:
        return 0.0
    used_targets: set[int] = set()
    dcg = 0.0
    for index, result in enumerate(results, start=1):
        target_index, gain = _best_gain_for_result(result, targets, index, used_targets)
        if target_index is not None:
            used_targets.add(target_index)
        dcg += gain / _discount(index)
    ideal = sorted((float(target.get("gain", 1.0)) for target in targets), reverse=True)[
        : len(results) or 10
    ]
    idcg = sum(gain / _discount(index) for index, gain in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def _best_gain_for_result(
    result: Any,
    targets: list[dict[str, Any]],
    rank: int,
    used_targets: set[int],
) -> tuple[int | None, float]:
    best_index = None
    best_gain = 0.0
    for index, target in enumerate(targets):
        if index in used_targets:
            continue
        if _target_matches_result(target, result, rank):
            gain = float(target.get("gain", 1.0))
            if gain > best_gain:
                best_index = index
                best_gain = gain
    return best_index, best_gain


def _discount(rank: int) -> float:
    return 1.0 if rank <= 1 else math.log2(rank + 1)


def _recall_at(results: list[Any], targets: list[dict[str, Any]]) -> float:
    if not targets:
        return 0.0
    hits = 0
    for target in targets:
        if any(
            _target_matches_result(target, result, rank)
            for rank, result in enumerate(results, start=1)
        ):
            hits += 1
    return hits / len(targets)


def _reciprocal_rank(results: list[Any], targets: list[dict[str, Any]]) -> float:
    for index, result in enumerate(results, start=1):
        if any(_target_matches_result(target, result, index) for target in targets):
            return 1.0 / index
    return 0.0


def _first_hit(results: list[Any], targets: list[dict[str, Any]]) -> bool:
    return any(
        _target_matches_result(target, result, rank)
        for rank, result in enumerate(results, start=1)
        for target in targets
    )


def _target_matches_result(target: dict[str, Any], result: Any, rank: int) -> bool:
    max_rank = target.get("max_rank")
    if max_rank is not None and rank > int(max_rank):
        return False
    checks = {
        "relative_path": getattr(result, "relative_path", None),
        "unit_type": getattr(result, "unit_type", None),
        "page_no": getattr(result, "page_no", None),
        "chunk_no": getattr(result, "chunk_no", None),
        "image_no": getattr(result, "payload", {}).get("image_no"),
        "table_no": getattr(result, "payload", {}).get("table_no"),
        "unit_id": getattr(result, "payload", {}).get("unit_id"),
    }
    for key, actual in checks.items():
        if key in target and target[key] is not None and str(actual) != str(target[key]):
            return False
    return True


def _unique_results(results: list[Any]) -> list[Any]:
    seen = set()
    result = []
    for item in results:
        key = (
            getattr(item, "relative_path", None),
            getattr(item, "unit_type", None),
            getattr(item, "page_no", None),
            getattr(item, "chunk_no", None),
            getattr(item, "payload", {}).get("image_no"),
            getattr(item, "payload", {}).get("table_no"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _stale_vector_count(records: list[dict[str, Any]], manifest: ManifestStore) -> int:
    count = 0
    for record in records:
        payload = record["payload"]
        workspace_id = payload.get("workspace_id")
        root_id = payload.get("root_id")
        relative_path = payload.get("relative_path")
        unit_id = payload.get("unit_id")
        if (
            not workspace_id
            or not root_id
            or not relative_path
            or not unit_id
            or not manifest.has_unit(
                str(workspace_id),
                str(root_id),
                str(relative_path),
                str(unit_id),
                content_hash=payload.get("content_hash"),
                text_embedding_profile=payload.get("text_embedding_profile"),
                vision_embedding_profile=payload.get("vision_embedding_profile"),
            )
        ):
            count += 1
    return count


def _duplicate_vector_count(records: list[dict[str, Any]]) -> int:
    seen = set()
    duplicates = 0
    for record in records:
        payload = record["payload"]
        key = (
            payload.get("workspace_id"),
            payload.get("root_id"),
            payload.get("relative_path"),
            payload.get("unit_type"),
            payload.get("page_no"),
            payload.get("chunk_no"),
            payload.get("image_no"),
            payload.get("table_no"),
            payload.get("text_embedding_profile"),
            payload.get("vision_embedding_profile"),
        )
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates


def _scan_text_artifact(content: str, path: Path, banned_terms: list[str]):
    return scan_text_artifact(content, path.as_posix(), banned_terms=banned_terms)


def _artifact_label(raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute():
        return raw_path
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return f"<artifact>/{path.name}"
