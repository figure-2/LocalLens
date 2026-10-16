from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.warm_query_benchmark import (
    _path_label,
    _server_target_label,
    run_warm_query_benchmark,
)
from locallens.core.config import Settings
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


DEFAULT_SIZES = [1000, 5000, 10000]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qdrant-scale-benchmark")
    parser.add_argument("--sizes", nargs="+", type=int, default=DEFAULT_SIZES)
    parser.add_argument("--queries", type=int, default=20)
    parser.add_argument("--server-url", default="http://localhost:6333")
    parser.add_argument("--allow-remote-server", action="store_true")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--out", default=None)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)

    if any(size < 1 for size in args.sizes):
        print(json.dumps({"error": "--sizes must contain positive integers."}, indent=2))
        return 2
    if args.queries < 1 or args.runs < 1 or args.warmup_runs < 0:
        print(
            json.dumps(
                {
                    "error": (
                        "--queries and --runs must be >= 1; "
                        "--warmup-runs must be >= 0."
                    )
                },
                indent=2,
            )
        )
        return 2
    if not args.allow_remote_server and not _is_loopback_server(args.server_url):
        print(
            json.dumps(
                {"error": "Qdrant server URL must be loopback for release-safe benchmarking."},
                indent=2,
            )
        )
        return 2

    try:
        report = run_qdrant_scale_benchmark(
            settings=Settings.from_env(),
            sizes=args.sizes,
            queries_per_size=args.queries,
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
        args.out or "qdrant-scale-benchmark",
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


def run_qdrant_scale_benchmark(
    settings: Settings,
    sizes: list[int],
    queries_per_size: int,
    server_url: str,
    runs: int,
    warmup_runs: int,
    allow_remote_server: bool = False,
) -> dict:
    if any(size < 1 for size in sizes):
        raise ValueError("sizes must contain positive integers.")
    if queries_per_size < 1 or runs < 1 or warmup_runs < 0:
        raise ValueError("queries and runs must be >= 1; warmup_runs must be >= 0.")
    if not allow_remote_server and not _is_loopback_server(server_url):
        raise ValueError("Qdrant server URL must be loopback for release-safe benchmarking.")

    with tempfile.TemporaryDirectory(prefix="locallens-qdrant-scale-") as temp_dir:
        root = Path(temp_dir)
        results = []
        for size in sizes:
            corpus = root / f"corpus_{size}"
            query_count = min(size, queries_per_size)
            _write_scale_corpus(corpus, size)
            queries = _scale_queries(size, query_count)
            local = run_warm_query_benchmark(
                folder=corpus,
                settings=settings,
                queries=queries,
                golden_path=None,
                server_url=None,
                runs=runs,
                warmup_runs=warmup_runs,
                allow_remote_server=allow_remote_server,
            )
            server = run_warm_query_benchmark(
                folder=corpus,
                settings=settings,
                queries=queries,
                golden_path=None,
                server_url=server_url,
                runs=runs,
                warmup_runs=warmup_runs,
                allow_remote_server=allow_remote_server,
            )
            local_summary = _summary(local, query_count)
            server_summary = _summary(server, query_count)
            results.append(
                {
                    "files": size,
                    "queries": query_count,
                    "corpus": _path_label(corpus),
                    "local": local_summary,
                    "server": server_summary,
                    "delta": _delta(local_summary, server_summary),
                }
            )
    return {
        "benchmark_mode": "qdrant-scale-warm-query",
        "profile": "hash-smoke",
        "claim_scope": "synthetic local/server warm-query comparison",
        "sizes": sizes,
        "queries_per_size": queries_per_size,
        "runs": runs,
        "warmup_runs": warmup_runs,
        "server_target": _server_target_label(server_url),
        "results": results,
    }


def _write_scale_corpus(corpus: Path, size: int) -> None:
    corpus.mkdir(parents=True, exist_ok=True)
    for index in range(size):
        bucket = corpus / f"group_{index // 1000:02d}"
        bucket.mkdir(parents=True, exist_ok=True)
        marker = _scale_marker(index)
        content = (
            f"# Scale document {index}\n\n"
            f"Local retrieval scale fixture {marker}.\n"
            f"Topic bucket {index % 17} with deterministic text for query latency.\n"
        )
        (bucket / f"doc_{index:05d}.md").write_text(content, encoding="utf-8")


def _scale_queries(size: int, query_count: int) -> list[str]:
    return [_scale_marker(index) for index in _query_indices(size, query_count)]


def _query_indices(size: int, count: int) -> list[int]:
    if count >= size:
        return list(range(size))
    if count == 1:
        return [0]
    step = (size - 1) / (count - 1)
    return sorted({int(round(step * index)) for index in range(count)})


def _scale_marker(index: int) -> str:
    return f"llscale-{index:05d}-target"


def _summary(report: dict, query_count: int) -> dict:
    warm = report["warm_aggregate"]["search_latency_ms"]
    return {
        "server_target": report["server_target"],
        "files": report["files"],
        "units": report["units"],
        "indexing_seconds": report["indexing_seconds"],
        "sync_failed": report["sync"]["failed"],
        "measured_queries": query_count,
        "cold_latency_ms": report["cold_pass"]["search_latency_ms"],
        "warm_latency_ms": {
            "p50": warm["p50"]["p50"],
            "p95": warm["p95"]["p50"],
            "p99": warm["p99"]["p50"],
        },
        "quality_scope": "not-evaluated",
    }


def _delta(local_summary: dict, server_summary: dict) -> dict:
    return {
        "indexing_seconds": (
            server_summary["indexing_seconds"] - local_summary["indexing_seconds"]
        ),
        "cold_p50_ms": (
            server_summary["cold_latency_ms"]["p50"]
            - local_summary["cold_latency_ms"]["p50"]
        ),
        "cold_p95_ms": (
            server_summary["cold_latency_ms"]["p95"]
            - local_summary["cold_latency_ms"]["p95"]
        ),
        "cold_p99_ms": (
            server_summary["cold_latency_ms"]["p99"]
            - local_summary["cold_latency_ms"]["p99"]
        ),
        "warm_p50_ms": (
            server_summary["warm_latency_ms"]["p50"]
            - local_summary["warm_latency_ms"]["p50"]
        ),
        "warm_p95_ms": (
            server_summary["warm_latency_ms"]["p95"]
            - local_summary["warm_latency_ms"]["p95"]
        ),
        "warm_p99_ms": (
            server_summary["warm_latency_ms"]["p99"]
            - local_summary["warm_latency_ms"]["p99"]
        ),
    }


def _is_loopback_server(server_url: str) -> bool:
    parsed = urlparse(server_url)
    return (parsed.hostname or "") in {"localhost", "127.0.0.1", "::1"}


if __name__ == "__main__":
    raise SystemExit(main())
