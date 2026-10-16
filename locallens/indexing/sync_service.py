from __future__ import annotations

import shutil
import gc
import time
from pathlib import Path
from typing import Callable

from locallens.core.config import Settings
from locallens.core.types import (
    ExtractionStats,
    IndexedUnit,
    SyncFailure,
    SyncProgress,
    SyncReport,
)
from locallens.embeddings.profiles import with_embedding_profiles
from locallens.embeddings.text_embedder import TextEmbedder
from locallens.embeddings.vision_embedder import VisionEmbedder
from locallens.extractors.pdf_ocr_table_cache import PdfOcrTableReadThroughCache
from locallens.extractors.router import ExtractorRouter
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.ingestion.fingerprint import file_id_for_path
from locallens.ingestion.scanner import Scanner
from locallens.security.redaction import redact_secret_text


class _SyncCancelled(Exception):
    pass


class SyncService:
    def __init__(
        self,
        settings: Settings,
        store: QdrantStore | None = None,
        manifest: ManifestStore | None = None,
        scanner: Scanner | None = None,
    ):
        self.text_embedder = TextEmbedder(settings)
        self.vision_embedder = VisionEmbedder(settings)
        self.settings = with_embedding_profiles(
            settings,
            text_dimension=self.text_embedder.dimension,
            vision_dimension=self.vision_embedder.dimension,
            text_profile=self.text_embedder.profile,
            vision_profile=self.vision_embedder.profile,
        )
        self.settings.ensure_dirs()
        self.store = store or QdrantStore(self.settings)
        self.store.settings = self.settings
        self.manifest = manifest or ManifestStore(self.settings.manifest_path)
        self.scanner = scanner or Scanner(self.settings)
        pdf_ocr_table_cache = PdfOcrTableReadThroughCache(
            self.settings,
            self.manifest,
        )
        self.extractors = ExtractorRouter(
            self.settings,
            pdf_ocr_table_cache=pdf_ocr_table_cache,
        )

    def sync_folder(
        self,
        root_path: str | Path,
        progress_callback: Callable[[SyncProgress], object] | None = None,
    ) -> SyncReport:
        scan_report = self.scanner.scan(root_path)
        report = SyncReport(excluded=len(scan_report.excluded))
        seen_paths = {file.relative_path for file in scan_report.files}
        total = len(scan_report.files)
        if not self._emit_progress(progress_callback, "scan", 0, total, "", report):
            report.cancelled = True
            return report

        root_id = scan_report.root_id

        for index, scanned in enumerate(scan_report.files, start=1):
            if not self._emit_progress(
                progress_callback,
                "indexing",
                index - 1,
                total,
                scanned.relative_path,
                report,
            ):
                report.cancelled = True
                return report
            existing = self.manifest.get_file(
                self.settings.workspace_id, scanned.root_id, scanned.relative_path
            )
            extractor_profile = _file_extractor_profile(self.settings, scanned.file_type)
            if (
                existing
                and existing["content_hash"] == scanned.content_hash
                and existing["mtime_ns"] == scanned.mtime_ns
                and existing["size_bytes"] == scanned.size_bytes
                and existing["text_embedding_profile"]
                == self.settings.text_embedding_profile
                and existing["vision_embedding_profile"]
                == self.settings.vision_embedding_profile
                and existing["extractor_profile"] == extractor_profile
            ):
                report.skipped += 1
                if not self._emit_progress(
                    progress_callback,
                    "skipped",
                    index,
                    total,
                    scanned.relative_path,
                    report,
                ):
                    report.cancelled = True
                    return report
                continue
            if (
                existing
                and existing["content_hash"] == scanned.content_hash
                and existing["extractor_profile"] != extractor_profile
            ):
                self._remove_file_cache_entries(
                    scanned.root_id,
                    scanned.relative_path,
                    report,
                    content_hash=scanned.content_hash,
                    stale=True,
                )

            old_point_ids = set(
                self.manifest.unit_point_ids(
                    self.settings.workspace_id, scanned.root_id, scanned.relative_path
                )
            )
            is_update = bool(old_point_ids)
            point_ids: list[tuple[str, int]] = []
            file_id = file_id_for_path(
                self.settings.workspace_id,
                scanned.root_id,
                scanned.relative_path,
            )
            stats_merged = False

            def merge_extraction_stats_once() -> None:
                nonlocal stats_merged
                if not stats_merged:
                    self._merge_extraction_stats(report, self.extractors.last_stats)
                    stats_merged = True

            def cleanup_cache_on_interrupt() -> None:
                self._discard_staged_file_cache(
                    scanned.root_id, scanned.relative_path, report
                )
                if scanned.file_type == "pdf":
                    self._cleanup_file_cache(file_id)

            try:
                def extraction_progress(phase: str, done: int, step_total: int) -> None:
                    allowed = self._emit_progress(
                        progress_callback,
                        phase,
                        index - 1,
                        total,
                        scanned.relative_path,
                        report,
                        unit_processed=done,
                        unit_total=step_total,
                    )
                    if not allowed:
                        raise _SyncCancelled()

                if not self._emit_progress(
                    progress_callback,
                    "extracting",
                    index - 1,
                    total,
                    scanned.relative_path,
                    report,
                ):
                    cleanup_cache_on_interrupt()
                    report.cancelled = True
                    return report
                if scanned.file_type == "pdf":
                    self._cleanup_file_cache(file_id)
                try:
                    units = self.extractors.extract(
                        scanned,
                        progress_callback=extraction_progress,
                    )
                finally:
                    merge_extraction_stats_once()
                self._index_units(scanned.root_path, units)
                if not self._emit_progress(
                    progress_callback,
                    "embedding",
                    index - 1,
                    total,
                    scanned.relative_path,
                    report,
                ):
                    cleanup_cache_on_interrupt()
                    report.cancelled = True
                    return report
                text_vectors = self._text_vectors(
                    units,
                    progress_callback,
                    index,
                    total,
                    scanned.relative_path,
                    report,
                )
                if text_vectors is None:
                    cleanup_cache_on_interrupt()
                    report.cancelled = True
                    return report
                vision_vectors = self._vision_vectors(
                    scanned.root_path,
                    units,
                    progress_callback,
                    index,
                    total,
                    scanned.relative_path,
                    report,
                )
                if vision_vectors is None:
                    cleanup_cache_on_interrupt()
                    report.cancelled = True
                    return report
                if not self._emit_progress(
                    progress_callback,
                    "upserting",
                    index - 1,
                    total,
                    scanned.relative_path,
                    report,
                ):
                    cleanup_cache_on_interrupt()
                    report.cancelled = True
                    return report
                point_ids = self.store.upsert_units(
                    units, text_vectors=text_vectors, vision_vectors=vision_vectors
                )
                self.manifest.upsert_file(
                    workspace_id=self.settings.workspace_id,
                    root_id=scanned.root_id,
                    relative_path=scanned.relative_path,
                    file_id=file_id,
                    content_hash=scanned.content_hash,
                    mtime_ns=scanned.mtime_ns,
                    size_bytes=scanned.size_bytes,
                    text_embedding_profile=self.settings.text_embedding_profile,
                    vision_embedding_profile=self.settings.vision_embedding_profile,
                    extractor_profile=extractor_profile,
                    point_ids=point_ids,
                )
                stale_point_ids = sorted(
                    old_point_ids - {point_id for _, point_id in point_ids}
                )
                self.store.delete_points(stale_point_ids)
                report.cache_entries_written += self.manifest.commit_staged_cache_entries(
                    self.settings.workspace_id,
                    scanned.root_id,
                    scanned.relative_path,
                    scanned.content_hash,
                )
                if existing and existing["content_hash"] != scanned.content_hash:
                    self._remove_file_cache_entries(
                        scanned.root_id,
                        scanned.relative_path,
                        report,
                        content_hash=str(existing["content_hash"]),
                        stale=True,
                    )
                if is_update:
                    report.updated += 1
                else:
                    report.added += 1
                report.units += len(units)
                if not self._emit_progress(
                    progress_callback,
                    "indexed",
                    index,
                    total,
                    scanned.relative_path,
                    report,
                ):
                    cleanup_cache_on_interrupt()
                    report.cancelled = True
                    return report
            except _SyncCancelled:
                merge_extraction_stats_once()
                cleanup_cache_on_interrupt()
                report.cancelled = True
                return report
            except Exception as exc:
                merge_extraction_stats_once()
                cleanup_cache_on_interrupt()
                self._cleanup_uncommitted_points(point_ids, old_point_ids)
                report.failed += 1
                report.failures.append(
                    _sync_failure(scanned.relative_path, exc, scanned.root_path)
                )
                if not self._emit_progress(
                    progress_callback,
                    "failed",
                    index,
                    total,
                    scanned.relative_path,
                    report,
                ):
                    report.cancelled = True
                    return report

        if root_id:
            stale_paths = (
                self.manifest.known_paths(self.settings.workspace_id, root_id)
                - seen_paths
            )
            for relative_path in stale_paths:
                point_ids = self.manifest.remove_file(
                    self.settings.workspace_id, root_id, relative_path
                )
                self._remove_file_cache_entries(
                    root_id,
                    relative_path,
                    report,
                    stale=True,
                )
                self.store.delete_points(point_ids)
                report.deleted += 1
                if not self._emit_progress(
                    progress_callback,
                    "deleted",
                    total,
                    total,
                    relative_path,
                    report,
                ):
                    report.cancelled = True
                    return report
        self._emit_progress(progress_callback, "complete", total, total, "", report)
        return report

    def purge(self) -> None:
        self.store.purge()
        self.manifest.purge()
        _remove_file(self.settings.manifest_path)
        _remove_file(self.settings.data_dir / "benchmark.json")
        if self.settings.cache_dir.exists():
            _remove_tree(self.settings.cache_dir)
        self.settings.ensure_dirs()

    @staticmethod
    def _index_units(root_path: Path, units: list[IndexedUnit]) -> None:
        for unit in units:
            if not (root_path / unit.relative_path).exists():
                raise FileNotFoundError(unit.relative_path)

    def _text_vectors(
        self,
        units: list[IndexedUnit],
        progress_callback: Callable[[SyncProgress], object] | None,
        file_index: int,
        total_files: int,
        relative_path: str,
        report: SyncReport,
    ) -> dict[str, list[float]] | None:
        result: dict[str, list[float]] = {}
        text_units = [
            unit for unit in units if unit.modality == "text" and unit.text.strip()
        ]
        total_units = len(text_units)
        for unit_index, unit in enumerate(text_units, start=1):
            if not self._emit_progress(
                progress_callback,
                "embedding",
                file_index - 1,
                total_files,
                relative_path,
                report,
                unit_processed=unit_index - 1,
                unit_total=total_units,
                detail=unit.unit_type,
            ):
                return None
            result[unit.unit_id] = self.text_embedder.embed_document(unit.text)
            if not self._emit_progress(
                progress_callback,
                "embedding",
                file_index - 1,
                total_files,
                relative_path,
                report,
                unit_processed=unit_index,
                unit_total=total_units,
                detail=unit.unit_type,
            ):
                return None
        return result

    def _vision_vectors(
        self,
        root_path: Path,
        units: list[IndexedUnit],
        progress_callback: Callable[[SyncProgress], object] | None,
        file_index: int,
        total_files: int,
        relative_path: str,
        report: SyncReport,
    ) -> dict[str, list[float]] | None:
        result: dict[str, list[float]] = {}
        image_units = [unit for unit in units if unit.modality == "image"]
        total_units = len(image_units)
        for unit_index, unit in enumerate(image_units, start=1):
            if not self._emit_progress(
                progress_callback,
                "embedding",
                file_index - 1,
                total_files,
                relative_path,
                report,
                unit_processed=unit_index - 1,
                unit_total=total_units,
                detail=unit.unit_type,
            ):
                return None
            source_path = unit.source_path or root_path / unit.relative_path
            result[unit.unit_id] = self.vision_embedder.embed_file(source_path)
            if not self._emit_progress(
                progress_callback,
                "embedding",
                file_index - 1,
                total_files,
                relative_path,
                report,
                unit_processed=unit_index,
                unit_total=total_units,
                detail=unit.unit_type,
            ):
                return None
        return result

    def _cleanup_file_cache(self, file_id: str) -> None:
        cache_path = self.settings.cache_dir / "pdf_images" / file_id
        if cache_path.exists():
            _remove_tree(cache_path)

    def _discard_staged_file_cache(
        self,
        root_id: str,
        relative_path: str,
        report: SyncReport,
    ) -> None:
        blob_paths = self.manifest.discard_staged_cache_entries(
            self.settings.workspace_id,
            root_id,
            relative_path,
        )
        report.cache_entries_deleted += len(blob_paths)
        self._remove_cache_blobs(blob_paths)

    def _remove_file_cache_entries(
        self,
        root_id: str,
        relative_path: str,
        report: SyncReport,
        content_hash: str | None = None,
        stale: bool = False,
    ) -> None:
        blob_paths = self.manifest.remove_cache_entries_for_file(
            self.settings.workspace_id,
            root_id,
            relative_path,
            content_hash=content_hash,
        )
        if not blob_paths:
            return
        report.cache_entries_deleted += len(blob_paths)
        if stale:
            report.cache_stale_deleted += len(blob_paths)
        self._remove_cache_blobs(blob_paths)

    def _remove_cache_blobs(self, blob_rel_paths: list[str]) -> None:
        for blob_rel_path in blob_rel_paths:
            path = _safe_cache_blob_path(self.settings.cache_dir, blob_rel_path)
            if path is None or not path.exists():
                continue
            if path.is_dir():
                _remove_tree(path)
            else:
                _remove_file(path)

    def _cleanup_uncommitted_points(
        self, point_ids: list[tuple[str, int]], old_point_ids: set[int]
    ) -> None:
        new_point_ids = sorted({point_id for _, point_id in point_ids} - old_point_ids)
        if not new_point_ids:
            return
        try:
            self.store.delete_points(new_point_ids)
        except Exception:
            pass

    @staticmethod
    def _merge_extraction_stats(report: SyncReport, stats: ExtractionStats) -> None:
        report.ocr_attempted += stats.ocr_attempted
        report.ocr_succeeded += stats.ocr_succeeded
        report.ocr_empty += stats.ocr_empty
        report.table_attempted += stats.table_attempted
        report.table_succeeded += stats.table_succeeded
        report.table_empty += stats.table_empty
        report.vlm_attempted += stats.vlm_attempted
        report.vlm_succeeded += stats.vlm_succeeded
        report.vlm_empty += stats.vlm_empty
        report.vlm_failed += stats.vlm_failed
        report.cache_result_hits += stats.cache_result_hits
        report.cache_result_misses += stats.cache_result_misses
        report.cache_corrupt_skipped += stats.cache_corrupt_skipped

    @staticmethod
    def _emit_progress(
        progress_callback: Callable[[SyncProgress], object] | None,
        phase: str,
        processed: int,
        total: int,
        relative_path: str,
        report: SyncReport,
        unit_processed: int = 0,
        unit_total: int = 0,
        detail: str = "",
    ) -> bool:
        if progress_callback is None:
            return True
        try:
            result = progress_callback(
                SyncProgress(
                    phase=phase,
                    processed=processed,
                    total=total,
                    relative_path=relative_path,
                    added=report.added,
                    updated=report.updated,
                    deleted=report.deleted,
                    skipped=report.skipped,
                    excluded=report.excluded,
                    failed=report.failed,
                    unit_processed=unit_processed,
                    unit_total=unit_total,
                    detail=detail,
                )
            )
            return result is not False
        except Exception:
            return True


def _file_extractor_profile(settings: Settings, file_type: str) -> str:
    if file_type == "pdf":
        profiles = []
        if settings.pdf_visual_mode != "off":
            profiles.append(f"pdf-visual:{settings.pdf_visual_mode}")
        if settings.pdf_ocr_mode != "off":
            ocr_profile = f"pdf-ocr:{settings.pdf_ocr_mode}:{settings.pdf_ocr_lang}"
            if settings.tesseract_psm:
                ocr_profile = f"{ocr_profile}:psm{settings.tesseract_psm}"
            profiles.append(ocr_profile)
        if settings.pdf_table_mode != "off":
            profiles.append(f"pdf-table:{settings.pdf_table_mode}")
        if settings.pdf_vlm_mode != "off":
            candidate = settings.pdf_vlm_model_name or "unconfigured"
            profiles.append(
                "pdf-vlm:"
                f"{settings.pdf_vlm_mode}:"
                f"{candidate}:"
                f"{settings.pdf_vlm_prompt_version}"
            )
        return "|".join(profiles)
    return ""


def _remove_tree(path: Path) -> None:
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            gc.collect()
            if attempt == 4:
                raise
            time.sleep(0.1 * (attempt + 1))


def _remove_file(path: Path) -> None:
    for attempt in range(5):
        try:
            if path.exists():
                path.unlink()
            return
        except PermissionError:
            gc.collect()
            if attempt == 4:
                raise
            time.sleep(0.1 * (attempt + 1))


def _safe_cache_blob_path(cache_dir: Path, blob_rel_path: str) -> Path | None:
    root = cache_dir.resolve()
    candidate = (cache_dir / blob_rel_path).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


def _sync_failure(relative_path: str, exc: Exception, root_path: Path) -> SyncFailure:
    message = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    message = redact_secret_text(message)
    root_text = str(root_path)
    if root_text:
        message = message.replace(root_text, "<root>")
        message = message.replace(root_text.replace("\\", "/"), "<root>")
    return SyncFailure(
        relative_path=relative_path,
        error_type=exc.__class__.__name__,
        message=message[:200],
    )
