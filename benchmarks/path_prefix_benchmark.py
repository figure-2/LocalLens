from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from locallens.core.config import Settings
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.search_service import SearchService
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="path-prefix-benchmark")
    parser.add_argument("--files", type=int, default=600)
    parser.add_argument("--target-files", type=int, default=60)
    parser.add_argument("--queries", type=int, default=20)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--out", default=None)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)

    report = run_path_prefix_benchmark(
        files=args.files,
        target_files=args.target_files,
        queries=args.queries,
        runs=args.runs,
    )
    content = json.dumps(report, indent=2)
    findings = scan_text_artifact(
        content,
        args.out or "path-prefix-benchmark",
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


def run_path_prefix_benchmark(
    files: int = 600,
    target_files: int = 60,
    queries: int = 20,
    runs: int = 1,
) -> dict:
    if files < 2:
        raise ValueError("--files must be >= 2")
    if target_files < 1 or target_files >= files:
        raise ValueError("--target-files must be between 1 and files - 1")
    if queries < 1:
        raise ValueError("--queries must be >= 1")
    if runs < 1:
        raise ValueError("--runs must be >= 1")

    measurements = [
        _run_once(files=files, target_files=target_files, queries=queries)
        for _ in range(runs)
    ]
    return {
        "files": files,
        "scoped_files": target_files,
        "decoy_files": files - target_files,
        "queries": queries,
        "runs": runs,
        "measurements": measurements,
        "aggregate": _aggregate_measurements(measurements),
    }


def _run_once(files: int, target_files: int, queries: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="locallens-prefix-") as temp_dir:
        temp_path = Path(temp_dir)
        corpus = temp_path / "corpus"
        _write_corpus(corpus, files=files, target_files=target_files)
        settings = Settings(data_dir=temp_path / "data")
        store = QdrantStore(settings, in_memory=True)
        manifest = ManifestStore(settings.manifest_path)
        sync = SyncService(settings, store=store, manifest=manifest)
        start = time.perf_counter()
        sync_report = sync.sync_folder(corpus)
        indexing_seconds = time.perf_counter() - start
        search = SearchService(settings, store=store, manifest=manifest)
        matching_paths_count = len(
            manifest.matching_paths(settings.workspace_id, "scope")
        )
        full_latencies = []
        prefix_latencies = []
        target_hits = []
        query = "shared prefix benchmark target"
        for _ in range(queries):
            start = time.perf_counter()
            full_results = search.search(query, top_k=10)
            full_latencies.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            prefix_results = search.search(query, top_k=10, path_prefix="scope")
            prefix_latencies.append((time.perf_counter() - start) * 1000)
            target_hits.append(
                bool(prefix_results)
                and all(item.relative_path.startswith("scope/") for item in prefix_results)
            )
            if not full_results:
                target_hits.append(False)
        store.close()

    return {
        "sync": asdict(sync_report),
        "indexing_seconds": indexing_seconds,
        "matching_paths_count": matching_paths_count,
        "full_search_ms": _latency_summary(full_latencies),
        "prefix_search_ms": _latency_summary(prefix_latencies),
        "prefix_all_results_in_scope": all(target_hits),
    }


def _write_corpus(root: Path, files: int, target_files: int) -> None:
    target = root / "scope"
    archive = root / "archive"
    target.mkdir(parents=True)
    archive.mkdir(parents=True)
    for index in range(target_files):
        (target / f"note_{index:04d}.md").write_text(
            f"shared prefix benchmark target team note {index}\n",
            encoding="utf-8",
        )
    for index in range(files - target_files):
        (archive / f"note_{index:04d}.md").write_text(
            f"shared prefix benchmark target archive note {index}\n",
            encoding="utf-8",
        )


def _latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
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


def _aggregate_measurements(measurements: list[dict]) -> dict:
    return {
        "indexing_seconds": _summary(
            [float(item["indexing_seconds"]) for item in measurements]
        ),
        "full_search_p50_ms": _summary(
            [float(item["full_search_ms"]["p50"]) for item in measurements]
        ),
        "prefix_search_p50_ms": _summary(
            [float(item["prefix_search_ms"]["p50"]) for item in measurements]
        ),
        "prefix_all_results_in_scope": all(
            bool(item["prefix_all_results_in_scope"]) for item in measurements
        ),
    }


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
        "p50": _percentile(ordered, 50),
    }


if __name__ == "__main__":
    raise SystemExit(main())
