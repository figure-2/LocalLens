from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from urllib.parse import urlparse

from locallens.benchmarks.runner import run_benchmark, write_report
from locallens.core.config import Settings
from locallens.core.types import ScanReport
from locallens.core.types import BenchmarkReport
from locallens.ingestion.scanner import Scanner
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.result_formatter import to_public_dict
from locallens.retrieval.search_service import SearchService
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import public_path_label
from locallens.security.artifact_scan import scan_artifacts, scan_text_artifact
from locallens.security.artifact_manifest import ManifestEntryError
from locallens.security.artifact_manifest import artifact_paths_from_manifest
from locallens.security.evidence_consistency import check_evidence_consistency
from locallens.security.release_gate import run_release_gate
from locallens.security.release_gate import write_release_gate_report


SKIPPED_SCAN_DIRS = {
    ".git",
    ".locallens",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="locallens")
    sub = parser.add_subparsers(dest="command", required=True)

    index_parser = sub.add_parser("index")
    index_parser.add_argument("folder")

    scan_parser = sub.add_parser("scan")
    scan_parser.add_argument("folder")

    search_parser = sub.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--top-k", type=int, default=10)
    search_parser.add_argument("--modality", choices=["text", "image"], default=None)
    search_parser.add_argument("--ext", default=None)
    search_parser.add_argument("--path-prefix", default=None)

    sub.add_parser("purge")

    bench_parser = sub.add_parser("benchmark")
    bench_parser.add_argument("folder")
    bench_parser.add_argument("--query", action="append", default=[])
    bench_parser.add_argument("--out", default=None)
    bench_parser.add_argument("--golden", default=None)
    bench_parser.add_argument("--blocked-term", action="append", default=[])
    bench_parser.add_argument("--blocked-terms-file", default=None)

    scan_parser = sub.add_parser("scan-artifacts")
    scan_parser.add_argument("paths", nargs="*")
    scan_parser.add_argument("--manifest", action="append", default=[])
    scan_parser.add_argument("--blocked-term", action="append", default=[])
    scan_parser.add_argument("--blocked-terms-file", default=None)
    scan_parser.add_argument("--publication-scan", action="store_true")

    evidence_parser = sub.add_parser("check-evidence-consistency")
    evidence_parser.add_argument("--root", default=".")
    evidence_parser.add_argument("--claims-file", default="release_evidence_claims.json")
    evidence_parser.add_argument(
        "--generated-manifest", default="generated_evidence_artifacts.txt"
    )
    evidence_parser.add_argument("--publication-manifest", action="append", default=[])

    gate_parser = sub.add_parser("release-gate")
    gate_parser.add_argument("--blocked-terms-file", required=True)
    gate_parser.add_argument("--root", default=".")
    gate_parser.add_argument("--out", default=None)
    gate_parser.add_argument("--python", default=None)

    compare_parser = sub.add_parser("compare-stores")
    compare_parser.add_argument("folder")
    compare_parser.add_argument("--golden", default=None)
    compare_parser.add_argument("--server-url", default=None)
    compare_parser.add_argument("--allow-remote-server", action="store_true")
    compare_parser.add_argument("--out", default=None)
    compare_parser.add_argument("--blocked-term", action="append", default=[])
    compare_parser.add_argument("--blocked-terms-file", default=None)
    compare_parser.add_argument("--runs", type=int, default=1)
    compare_parser.add_argument("--warmup-runs", type=int, default=0)

    args = parser.parse_args(argv)
    settings = Settings.from_env()

    if args.command == "index":
        service = SyncService(settings)
        try:
            report = service.sync_folder(args.folder)
            print(json.dumps(asdict(report), indent=2))
        finally:
            service.store.close()
        return 0

    if args.command == "scan":
        report = Scanner(settings).scan(args.folder)
        print(json.dumps(_scan_report_dict(report), indent=2))
        return 0

    if args.command == "search":
        service = SearchService(settings)
        try:
            try:
                results = service.search(
                    args.query,
                    top_k=args.top_k,
                    modality=args.modality,
                    ext=args.ext,
                    path_prefix=args.path_prefix,
                )
            except ValueError as exc:
                print(json.dumps({"error": str(exc)}, indent=2))
                return 2
            print(json.dumps([to_public_dict(item) for item in results], indent=2))
        finally:
            service.store.close()
        return 0

    if args.command == "purge":
        service = SyncService(settings)
        try:
            service.purge()
            print(json.dumps({"status": "purged"}, indent=2))
        finally:
            service.store.close()
        return 0

    if args.command == "benchmark":
        queries = args.query or ["project notes", "planning document", "image file"]
        report = run_benchmark(args.folder, queries, settings, golden_path=args.golden)
        if _has_sync_failures(report):
            print(json.dumps(_sync_failure_error("benchmark", report), indent=2))
            return 1
        out_path = Path(args.out) if args.out else settings.data_dir / "benchmark.json"
        blocked_terms = _blocked_terms(args.blocked_term, args.blocked_terms_file)
        try:
            write_report(report, out_path, banned_terms=blocked_terms)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        print(json.dumps(asdict(report), indent=2))
        return 0

    if args.command == "scan-artifacts":
        try:
            raw_paths = list(args.paths) + _manifest_artifact_paths(args.manifest)
        except ManifestEntryError as exc:
            print(
                json.dumps(
                    {
                        "error": "artifact manifest contains unsafe path",
                        "manifest": public_path_label(exc.manifest.as_posix()),
                        "line": exc.line_no,
                        "reason": exc.reason,
                    },
                    indent=2,
                )
            )
            return 1
        if not raw_paths:
            print(json.dumps({"error": "artifact paths or --manifest are required"}, indent=2))
            return 2
        blocked_terms = _blocked_terms(args.blocked_term, args.blocked_terms_file)
        if _requires_publication_terms(args.manifest, args.publication_scan) and not blocked_terms:
            print(
                json.dumps(
                    {
                        "error": (
                            "publication scan requires --blocked-terms-file "
                            "or --blocked-term with at least one active term"
                        )
                    },
                    indent=2,
                )
            )
            return 2
        paths = _artifact_paths(raw_paths)
        findings = scan_artifacts(paths, banned_terms=blocked_terms)
        print(
            json.dumps(
                {
                    "scanned": len(paths),
                    "findings": public_findings(findings),
                },
                indent=2,
            )
        )
        return 1 if findings else 0

    if args.command == "check-evidence-consistency":
        report = check_evidence_consistency(
            root=Path(args.root),
            claims_file=args.claims_file,
            generated_manifest=args.generated_manifest,
            publication_manifests=args.publication_manifest or None,
        )
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "passed" else 1

    if args.command == "release-gate":
        report = run_release_gate(
            root=Path(args.root),
            blocked_terms_file=args.blocked_terms_file,
            python_executable=args.python or sys.executable,
        )
        if args.out:
            write_release_gate_report(report, args.out)
        print(json.dumps(report, indent=2))
        return 0 if report.get("status") == "passed" else 1

    if args.command == "compare-stores":
        server_url = args.server_url or settings.qdrant_url
        if not server_url:
            print(json.dumps({"error": "Qdrant server URL is required."}, indent=2))
            return 1
        if not args.allow_remote_server and not _is_loopback_server(server_url):
            print(
                json.dumps(
                    {"error": "Qdrant server URL must be loopback for release-safe comparison."},
                    indent=2,
                )
            )
            return 1
        if args.runs < 1 or args.warmup_runs < 0:
            print(
                json.dumps(
                    {"error": "--runs must be >= 1 and --warmup-runs must be >= 0."},
                    indent=2,
                )
            )
            return 2
        blocked_terms = _blocked_terms(args.blocked_term, args.blocked_terms_file)
        measured_runs = []
        try:
            for index in range(args.warmup_runs + args.runs):
                local_report, server_report = _run_compare_pair(
                    args.folder,
                    settings,
                    server_url,
                    args.golden,
                    index,
                )
                if _has_sync_failures(local_report):
                    print(
                        json.dumps(
                            _sync_failure_error("local benchmark", local_report),
                            indent=2,
                        )
                    )
                    return 1
                if _has_sync_failures(server_report):
                    print(
                        json.dumps(
                            _sync_failure_error("server benchmark", server_report),
                            indent=2,
                        )
                    )
                    return 1
                if index >= args.warmup_runs:
                    measured_runs.append(
                        _comparison_measurement(local_report, server_report)
                    )
            if args.runs == 1 and args.warmup_runs == 0:
                comparison = {
                    "server_target": _server_target_label(server_url),
                    **measured_runs[0],
                }
            else:
                comparison = _comparison_report_repeated(
                    measured_runs,
                    server_url,
                    runs=args.runs,
                    warmup_runs=args.warmup_runs,
                )
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        content = json.dumps(comparison, indent=2)
        findings = scan_text_artifact(content, args.out or "compare-stores", blocked_terms)
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

    return 2


def _run_compare_pair(
    folder: str,
    settings: Settings,
    server_url: str,
    golden_path: str | None,
    index: int,
) -> tuple[BenchmarkReport, BenchmarkReport]:
    suffix = f"{int(time.time() * 1000)}_{index}"
    local_settings = replace(
        settings,
        qdrant_url=None,
        collection_name=f"{settings.collection_name}_local_{suffix}",
    )
    server_settings = replace(
        settings,
        qdrant_url=server_url,
        collection_name=f"{settings.collection_name}_server_{suffix}",
    )
    local_report = run_benchmark(
        folder,
        [],
        local_settings,
        golden_path=golden_path,
        drop_collection=True,
    )
    if _has_sync_failures(local_report):
        return local_report, BenchmarkReport(
            files=0,
            units=0,
            indexing_seconds=0.0,
            files_per_second=0.0,
            units_per_second=0.0,
            search_latency_ms={"p50": 0.0, "p95": 0.0, "p99": 0.0},
            collection_name="not-run",
            text_embedding_profile=local_report.text_embedding_profile,
            vision_embedding_profile=local_report.vision_embedding_profile,
            text_dimension=local_report.text_dimension,
            vision_dimension=local_report.vision_dimension,
            evaluated_queries=0,
            recall_at_5=None,
            recall_at_10=None,
            mrr_at_10=None,
            stale_vector_count=0,
            duplicate_vector_count=0,
            qdrant_disk_bytes=0,
            sync=local_report.sync,
        )
    server_report = run_benchmark(
        folder,
        [],
        server_settings,
        golden_path=golden_path,
        drop_collection=True,
    )
    return local_report, server_report


def _comparison_measurement(
    local_report: BenchmarkReport,
    server_report: BenchmarkReport,
) -> dict:
    local = asdict(local_report)
    server = asdict(server_report)
    return {
        "local": local,
        "server": server,
        "delta": {
            "indexing_seconds": server_report.indexing_seconds
            - local_report.indexing_seconds,
            "search_p50_ms": server_report.search_latency_ms["p50"]
            - local_report.search_latency_ms["p50"],
            "search_p95_ms": server_report.search_latency_ms["p95"]
            - local_report.search_latency_ms["p95"],
            "search_p99_ms": server_report.search_latency_ms["p99"]
            - local_report.search_latency_ms["p99"],
        },
    }


def _comparison_report_repeated(
    measurements: list[dict],
    server_url: str,
    runs: int,
    warmup_runs: int,
) -> dict:
    return {
        "server_target": _server_target_label(server_url),
        "runs": runs,
        "warmup_runs": warmup_runs,
        "measurements": measurements,
        "aggregate": {
            "local": _aggregate_reports([item["local"] for item in measurements]),
            "server": _aggregate_reports([item["server"] for item in measurements]),
            "delta": _aggregate_deltas([item["delta"] for item in measurements]),
        },
    }


def _aggregate_reports(reports: list[dict]) -> dict:
    return {
        "indexing_seconds": _metric_summary(
            [float(item["indexing_seconds"]) for item in reports]
        ),
        "search_p50_ms": _metric_summary(
            [float(item["search_latency_ms"]["p50"]) for item in reports]
        ),
        "search_p95_ms": _metric_summary(
            [float(item["search_latency_ms"]["p95"]) for item in reports]
        ),
        "search_p99_ms": _metric_summary(
            [float(item["search_latency_ms"]["p99"]) for item in reports]
        ),
        "recall_at_10": _metric_summary(
            [float(item["recall_at_10"] or 0.0) for item in reports]
        ),
        "mrr_at_10": _metric_summary(
            [float(item["mrr_at_10"] or 0.0) for item in reports]
        ),
    }


def _aggregate_deltas(deltas: list[dict]) -> dict:
    return {
        name: _metric_summary([float(item[name]) for item in deltas])
        for name in ("indexing_seconds", "search_p50_ms", "search_p95_ms", "search_p99_ms")
    }


def _metric_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
        "p50": _nearest_percentile(ordered, 50),
        "p95": _nearest_percentile(ordered, 95),
        "p99": _nearest_percentile(ordered, 99),
    }


def _nearest_percentile(values: list[float], percentile: int) -> float:
    if len(values) == 1:
        return values[0]
    index = int(round((percentile / 100) * (len(values) - 1)))
    return values[max(0, min(index, len(values) - 1))]


def _has_sync_failures(report: BenchmarkReport) -> bool:
    return report.sync.failed > 0


def _sync_failure_error(label: str, report: BenchmarkReport) -> dict:
    return {
        "error": f"{label} failed during indexing",
        "failed": report.sync.failed,
        "sync": asdict(report.sync),
    }


def _blocked_terms(terms: list[str], terms_file: str | None) -> list[str]:
    return load_blocked_terms(terms, terms_file)


def _server_target_label(server_url: str) -> str:
    parsed = urlparse(server_url)
    if not parsed.scheme:
        return "configured-server"
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return f"{parsed.scheme}://localhost"
    return f"{parsed.scheme}://remote"


def _is_loopback_server(server_url: str) -> bool:
    parsed = urlparse(server_url)
    host = parsed.hostname or ""
    return host in {"localhost", "127.0.0.1", "::1"}


def _scan_report_dict(report: ScanReport) -> dict:
    return {
        "root_id": report.root_id,
        "included": len(report.files),
        "excluded": len(report.excluded),
        "files": [
            {
                "relative_path": item.relative_path,
                "file_type": item.file_type,
                "mime_type": item.mime_type,
                "ext": item.ext,
                "size_bytes": item.size_bytes,
            }
            for item in report.files
        ],
        "excluded_paths": [asdict(item) for item in report.excluded],
    }


def _artifact_paths(raw_paths: list[str | Path]) -> list[Path]:
    paths: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path)
        if path.is_dir():
            paths.extend(_iter_artifacts(path))
        else:
            paths.append(path)
    return sorted(set(paths), key=lambda item: item.as_posix())


def _manifest_artifact_paths(raw_manifests: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw_manifest in raw_manifests:
        paths.extend(artifact_paths_from_manifest(Path(raw_manifest)))
    return paths


def _requires_publication_terms(
    raw_manifests: list[str], publication_scan: bool = False
) -> bool:
    if publication_scan:
        return True
    return any(
        Path(manifest).name
        in {"publication_artifacts.txt", "generated_evidence_artifacts.txt"}
        for manifest in raw_manifests
    )


def _iter_artifacts(root: Path):
    for path in root.rglob("*"):
        if any(part in SKIPPED_SCAN_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


if __name__ == "__main__":
    raise SystemExit(main())
