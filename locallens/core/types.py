from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScannedFile:
    root_id: str
    root_path: Path
    relative_path: str
    file_type: str
    mime_type: str
    ext: str
    size_bytes: int
    mtime_ns: int
    content_hash: str


@dataclass(frozen=True)
class ExcludedPath:
    relative_path: str
    reason: str


@dataclass
class ScanReport:
    root_id: str = ""
    root_path: Path | None = None
    files: list[ScannedFile] = field(default_factory=list)
    excluded: list[ExcludedPath] = field(default_factory=list)


@dataclass(frozen=True)
class IndexedUnit:
    workspace_id: str
    root_id: str
    file_id: str
    unit_id: str
    unit_type: str
    relative_path: str
    mime_type: str
    ext: str
    size_bytes: int
    mtime_ns: int
    content_hash: str
    modality: str
    text: str = ""
    text_preview: str = ""
    page_no: int | None = None
    chunk_no: int | None = None
    image_no: int | None = None
    table_no: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    source_kind: str = ""
    extractor_profile: str = ""
    source_path: Path | None = None
    locality: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    score: float
    modality: str
    relative_path: str
    page_no: int | None
    snippet: str
    unit_type: str
    chunk_no: int | None = None
    embedding_profile: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncFailure:
    relative_path: str
    error_type: str
    message: str


@dataclass
class SyncReport:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    excluded: int = 0
    failed: int = 0
    units: int = 0
    failures: list[SyncFailure] = field(default_factory=list)
    cancelled: bool = False
    ocr_attempted: int = 0
    ocr_succeeded: int = 0
    ocr_empty: int = 0
    table_attempted: int = 0
    table_succeeded: int = 0
    table_empty: int = 0
    vlm_attempted: int = 0
    vlm_succeeded: int = 0
    vlm_empty: int = 0
    vlm_failed: int = 0
    cache_page_hits: int = 0
    cache_page_misses: int = 0
    cache_roi_hits: int = 0
    cache_roi_misses: int = 0
    cache_result_hits: int = 0
    cache_result_misses: int = 0
    cache_entries_written: int = 0
    cache_entries_deleted: int = 0
    cache_stale_deleted: int = 0
    cache_corrupt_skipped: int = 0


@dataclass(frozen=True)
class SyncProgress:
    phase: str
    processed: int
    total: int
    relative_path: str = ""
    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    excluded: int = 0
    failed: int = 0
    unit_processed: int = 0
    unit_total: int = 0
    detail: str = ""


@dataclass
class ExtractionStats:
    ocr_attempted: int = 0
    ocr_succeeded: int = 0
    ocr_empty: int = 0
    table_attempted: int = 0
    table_succeeded: int = 0
    table_empty: int = 0
    vlm_attempted: int = 0
    vlm_succeeded: int = 0
    vlm_empty: int = 0
    vlm_failed: int = 0
    cache_result_hits: int = 0
    cache_result_misses: int = 0
    cache_corrupt_skipped: int = 0


@dataclass(frozen=True)
class LocalityReport:
    runtime_network_calls: int = 0
    automatic_model_downloads: int = 0
    local_cache_or_install_path: str = ""
    external_provider_fallbacks: int = 0
    candidate: str = ""
    status: str = ""

    def to_payload(self) -> dict[str, int | str]:
        return {
            "runtime_network_calls": self.runtime_network_calls,
            "automatic_model_downloads": self.automatic_model_downloads,
            "local_cache_or_install_path": self.local_cache_or_install_path,
            "external_provider_fallbacks": self.external_provider_fallbacks,
            "candidate": self.candidate,
            "status": self.status,
        }


@dataclass(frozen=True)
class BenchmarkReport:
    files: int
    units: int
    indexing_seconds: float
    files_per_second: float
    units_per_second: float
    search_latency_ms: dict[str, float]
    collection_name: str
    text_embedding_profile: str
    vision_embedding_profile: str
    text_dimension: int
    vision_dimension: int
    evaluated_queries: int
    recall_at_5: float | None
    recall_at_10: float | None
    mrr_at_10: float | None
    stale_vector_count: int
    duplicate_vector_count: int
    qdrant_disk_bytes: int
    sync: SyncReport
    skipped_queries: int = 0
    recall_at_1: float | None = None
    hit_at_1: float | None = None
    ndcg_at_10: float | None = None
    top1_accuracy: float | None = None
    quality_slices: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    query_results: list[dict[str, Any]] = field(default_factory=list)
