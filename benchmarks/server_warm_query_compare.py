from __future__ import annotations

import argparse
import json
import sys
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="server-warm-query-compare")
    parser.add_argument("folder")
    parser.add_argument("--golden", default=None)
    parser.add_argument("--server-url", default="http://localhost:6333")
    parser.add_argument("--allow-remote-server", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--out", default=None)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)

    if args.runs < 1 or args.warmup_runs < 0:
        print(
            json.dumps(
                {"error": "--runs must be >= 1 and --warmup-runs must be >= 0."},
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
        report = run_server_warm_query_compare(
            folder=Path(args.folder),
            settings=Settings.from_env(),
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
        args.out or "server-warm-query-compare",
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


def run_server_warm_query_compare(
    folder: Path,
    settings: Settings,
    golden_path: Path | None,
    server_url: str,
    runs: int,
    warmup_runs: int,
    allow_remote_server: bool = False,
) -> dict:
    if not allow_remote_server and not _is_loopback_server(server_url):
        raise ValueError("Qdrant server URL must be loopback for release-safe benchmarking.")
    local = run_warm_query_benchmark(
        folder=folder,
        settings=settings,
        queries=[],
        golden_path=golden_path,
        server_url=None,
        runs=runs,
        warmup_runs=warmup_runs,
        allow_remote_server=allow_remote_server,
    )
    server = run_warm_query_benchmark(
        folder=folder,
        settings=settings,
        queries=[],
        golden_path=golden_path,
        server_url=server_url,
        runs=runs,
        warmup_runs=warmup_runs,
        allow_remote_server=allow_remote_server,
    )
    return {
        "benchmark_mode": "local-server-warm-query-compare",
        "fixture": _path_label(folder),
        "golden": _path_label(golden_path) if golden_path else None,
        "runs": runs,
        "warmup_runs": warmup_runs,
        "server_target": _server_target_label(server_url),
        "local": local,
        "server": server,
        "delta": _delta_report(local, server),
    }


def _delta_report(local: dict, server: dict) -> dict:
    local_warm = local["warm_aggregate"]["search_latency_ms"]
    server_warm = server["warm_aggregate"]["search_latency_ms"]
    return {
        "indexing_seconds": server["indexing_seconds"] - local["indexing_seconds"],
        "cold_p50_ms": _latency(server, "cold_pass", "p50")
        - _latency(local, "cold_pass", "p50"),
        "cold_p95_ms": _latency(server, "cold_pass", "p95")
        - _latency(local, "cold_pass", "p95"),
        "cold_p99_ms": _latency(server, "cold_pass", "p99")
        - _latency(local, "cold_pass", "p99"),
        "warm_p50_ms": server_warm["p50"]["p50"] - local_warm["p50"]["p50"],
        "warm_p95_ms": server_warm["p95"]["p50"] - local_warm["p95"]["p50"],
        "warm_p99_ms": server_warm["p99"]["p50"] - local_warm["p99"]["p50"],
    }


def _latency(report: dict, pass_name: str, metric: str) -> float:
    return float(report[pass_name]["search_latency_ms"][metric])


def _is_loopback_server(server_url: str) -> bool:
    parsed = urlparse(server_url)
    return (parsed.hostname or "") in {"localhost", "127.0.0.1", "::1"}


if __name__ == "__main__":
    raise SystemExit(main())
