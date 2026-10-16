from __future__ import annotations

import os
import sqlite3
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import locallens.extractors.pdf_extractor as pdf_module
from locallens.core.config import Settings
from locallens.core.types import ExtractionStats, IndexedUnit, ScannedFile
from locallens.extractors.pdf_extractor import PdfExtractor
from locallens.extractors.pdf_ocr_table_cache import PdfOcrTableReadThroughCache
from locallens.ingestion.fingerprint import file_id_for_path, unit_id_for_parts
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.ingestion.scanner import Scanner
from locallens.retrieval.search_service import SearchService


fitz = pytest.importorskip("fitz")
Image = pytest.importorskip("PIL.Image")
pytest.importorskip("qdrant_client")


def test_pdf_local_ocr_creates_text_units_without_visual_units(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "scanned.pdf")
    settings = Settings(data_dir=tmp_path / "data", pdf_ocr_mode="local-ocr")
    scanned = Scanner(settings).scan(source).files[0]

    def fake_run(*args, **kwargs):
        assert args[0][0] == "tesseract"
        assert "-l" in args[0]
        return SimpleNamespace(returncode=0, stdout="invoice total approved\n")

    monkeypatch.setattr(pdf_module.subprocess, "run", fake_run)

    extractor = PdfExtractor(settings)
    units = extractor.extract(scanned)
    ocr_units = [unit for unit in units if unit.unit_type == "pdf_ocr_text"]

    assert len(ocr_units) == 1
    assert extractor.last_stats.ocr_attempted == 1
    assert extractor.last_stats.ocr_succeeded == 1
    assert extractor.last_stats.ocr_empty == 0
    assert {unit.unit_type for unit in units}.isdisjoint({"pdf_region", "pdf_image"})
    assert ocr_units[0].modality == "text"
    assert ocr_units[0].page_no == 1
    assert ocr_units[0].image_no == 0
    assert ocr_units[0].bbox is not None
    assert ocr_units[0].source_kind == "pdf"
    assert ocr_units[0].extractor_profile == "tesseract-local-ocr-v1:eng"
    assert "invoice total" in ocr_units[0].text


def test_pdf_local_ocr_passes_tessdata_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "scanned.pdf")
    tessdata = tmp_path / "tessdata"
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_ocr_mode="local-ocr",
        pdf_ocr_lang="kor",
        tessdata_dir=str(tessdata),
        tesseract_psm="6",
    )
    scanned = Scanner(settings).scan(source).files[0]
    commands = []

    def fake_run(*args, **kwargs):
        commands.append(args[0])
        return SimpleNamespace(returncode=0, stdout="로컬 검색 승인\n")

    monkeypatch.setattr(pdf_module.subprocess, "run", fake_run)

    units = PdfExtractor(settings).extract(scanned)

    assert [unit.unit_type for unit in units].count("pdf_ocr_text") == 1
    assert commands[0][-4:] == ["--tessdata-dir", str(tessdata), "--psm", "6"]
    assert commands[0][commands[0].index("-l") + 1] == "kor"
    ocr_unit = [unit for unit in units if unit.unit_type == "pdf_ocr_text"][0]
    assert ocr_unit.extractor_profile == "tesseract-local-ocr-v1:kor:psm6"


def test_pdf_local_ocr_missing_binary_skips_units(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "scanned.pdf")
    settings = Settings(data_dir=tmp_path / "data", pdf_ocr_mode="local-ocr")
    scanned = Scanner(settings).scan(source).files[0]

    def missing_binary(*args, **kwargs):
        raise FileNotFoundError("tesseract")

    monkeypatch.setattr(pdf_module.subprocess, "run", missing_binary)

    extractor = PdfExtractor(settings)
    units = extractor.extract(scanned)

    assert [unit for unit in units if unit.unit_type == "pdf_ocr_text"] == []
    assert extractor.last_stats.ocr_attempted == 1
    assert extractor.last_stats.ocr_succeeded == 0
    assert extractor.last_stats.ocr_empty == 1


def test_pdf_local_table_creates_table_units(tmp_path: Path):
    pytest.importorskip("pdfplumber")
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_table(source / "table.pdf")
    settings = Settings(data_dir=tmp_path / "data", pdf_table_mode="local-table")
    scanned = Scanner(settings).scan(source).files[0]

    extractor = PdfExtractor(settings)
    units = extractor.extract(scanned)
    table_units = [unit for unit in units if unit.unit_type == "pdf_table"]

    assert len(table_units) == 1
    assert extractor.last_stats.table_attempted == 1
    assert extractor.last_stats.table_succeeded == 1
    assert extractor.last_stats.table_empty == 0
    table = table_units[0]
    assert table.modality == "text"
    assert table.page_no == 1
    assert table.table_no == 0
    assert table.bbox is not None
    assert table.source_kind == "pdf"
    assert table.extractor_profile == "pdfplumber-local-table-v1"
    assert "Context:" in table.text
    assert "Owner | Status | Total" in table.text
    assert "Kim | Done | 120" in table.text


def test_pdf_table_cache_is_default_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_table(source / "table.pdf")
    monkeypatch.setattr(pdf_module, "_pdf_table_units", _fake_pdf_table_units)
    settings = Settings(data_dir=tmp_path / "data", pdf_table_mode="local-table")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)

    report = SyncService(settings, store=store, manifest=manifest).sync_folder(source)

    assert report.added == 1
    assert report.table_attempted == 1
    assert report.cache_result_hits == 0
    assert report.cache_result_misses == 0
    assert report.cache_entries_written == 0
    assert manifest.cache_entry_count() == 0


def test_pdf_table_readthrough_cache_hits_committed_units_on_reindex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "table.pdf"
    _write_pdf_with_table(target)
    monkeypatch.setattr(pdf_module, "_pdf_table_units", _fake_pdf_table_units)
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_table_mode="local-table",
        pdf_ocr_table_cache_mode="read-through",
    )
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    first = sync.sync_folder(source)
    _touch_without_content_change(target)
    second = sync.sync_folder(source)
    table_payloads = [
        record["payload"]
        for record in store.payload_records()
        if record["payload"].get("unit_type") == "pdf_table"
    ]

    assert first.added == 1
    assert first.table_attempted == 1
    assert first.table_succeeded == 1
    assert first.cache_result_misses == 1
    assert first.cache_result_hits == 0
    assert first.cache_entries_written == 1
    assert second.updated == 1
    assert second.table_attempted == 0
    assert second.table_succeeded == 0
    assert second.cache_result_hits == 1
    assert second.cache_result_misses == 0
    assert second.cache_entries_deleted == 0
    assert manifest.cache_entry_count(state="committed") == 1
    assert table_payloads
    assert table_payloads[0]["unit_type"] == "pdf_table"
    assert table_payloads[0]["has_text_vector"] is True


def test_pdf_ocr_readthrough_cache_hits_committed_units_on_reindex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "scanned.pdf"
    _write_pdf_with_image(target)
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_ocr_mode="local-ocr",
        pdf_ocr_table_cache_mode="read-through",
    )
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)
    ocr_calls = []

    def fake_run(*args, **kwargs):
        ocr_calls.append(args)
        return SimpleNamespace(returncode=0, stdout="invoice total approved\n")

    monkeypatch.setattr(pdf_module.subprocess, "run", fake_run)

    first = sync.sync_folder(source)
    _touch_without_content_change(target)
    second = sync.sync_folder(source)
    ocr_payloads = [
        record["payload"]
        for record in store.payload_records()
        if record["payload"].get("unit_type") == "pdf_ocr_text"
    ]

    assert first.added == 1
    assert first.ocr_attempted == 1
    assert first.ocr_succeeded == 1
    assert first.cache_result_misses == 1
    assert first.cache_entries_written == 1
    assert second.updated == 1
    assert second.ocr_attempted == 0
    assert second.ocr_succeeded == 0
    assert second.cache_result_hits == 1
    assert second.cache_result_misses == 0
    assert len(ocr_calls) == 1
    assert manifest.cache_entry_count(state="committed") == 1
    assert ocr_payloads
    assert ocr_payloads[0]["unit_type"] == "pdf_ocr_text"
    assert ocr_payloads[0]["has_text_vector"] is True


def test_pdf_table_cache_blob_removal_does_not_change_search_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "table.pdf"
    _write_pdf_with_table(target)
    monkeypatch.setattr(pdf_module, "_pdf_table_units", _fake_pdf_table_units)
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_table_mode="local-table",
        pdf_ocr_table_cache_mode="read-through",
    )
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    first = sync.sync_folder(source)
    baseline = _search_signature(settings, store, manifest, "Owner Status Total")
    payloads = _search_payloads(settings, store, manifest, "Owner Status Total")
    blob = _first_cache_blob(settings, manifest)
    blob.unlink()
    after = _search_signature(settings, store, manifest, "Owner Status Total")

    assert first.cache_entries_written == 1
    assert baseline
    assert all(
        not any(str(key).startswith("cache") for key in payload)
        for payload in payloads
    )
    assert after == baseline


def test_pdf_table_cache_cannot_recover_removed_index_or_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "table.pdf"
    _write_pdf_with_table(target)
    monkeypatch.setattr(pdf_module, "_pdf_table_units", _fake_pdf_table_units)
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_table_mode="local-table",
        pdf_ocr_table_cache_mode="read-through",
    )
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    first = sync.sync_folder(source)
    before = _search_signature(settings, store, manifest, "Owner Status Total")
    assert _first_cache_blob(settings, manifest).exists()
    workspace_id, root_id, relative_path = _first_manifest_file(manifest)
    point_ids = manifest.unit_point_ids(workspace_id, root_id, relative_path)
    store.delete_points(point_ids)
    manifest.remove_file(workspace_id, root_id, relative_path)
    after = _search_signature(settings, store, manifest, "Owner Status Total")

    assert first.cache_entries_written == 1
    assert before
    assert after == []


def test_pdf_table_readthrough_corrupt_blob_falls_back_to_cold_extract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "table.pdf"
    _write_pdf_with_table(target)
    monkeypatch.setattr(pdf_module, "_pdf_table_units", _fake_pdf_table_units)
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_table_mode="local-table",
        pdf_ocr_table_cache_mode="read-through",
    )
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    first = sync.sync_folder(source)
    blob = _first_cache_blob(settings, manifest)
    blob.write_text("{\"corrupt\": true}\n", encoding="utf-8")
    _touch_without_content_change(target)
    second = sync.sync_folder(source)

    assert first.cache_entries_written == 1
    assert second.updated == 1
    assert second.cache_result_hits == 0
    assert second.cache_result_misses == 1
    assert second.cache_corrupt_skipped == 1
    assert second.table_attempted == 1
    assert second.table_succeeded == 1
    assert second.cache_entries_written == 1
    assert manifest.cache_entry_count(state="committed") == 1


def test_pdf_table_readthrough_stale_content_does_not_hit_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "table.pdf"
    _write_pdf_with_table(target)
    monkeypatch.setattr(pdf_module, "_pdf_table_units", _fake_pdf_table_units)
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_table_mode="local-table",
        pdf_ocr_table_cache_mode="read-through",
    )
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    first = sync.sync_folder(source)
    original = target.read_bytes()
    target.write_bytes(original + b"\n% stale safety probe\n")
    second = sync.sync_folder(source)

    assert first.cache_entries_written == 1
    assert second.cache_result_hits == 0
    assert second.cache_result_misses == 1
    assert second.cache_stale_deleted == 1
    assert second.table_attempted == 1
    assert second.table_succeeded == 1
    assert manifest.cache_entry_count(state="committed") == 1


def test_pdf_table_readthrough_rejects_foreign_blob_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "table.pdf"
    _write_pdf_with_table(target)
    monkeypatch.setattr(pdf_module, "_pdf_table_units", _fake_pdf_table_units)
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_table_mode="local-table",
        pdf_ocr_table_cache_mode="read-through",
    )
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    first = sync.sync_folder(source)
    with sqlite3.connect(manifest.path) as conn:
        conn.execute("UPDATE cache_entries SET blob_rel_path='../foreign.json'")
    _touch_without_content_change(target)
    second = sync.sync_folder(source)

    assert first.cache_entries_written == 1
    assert second.cache_result_hits == 0
    assert second.cache_result_misses == 1
    assert second.cache_corrupt_skipped == 1
    assert second.table_attempted == 1
    assert second.table_succeeded == 1


def test_pdf_ocr_table_cache_key_uses_extractor_profile_not_embedding_profile(
    tmp_path: Path,
):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_table(source / "table.pdf")
    base = Settings(
        data_dir=tmp_path / "data",
        pdf_table_mode="local-table",
        pdf_ocr_table_cache_mode="read-through",
        text_embedding_profile="hash:64",
        vision_embedding_profile="hash:64",
    )
    changed_embedding = Settings(
        data_dir=tmp_path / "data",
        pdf_table_mode="local-table",
        pdf_ocr_table_cache_mode="read-through",
        text_embedding_profile="hash:128",
        vision_embedding_profile="hash:128",
    )
    changed_ocr_runtime = Settings(
        data_dir=tmp_path / "data",
        pdf_ocr_mode="local-ocr",
        pdf_table_mode="local-table",
        pdf_ocr_table_cache_mode="read-through",
        tesseract_psm="7",
    )
    scanned = Scanner(base).scan(source).files[0]
    file_id = file_id_for_path(base.workspace_id, scanned.root_id, scanned.relative_path)

    assert (
        PdfOcrTableReadThroughCache(
            base,
            ManifestStore(base.manifest_path),
        ).cache_key(scanned, file_id)
        == PdfOcrTableReadThroughCache(
            changed_embedding,
            ManifestStore(changed_embedding.manifest_path),
        ).cache_key(scanned, file_id)
    )
    assert (
        PdfOcrTableReadThroughCache(
            base,
            ManifestStore(base.manifest_path),
        ).cache_key(scanned, file_id)
        != PdfOcrTableReadThroughCache(
            changed_ocr_runtime,
            ManifestStore(changed_ocr_runtime.manifest_path),
        ).cache_key(scanned, file_id)
    )


def test_sync_can_cancel_during_pdf_ocr_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "scanned.pdf")
    settings = Settings(data_dir=tmp_path / "data", pdf_ocr_mode="local-ocr")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    events = []
    ocr_calls = []

    def fake_run(*args, **kwargs):
        ocr_calls.append(args)
        return SimpleNamespace(returncode=0, stdout="invoice total approved\n")

    def cancel_on_ocr(progress):
        events.append((progress.phase, progress.unit_processed, progress.unit_total))
        return progress.phase != "ocr"

    monkeypatch.setattr(pdf_module.subprocess, "run", fake_run)

    report = SyncService(settings, store=store, manifest=manifest).sync_folder(
        source,
        progress_callback=cancel_on_ocr,
    )

    assert report.cancelled is True
    assert report.failed == 0
    assert report.added == 0
    assert store.count() == 0
    assert any(phase == "ocr" and total == 1 for phase, _, total in events)
    assert ocr_calls == []


def test_pdf_table_mode_change_forces_reindex_and_stale_removal(tmp_path: Path):
    pytest.importorskip("pdfplumber")
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_table(source / "table.pdf")
    base_settings = Settings(data_dir=tmp_path / "data")
    table_settings = Settings(data_dir=tmp_path / "data", pdf_table_mode="local-table")
    store = QdrantStore(base_settings, in_memory=True)
    manifest = ManifestStore(base_settings.manifest_path)

    first = SyncService(base_settings, store=store, manifest=manifest).sync_folder(source)
    second = SyncService(table_settings, store=store, manifest=manifest).sync_folder(source)
    table_payloads = [
        record["payload"]
        for record in store.payload_records()
        if record["payload"].get("unit_type") == "pdf_table"
    ]
    third = SyncService(base_settings, store=store, manifest=manifest).sync_folder(source)
    remaining_table_payloads = [
        record["payload"]
        for record in store.payload_records()
        if record["payload"].get("unit_type") == "pdf_table"
    ]

    assert first.added == 1
    assert second.updated == 1
    assert second.table_attempted == 1
    assert second.table_succeeded == 1
    assert second.table_empty == 0
    assert table_payloads
    assert table_payloads[0]["has_text_vector"] is True
    assert table_payloads[0]["table_no"] == 0
    assert table_payloads[0]["source_kind"] == "pdf"
    assert table_payloads[0]["extractor_profile"] == "pdfplumber-local-table-v1"
    assert third.updated == 1
    assert remaining_table_payloads == []


def _write_pdf_with_image(path: Path) -> None:
    image_bytes = _png_bytes()
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_text((36, 36), "Local OCR image page")
    page.insert_image(fitz.Rect(72, 72, 168, 168), stream=image_bytes)
    doc.save(str(path))
    doc.close()


def _write_pdf_with_table(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=360, height=240)
    x_points = [36, 144, 252, 324]
    y_points = [48, 84, 120, 156]
    for x_point in x_points:
        page.draw_line((x_point, y_points[0]), (x_point, y_points[-1]))
    for y_point in y_points:
        page.draw_line((x_points[0], y_point), (x_points[-1], y_point))
    cells = [
        ["Owner", "Status", "Total"],
        ["Kim", "Done", "120"],
        ["Lee", "Open", "90"],
    ]
    for row_index, row in enumerate(cells):
        for column_index, value in enumerate(row):
            page.insert_text(
                (x_points[column_index] + 10, y_points[row_index] + 23),
                value,
                fontsize=10,
            )
    doc.save(str(path))
    doc.close()


def _touch_without_content_change(path: Path) -> None:
    now_ns = time.time_ns() + 1_000_000_000
    os.utime(path, ns=(now_ns, now_ns))


def _first_cache_blob(settings: Settings, manifest: ManifestStore) -> Path:
    with sqlite3.connect(manifest.path) as conn:
        row = conn.execute("SELECT blob_rel_path FROM cache_entries LIMIT 1").fetchone()
    assert row is not None
    return settings.cache_dir / str(row[0])


def _first_manifest_file(manifest: ManifestStore) -> tuple[str, str, str]:
    with sqlite3.connect(manifest.path) as conn:
        row = conn.execute(
            "SELECT workspace_id, root_id, relative_path FROM files LIMIT 1"
        ).fetchone()
    assert row is not None
    return str(row[0]), str(row[1]), str(row[2])


def _search_signature(
    settings: Settings,
    store: QdrantStore,
    manifest: ManifestStore,
    query: str,
) -> list[tuple[str, str, int | None, int | None]]:
    results = SearchService(settings, store=store, manifest=manifest).search(
        query,
        top_k=5,
        modality="text",
    )
    return [
        (
            item.relative_path,
            item.unit_type,
            item.page_no,
            item.payload.get("table_no"),
        )
        for item in results
    ]


def _search_payloads(
    settings: Settings,
    store: QdrantStore,
    manifest: ManifestStore,
    query: str,
) -> list[dict]:
    return [
        item.payload
        for item in SearchService(
            settings,
            store=store,
            manifest=manifest,
        ).search(query, top_k=5, modality="text")
    ]


def _fake_pdf_table_units(
    settings: Settings,
    scanned: ScannedFile,
    path: Path,
    file_id: str,
    version_parts: tuple[str, str, str, str],
    stats: ExtractionStats,
    progress_callback,
) -> list[IndexedUnit]:
    stats.table_attempted += 1
    stats.table_succeeded += 1
    text = (
        "PDF table page 1 table 0\n"
        "Rows: 3 Columns: 3\n"
        "Owner | Status | Total\n"
        "Kim | Done | 120\n"
        "Lee | Open | 90"
    )
    return [
        IndexedUnit(
            workspace_id=settings.workspace_id,
            root_id=scanned.root_id,
            file_id=file_id,
            unit_id=unit_id_for_parts(*version_parts, "pdf_table", 1, 0),
            unit_type="pdf_table",
            relative_path=scanned.relative_path,
            mime_type=scanned.mime_type,
            ext=scanned.ext,
            size_bytes=scanned.size_bytes,
            mtime_ns=scanned.mtime_ns,
            content_hash=scanned.content_hash,
            modality="text",
            text=text,
            text_preview="PDF table page 1 table 0",
            page_no=1,
            table_no=0,
            bbox=(36.0, 48.0, 324.0, 156.0),
            source_kind="pdf",
            extractor_profile="pdfplumber-local-table-v1",
        )
    ]


def _png_bytes() -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", (80, 80), color=(230, 230, 230))
    image.save(buffer, format="PNG")
    return buffer.getvalue()
