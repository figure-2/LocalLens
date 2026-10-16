from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from locallens.core.config import Settings
from locallens.extractors.pdf_extractor import PdfExtractor
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.ingestion.scanner import Scanner


fitz = pytest.importorskip("fitz")
Image = pytest.importorskip("PIL.Image")
pytest.importorskip("qdrant_client")


def test_pdf_visual_mode_off_keeps_default_pdf_units(tmp_path: Path):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "visual.pdf")
    settings = Settings(data_dir=tmp_path / "data")
    scanned = Scanner(settings).scan(source).files[0]

    units = PdfExtractor(settings).extract(scanned)

    assert units
    assert {unit.unit_type for unit in units}.isdisjoint({"pdf_image", "pdf_region"})


def test_pdf_local_layout_creates_region_units_with_cached_sources(tmp_path: Path):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "visual.pdf")
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_visual_mode="local-layout",
    )
    scanned = Scanner(settings).scan(source).files[0]

    units = PdfExtractor(settings).extract(scanned)
    regions = [unit for unit in units if unit.unit_type == "pdf_region"]

    assert len(regions) == 1
    region = regions[0]
    assert region.modality == "image"
    assert region.page_no == 1
    assert region.image_no == 0
    assert region.bbox is not None
    assert region.source_kind == "pdf"
    assert region.extractor_profile == "pymupdf-local-layout-v1"
    assert region.source_path is not None
    assert region.source_path.exists()
    assert settings.cache_dir in region.source_path.parents


def test_pdf_visual_mode_change_forces_reindex_and_stale_removal(tmp_path: Path):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "visual.pdf")
    base_settings = Settings(data_dir=tmp_path / "data")
    visual_settings = Settings(
        data_dir=tmp_path / "data",
        pdf_visual_mode="local-layout",
    )
    store = QdrantStore(base_settings, in_memory=True)
    manifest = ManifestStore(base_settings.manifest_path)

    first = SyncService(base_settings, store=store, manifest=manifest).sync_folder(source)
    second = SyncService(visual_settings, store=store, manifest=manifest).sync_folder(source)
    visual_payloads = [
        record["payload"]
        for record in store.payload_records()
        if record["payload"].get("unit_type") == "pdf_region"
    ]
    third = SyncService(base_settings, store=store, manifest=manifest).sync_folder(source)
    remaining_visual_payloads = [
        record["payload"]
        for record in store.payload_records()
        if record["payload"].get("unit_type") == "pdf_region"
    ]

    assert first.added == 1
    assert second.updated == 1
    assert visual_payloads
    assert visual_payloads[0]["has_vision_vector"] is True
    assert visual_payloads[0]["bbox"]
    assert visual_payloads[0]["source_kind"] == "pdf"
    assert visual_payloads[0]["extractor_profile"] == "pymupdf-local-layout-v1"
    assert third.updated == 1
    assert remaining_visual_payloads == []


def _write_pdf_with_image(path: Path) -> None:
    image_bytes = _png_bytes()
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_text((36, 36), "Local PDF visual evidence page")
    page.insert_image(fitz.Rect(72, 72, 168, 168), stream=image_bytes)
    doc.save(str(path))
    doc.close()


def _png_bytes() -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", (80, 80), color=(80, 140, 220))
    image.save(buffer, format="PNG")
    return buffer.getvalue()
