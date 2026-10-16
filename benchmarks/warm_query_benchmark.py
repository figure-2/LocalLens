from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path
from urllib.parse import urlparse

from locallens.benchmarks.runner import (
    _effective_query_items,
    _latency_summary,
    _load_golden_queries,
    _quality_metrics,
    _query_items,
)
from locallens.core.config import Settings
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.search_service import SearchService
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="warm-query-benchmark")
    parser.add_argument("folder")
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--golden", default=None)
    parser.add_argument("--server-url", default=None)
    parser.add_argument("--allow-remote-server", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--out", default=None)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)

    if args.runs < 1 or args.warmup_runs < 0:
        print(json.dumps({"error": "--runs must be >= 1 and --warmup-runs must be >= 0."}, indent=2))
        return 2
    if args.server_url and not args.allow_remote_server and not _is_loopback_server(args.server_url):
        print(
            json.dumps(
                {"error": "Qdrant server URL must be loopback for release-safe benchmarking."},
                indent=2,
            )
        )
        return 2
    try:
        report = run_warm_query_benchmark(
            folder=Path(args.folder),
            settings=Settings.from_env(),
            queries=args.query,
            golden_path=Path(args.golden) if args.golden else None,
            server_url=args.server_url,
            runs=args.runs,
            warmup_runs=args.warmup_runs,
            allow_remote_server=args.allow_remote_server,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1
    content = json.dumps(report, indent=2)
    findings = scan_text_artifact(
        content,
        args.out or "warm-query-benchmark",
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
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    print(content)
    return 0


def run_warm_query_benchmark(
    folder: Path,
    settings: Settings,
    queries: list[str],
    golden_path: Path | None,
    server_url: str | None,
    runs: int,
    warmup_runs: int,
    allow_remote_server: bool = False,
) -> dict:
    if server_url and not allow_remote_server and not _is_loopback_server(server_url):
        raise ValueError("Qdrant server URL must be loopback for release-safe benchmarking.")
    suffix = str(int(time.time() * 1000))
    with tempfile.TemporaryDirectory(prefix="locallens-warm-query-") as temp_dir:
        run_settings = replace(
            settings,
            data_dir=Path(temp_dir) / "data",
            qdrant_url=server_url or settings.qdrant_url,
            collection_name=f"{settings.collection_name}_warm_{suffix}",
        )
        golden_queries = _load_golden_queries(golden_path) if golden_path else []
        effective_queries = _effective_query_items(golden_queries, queries, run_settings)
        if not effective_queries:
            effective_queries = _query_items(queries or ["local retrieval"])
        store = QdrantStore(run_settings)
        manifest = ManifestStore(run_settings.manifest_path)
        try:
            sync = SyncService(run_settings, store=store, manifest=manifest)
            indexing_start = time.perf_counter()
            sync_report = sync.sync_folder(folder)
            indexing_seconds = time.perf_counter() - indexing_start
            search = SearchService(run_settings, store=store, manifest=manifest)
            cold_pass = _measure_query_pass(search, effective_queries, golden_queries)
            for _ in range(warmup_runs):
                _measure_query_pass(search, effective_queries, golden_queries)
            warm_passes = [
                _measure_query_pass(search, effective_queries, golden_queries)
                for _ in range(runs)
            ]
            return {
                "benchmark_mode": "warm-query",
                "indexed_once": True,
                "reused_collection": True,
                "server_target": _server_target_label(run_settings.qdrant_url),
                "collection_name": store.collection_name,
                "fixture": _path_label(folder),
                "golden": _path_label(golden_path) if golden_path else None,
                "files": sync_report.added + sync_report.updated + sync_report.skipped,
                "units": store.count(),
                "indexing_seconds": indexing_seconds,
                "sync": asdict(sync_report),
                "evaluated_queries": len(effective_queries) if golden_queries else 0,
                "cold_pass": cold_pass,
                "warmup_runs": warmup_runs,
                "runs": runs,
                "warm_passes": warm_passes,
                "warm_aggregate": _aggregate_passes(warm_passes),
            }
        finally:
            try:
                store.drop_collection()
            finally:
                store.close()


def _measure_query_pass(
    search: SearchService,
    query_items: list[dict],
    golden_queries: list[dict],
) -> dict:
    latencies = []
    result_sets = []
    for item in _query_items(query_items):
        start = time.perf_counter()
        results = search.search(
            item["query"],
            top_k=int(item.get("top_k", 10)),
            modality=item.get("modality"),
        )
        latencies.append((time.perf_counter() - start) * 1000)
        result_sets.append(results)
    quality = _quality_metrics(golden_queries and query_items or [], result_sets)
    return {
        "search_latency_ms": _latency_summary(latencies),
        "quality": quality,
    }


def _aggregate_passes(passes: list[dict]) -> dict:
    return {
        "search_latency_ms": {
            metric: _latency_summary(
                [item["search_latency_ms"][metric] for item in passes]
            )
            for metric in ("p50", "p95", "p99")
        }
    }


def _server_target_label(server_url: str | None) -> str:
    if not server_url:
        return "local-path"
    parsed = urlparse(server_url)
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return f"{parsed.scheme}://localhost"
    return f"{parsed.scheme}://remote"


def _is_loopback_server(server_url: str) -> bool:
    parsed = urlparse(server_url)
    return (parsed.hostname or "") in {"localhost", "127.0.0.1", "::1"}


def _path_label(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return f"<external>/{path.name}"


if __name__ == "__main__":
    raise SystemExit(main())
