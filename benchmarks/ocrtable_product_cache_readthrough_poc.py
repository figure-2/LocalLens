from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.ocrtable_warm_cache_poc import METRIC_FIELDS
from benchmarks.ocrtable_warm_cache_poc import _cache_key
from benchmarks.ocrtable_warm_cache_poc import _cache_payload
from benchmarks.ocrtable_warm_cache_poc import _candidate
from benchmarks.ocrtable_warm_cache_poc import _file_digest
from benchmarks.ocrtable_warm_cache_poc import _metrics_from_details
from locallens.core.config import Settings
from locallens.indexing.manifest import ManifestStore
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


SCHEMA_VERSION = "ocrtable-product-cache-readthrough-poc-v1"
WORKSPACE_ID = "scanned-table-poc"
ROOT_ID = "pdf-fixture"
TEXT_PROFILE = "benchmark-only"
VISION_PROFILE = "benchmark-only"
EXTRACTOR_PROFILE = "ocrtable-readthrough-poc-v1"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_product_cache_readthrough_poc(
        cold_report_path=Path(args.cold_report),
        pdf_dir=Path(args.pdf_dir),
        candidate=args.candidate,
        data_dir=Path(args.data_dir) if args.data_dir else None,
        simulate_corrupt=args.simulate_corrupt,
    )
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    findings = scan_text_artifact(
        content,
        args.out or "ocrtable-product-cache-readthrough-poc",
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
        Path(args.out).write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


def run_product_cache_readthrough_poc(
    *,
    cold_report_path: Path,
    pdf_dir: Path,
    candidate: str = "paddleocr-structure",
    data_dir: Path | None = None,
    simulate_corrupt: bool = False,
) -> dict:
    cold_report = json.loads(cold_report_path.read_text(encoding="utf-8"))
    cold_row = _candidate(cold_report, candidate)
    details = cold_row.get("documents_detail")
    if not isinstance(details, list) or not details:
        raise ValueError("cold report must include document details")
    if cold_row.get("status") != "ok":
        raise ValueError("cold candidate status must be ok")

    with _data_dir(data_dir) as cache_data_dir:
        settings = Settings(data_dir=cache_data_dir, workspace_id=WORKSPACE_ID)
        settings.ensure_dirs()
        manifest = ManifestStore(settings.manifest_path)
        write_latencies: list[float] = []
        written_keys: list[dict] = []

        for index, detail in enumerate(details):
            started = time.perf_counter()
            entry = _stage_document_result(
                manifest=manifest,
                settings=settings,
                pdf_dir=pdf_dir,
                cold_row=cold_row,
                detail=detail,
            )
            if simulate_corrupt and index == 0:
                (settings.cache_dir / entry["blob_rel_path"]).write_text(
                    "{\"corrupt\": true}\n",
                    encoding="utf-8",
                )
            manifest.commit_staged_cache_entries(
                WORKSPACE_ID,
                ROOT_ID,
                entry["relative_path"],
                entry["content_hash"],
            )
            written_keys.append(entry)
            write_latencies.append((time.perf_counter() - started) * 1000)

        warm_rows: list[dict] = []
        read_latencies: list[float] = []
        cache_result_hits = 0
        cache_result_misses = 0
        cache_corrupt_skipped = 0

        for entry in written_keys:
            started = time.perf_counter()
            cached = manifest.committed_cache_entry(
                cache_key=entry["cache_key"],
                workspace_id=WORKSPACE_ID,
                root_id=ROOT_ID,
                relative_path=entry["relative_path"],
                content_hash=entry["content_hash"],
                entry_type="document_result",
            )
            if cached is None:
                cache_result_misses += 1
            else:
                payload = _read_payload(settings.cache_dir, cached)
                if payload is None:
                    cache_result_misses += 1
                    cache_corrupt_skipped += 1
                else:
                    cache_result_hits += 1
                    warm_rows.append(payload)
            read_latencies.append((time.perf_counter() - started) * 1000)

        stale_validation = _stale_validation(manifest, written_keys)
        cold_metrics = _metrics_from_details(details)
        warm_metrics = _metrics_from_details(warm_rows)
        metric_delta = {
            key: round(warm_metrics.get(key, 0.0) - cold_metrics.get(key, 0.0), 9)
            for key in METRIC_FIELDS
        }
        report = {
            "schema_version": SCHEMA_VERSION,
            "source": "benchmark-only",
            "default_enabled": False,
            "candidate": candidate,
            "cold_source_report": cold_report_path.name,
            "cache_mode": "manifest-owned-document-result-read-through-poc",
            "search_time_cache_source_allowed": False,
            "cache_entries_written": len(written_keys),
            "cache_result_hits": cache_result_hits,
            "cache_result_misses": cache_result_misses,
            "cache_corrupt_skipped": cache_corrupt_skipped,
            "warm_cache_hit_rate": round(
                cache_result_hits / len(written_keys), 6
            ),
            "queries": len(details),
            "cold_metrics": cold_metrics,
            "warm_metrics": warm_metrics,
            "metric_delta": metric_delta,
            "metrics_non_regression": all(
                value >= 0.0 for value in metric_delta.values()
            ),
            "cold_latency_ms": {
                "p50": float(cold_row.get("p50_latency_ms") or 0.0),
                "p95": float(cold_row.get("p95_latency_ms") or 0.0),
            },
            "warm_latency_ms": {
                "write_p50": _median(write_latencies),
                "write_p95": _p95(write_latencies),
                "read_p50": _median(read_latencies),
                "read_p95": _p95(read_latencies),
            },
            "latency_improvement": {
                "p95_ms_delta": round(
                    _p95(read_latencies) - float(cold_row["p95_latency_ms"]), 3
                ),
                "warm_read_p95_below_1500_ms": _p95(read_latencies) <= 1500.0,
            },
            "stale_validation": stale_validation,
            "claim_boundary": {
                "product_cache_claim_allowed": False,
                "public_performance_claim_allowed": False,
                "reason": (
                    "read-through POC uses manifest-owned cache validation; "
                    "product extractor integration and public claims require "
                    "a separate decision"
                ),
            },
        }
    return report


def _stage_document_result(
    *,
    manifest: ManifestStore,
    settings: Settings,
    pdf_dir: Path,
    cold_row: dict,
    detail: dict,
) -> dict:
    relative_path = str(detail["relative_path"])
    pdf_path = pdf_dir / relative_path
    content_hash = _file_digest(pdf_path)
    file_id = _text_digest(relative_path)[:24]
    cache_key = _cache_key(pdf_dir, cold_row, detail)
    payload = _cache_payload(detail)
    payload_sha256 = _payload_sha256(payload)
    blob_rel_path = (
        "product_cache/ocrtable_readthrough/"
        f"{_text_digest(cache_key)[:32]}.json"
    )
    blob_path = settings.cache_dir / blob_rel_path
    blob_path.parent.mkdir(parents=True, exist_ok=True)
    blob_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    stat = pdf_path.stat()
    manifest.upsert_file(
        workspace_id=WORKSPACE_ID,
        root_id=ROOT_ID,
        relative_path=relative_path,
        file_id=file_id,
        content_hash=content_hash,
        mtime_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
        text_embedding_profile=TEXT_PROFILE,
        vision_embedding_profile=VISION_PROFILE,
        extractor_profile=EXTRACTOR_PROFILE,
        point_ids=[],
    )
    manifest.stage_cache_entry(
        cache_key=cache_key,
        workspace_id=WORKSPACE_ID,
        root_id=ROOT_ID,
        relative_path=relative_path,
        file_id=file_id,
        unit_id="",
        content_hash=content_hash,
        entry_type="document_result",
        payload_sha256=payload_sha256,
        blob_rel_path=blob_rel_path,
    )
    return {
        "cache_key": cache_key,
        "relative_path": relative_path,
        "content_hash": content_hash,
        "blob_rel_path": blob_rel_path,
    }


def _read_payload(cache_dir: Path, entry: dict) -> dict | None:
    blob_path = _safe_cache_path(cache_dir, str(entry["blob_rel_path"]))
    if blob_path is None or not blob_path.exists():
        return None
    try:
        payload = json.loads(blob_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if _payload_sha256(payload) != entry["payload_sha256"]:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _stale_validation(manifest: ManifestStore, entries: list[dict]) -> dict:
    if not entries:
        return {
            "content_hash_mismatch_rejected": False,
            "removed_manifest_file_rejected": False,
        }
    first = entries[0]
    mismatch = manifest.committed_cache_entry(
        cache_key=first["cache_key"],
        workspace_id=WORKSPACE_ID,
        root_id=ROOT_ID,
        relative_path=first["relative_path"],
        content_hash="wrong-content-hash",
        entry_type="document_result",
    )
    manifest.remove_file(WORKSPACE_ID, ROOT_ID, first["relative_path"])
    removed = manifest.committed_cache_entry(
        cache_key=first["cache_key"],
        workspace_id=WORKSPACE_ID,
        root_id=ROOT_ID,
        relative_path=first["relative_path"],
        content_hash=first["content_hash"],
        entry_type="document_result",
    )
    return {
        "content_hash_mismatch_rejected": mismatch is None,
        "removed_manifest_file_rejected": removed is None,
    }


def _payload_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 6) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 6)
    ordered = sorted(values)
    index = (len(ordered) - 1) * 0.95
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def _safe_cache_path(cache_dir: Path, blob_rel_path: str) -> Path | None:
    root = cache_dir.resolve()
    candidate = (cache_dir / blob_rel_path).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


@contextmanager
def _data_dir(path: Path | None) -> Iterator[Path]:
    if path is not None:
        path.mkdir(parents=True, exist_ok=True)
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="locallens-ocrtable-cache-") as temp_dir:
        yield Path(temp_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("cold_report")
    parser.add_argument("--pdf-dir", default="benchmarks/fixtures/pdf_corpus")
    parser.add_argument("--candidate", default="paddleocr-structure")
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--simulate-corrupt", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
