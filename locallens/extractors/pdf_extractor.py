from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from locallens.core.config import Settings
from locallens.core.types import ExtractionStats, IndexedUnit, ScannedFile
from locallens.extractors.chunking import chunk_text, preview
from locallens.extractors.pdf_ocr_table_cache import PdfOcrTableReadThroughCache
from locallens.extractors.pdf_vlm_adapter import build_local_vlm_captioner
from locallens.ingestion.fingerprint import file_id_for_path, unit_id_for_parts
from locallens.security.redaction import redact_secret_text


class PdfExtractor:
    def __init__(
        self,
        settings: Settings,
        ocr_table_cache: PdfOcrTableReadThroughCache | None = None,
    ):
        self.settings = settings
        self.ocr_table_cache = ocr_table_cache
        self.last_stats = ExtractionStats()

    def extract(
        self,
        scanned: ScannedFile,
        progress_callback: Callable[[str, int, int], object] | None = None,
    ) -> list[IndexedUnit]:
        import fitz

        self.last_stats = ExtractionStats()
        _validate_pdf_modes(self.settings)
        path = scanned.root_path / scanned.relative_path
        file_id = file_id_for_path(
            self.settings.workspace_id, scanned.root_id, scanned.relative_path
        )
        version_parts = (
            file_id,
            scanned.content_hash,
            self.settings.text_embedding_profile,
            self.settings.vision_embedding_profile,
        )
        cached_optional_units: list[IndexedUnit] = []
        optional_cache_hit = False
        if self.ocr_table_cache is not None:
            cache_read = self.ocr_table_cache.read(scanned, file_id, version_parts)
            if cache_read.status == "hit":
                self.last_stats.cache_result_hits += 1
                optional_cache_hit = True
                cached_optional_units = cache_read.units
            elif cache_read.status == "miss":
                self.last_stats.cache_result_misses += 1
            elif cache_read.status == "corrupt":
                self.last_stats.cache_result_misses += 1
                self.last_stats.cache_corrupt_skipped += 1
        units: list[IndexedUnit] = []
        document_text_parts: list[str] = []
        with fitz.open(path) as doc:
            for page_index, page in enumerate(doc):
                page_no = page_index + 1
                text = redact_secret_text(page.get_text() or "")
                if text.strip():
                    document_text_parts.append(text)
                    page_id = unit_id_for_parts(*version_parts, "page", page_no)
                    units.append(
                        _unit(
                            self.settings.workspace_id,
                            scanned,
                            file_id,
                            page_id,
                            "page",
                            "text",
                            text,
                            page_no,
                            None,
                        )
                    )
                    for chunk_index, chunk in enumerate(
                        chunk_text(
                            text,
                            self.settings.chunk_size,
                            self.settings.chunk_overlap,
                        )
                    ):
                        chunk_id = unit_id_for_parts(
                            *version_parts, "chunk", page_no, chunk_index
                        )
                        units.append(
                            _unit(
                                self.settings.workspace_id,
                                scanned,
                                file_id,
                                chunk_id,
                                "chunk",
                                "text",
                                chunk,
                                page_no,
                                chunk_index,
                            )
                        )
                needs_visual_units = (
                    self.settings.pdf_visual_mode == "local-layout"
                    or (
                        self.settings.pdf_ocr_mode == "local-ocr"
                        and not optional_cache_hit
                    )
                    or self.settings.pdf_vlm_mode
                    in {"local-vlm", "mock-vlm", "clova-studio"}
                )
                if needs_visual_units:
                    visual_units = _pdf_visual_units(
                        self.settings,
                        scanned,
                        doc,
                        page,
                        file_id,
                        version_parts,
                        page_no,
                    )
                else:
                    visual_units = []
                if self.settings.pdf_visual_mode == "local-layout":
                    units.extend(visual_units)
                if self.settings.pdf_ocr_mode == "local-ocr" and not optional_cache_hit:
                    self.last_stats.ocr_attempted += len(
                        [unit for unit in visual_units if unit.source_path is not None]
                    )
                    units.extend(
                        _pdf_ocr_units(
                            self.settings,
                            scanned,
                            file_id,
                            version_parts,
                            visual_units,
                            self.last_stats,
                            progress_callback,
                        )
                    )
                if self.settings.pdf_vlm_mode in {
                    "local-vlm",
                    "mock-vlm",
                    "clova-studio",
                }:
                    units.extend(
                        _pdf_visual_caption_units(
                            self.settings,
                            scanned,
                            file_id,
                            version_parts,
                            visual_units,
                            self.last_stats,
                            progress_callback,
                        )
                    )
        document_text = "\n\n".join(document_text_parts)
        if document_text:
            units.insert(
                0,
                _unit(
                    self.settings.workspace_id,
                    scanned,
                    file_id,
                    unit_id_for_parts(*version_parts, "document"),
                    "document",
                    "text",
                    document_text,
                    None,
                    None,
                ),
            )
        if self.settings.pdf_table_mode == "local-table" and not optional_cache_hit:
            units.extend(
                _pdf_table_units(
                    self.settings,
                    scanned,
                    path,
                    file_id,
                    version_parts,
                    self.last_stats,
                    progress_callback,
                )
            )
        if optional_cache_hit:
            units.extend(cached_optional_units)
        elif self.ocr_table_cache is not None:
            self.ocr_table_cache.stage(scanned, file_id, units)
        return units


def _validate_pdf_modes(settings: Settings) -> None:
    if settings.pdf_visual_mode not in {"off", "local-layout"}:
        raise ValueError("Unsupported PDF visual mode. Use off or local-layout.")
    if settings.pdf_ocr_mode not in {"off", "local-ocr"}:
        raise ValueError("Unsupported PDF OCR mode. Use off or local-ocr.")
    if settings.pdf_table_mode not in {"off", "local-table"}:
        raise ValueError("Unsupported PDF table mode. Use off or local-table.")
    if settings.pdf_ocr_table_cache_mode not in {"off", "read-through"}:
        raise ValueError("Unsupported PDF OCR/table cache mode. Use off or read-through.")
    if settings.pdf_vlm_mode not in {"off", "local-vlm", "mock-vlm", "clova-studio"}:
        raise ValueError(
            "Unsupported PDF VLM mode. Use off, local-vlm, mock-vlm, or clova-studio."
        )


def _unit(
    workspace_id: str,
    scanned: ScannedFile,
    file_id: str,
    unit_id: str,
    unit_type: str,
    modality: str,
    text: str,
    page_no: int | None,
    chunk_no: int | None,
) -> IndexedUnit:
    return IndexedUnit(
        workspace_id=workspace_id,
        root_id=scanned.root_id,
        file_id=file_id,
        unit_id=unit_id,
        unit_type=unit_type,
        relative_path=scanned.relative_path,
        mime_type=scanned.mime_type,
        ext=scanned.ext,
        size_bytes=scanned.size_bytes,
        mtime_ns=scanned.mtime_ns,
        content_hash=scanned.content_hash,
        modality=modality,
        text=text,
        text_preview=preview(text),
        page_no=page_no,
        chunk_no=chunk_no,
    )


def _pdf_visual_units(
    settings: Settings,
    scanned: ScannedFile,
    doc,
    page,
    file_id: str,
    version_parts: tuple[str, str, str, str],
    page_no: int,
) -> list[IndexedUnit]:
    units: list[IndexedUnit] = []
    for image_index, image in enumerate(page.get_images(full=True)):
        xref = int(image[0])
        rects = _image_rects(page, xref)
        if not rects:
            rects = [None]
        for rect_index, rect in enumerate(rects):
            occurrence_no = (
                image_index if len(rects) == 1 else image_index * 1000 + rect_index
            )
            source_path = _write_pdf_visual_source(
                settings,
                doc,
                page,
                xref,
                file_id,
                scanned,
                page_no,
                image_index,
                rect_index,
                rect,
            )
            text = (
                f"PDF visual page {page_no} image {occurrence_no} "
                f"in {scanned.relative_path}"
            )
            unit_type = "pdf_region" if rect is not None else "pdf_image"
            units.append(
                IndexedUnit(
                    workspace_id=settings.workspace_id,
                    root_id=scanned.root_id,
                    file_id=file_id,
                    unit_id=unit_id_for_parts(
                        *version_parts, unit_type, page_no, occurrence_no
                    ),
                    unit_type=unit_type,
                    relative_path=scanned.relative_path,
                    mime_type=scanned.mime_type,
                    ext=scanned.ext,
                    size_bytes=scanned.size_bytes,
                    mtime_ns=scanned.mtime_ns,
                    content_hash=scanned.content_hash,
                    modality="image",
                    text=text,
                    text_preview=preview(text),
                    page_no=page_no,
                    image_no=occurrence_no,
                    bbox=_rect_tuple(rect),
                    source_kind="pdf",
                    extractor_profile="pymupdf-local-layout-v1",
                    source_path=source_path,
                )
            )
    return units


def _pdf_ocr_units(
    settings: Settings,
    scanned: ScannedFile,
    file_id: str,
    version_parts: tuple[str, str, str, str],
    visual_units: list[IndexedUnit],
    stats: ExtractionStats,
    progress_callback: Callable[[str, int, int], object] | None,
) -> list[IndexedUnit]:
    units: list[IndexedUnit] = []
    candidates = [unit for unit in visual_units if unit.source_path is not None]
    total = len(candidates)
    for index, visual in enumerate(candidates, start=1):
        if visual.source_path is None:
            continue
        _emit_optional_progress(progress_callback, "ocr", index - 1, total)
        text = redact_secret_text(
            _run_tesseract(
                settings.tesseract_cmd,
                visual.source_path,
                settings.pdf_ocr_lang,
                settings.tessdata_dir,
                settings.tesseract_psm,
            )
        )
        if not text.strip():
            stats.ocr_empty += 1
            _emit_optional_progress(progress_callback, "ocr", index, total)
            continue
        stats.ocr_succeeded += 1
        units.append(
            IndexedUnit(
                workspace_id=settings.workspace_id,
                root_id=scanned.root_id,
                file_id=file_id,
                unit_id=unit_id_for_parts(
                    *version_parts,
                    "pdf_ocr_text",
                    visual.page_no or 0,
                    visual.image_no or 0,
                    settings.pdf_ocr_lang,
                ),
                unit_type="pdf_ocr_text",
                relative_path=scanned.relative_path,
                mime_type=scanned.mime_type,
                ext=scanned.ext,
                size_bytes=scanned.size_bytes,
                mtime_ns=scanned.mtime_ns,
                content_hash=scanned.content_hash,
                modality="text",
                text=text,
                text_preview=preview(text),
                page_no=visual.page_no,
                image_no=visual.image_no,
                bbox=visual.bbox,
                source_kind="pdf",
                extractor_profile=_ocr_extractor_profile(settings),
            )
        )
        _emit_optional_progress(progress_callback, "ocr", index, total)
    return units


def _pdf_visual_caption_units(
    settings: Settings,
    scanned: ScannedFile,
    file_id: str,
    version_parts: tuple[str, str, str, str],
    visual_units: list[IndexedUnit],
    stats: ExtractionStats,
    progress_callback: Callable[[str, int, int], object] | None,
) -> list[IndexedUnit]:
    captioner = build_local_vlm_captioner(settings)
    units: list[IndexedUnit] = []
    candidates = [unit for unit in visual_units if unit.source_path is not None]
    total = len(candidates)
    for index, visual in enumerate(candidates, start=1):
        if visual.source_path is None:
            continue
        _emit_optional_progress(progress_callback, "vlm", index - 1, total)
        stats.vlm_attempted += 1
        try:
            result = captioner.caption_region(
                visual.source_path,
                {
                    "relative_path": scanned.relative_path,
                    "page_no": visual.page_no,
                    "image_no": visual.image_no,
                    "bbox": visual.bbox,
                },
            )
        except Exception:
            stats.vlm_failed += 1
            _emit_optional_progress(progress_callback, "vlm", index, total)
            continue
        text = redact_secret_text(result.text or "")
        if not text.strip():
            stats.vlm_empty += 1
            _emit_optional_progress(progress_callback, "vlm", index, total)
            continue
        stats.vlm_succeeded += 1
        profile = captioner.profile
        units.append(
            IndexedUnit(
                workspace_id=settings.workspace_id,
                root_id=scanned.root_id,
                file_id=file_id,
                unit_id=unit_id_for_parts(
                    *version_parts,
                    "pdf_visual_caption",
                    visual.page_no or 0,
                    visual.image_no or 0,
                    profile,
                ),
                unit_type="pdf_visual_caption",
                relative_path=scanned.relative_path,
                mime_type=scanned.mime_type,
                ext=scanned.ext,
                size_bytes=scanned.size_bytes,
                mtime_ns=scanned.mtime_ns,
                content_hash=scanned.content_hash,
                modality="text",
                text=text,
                text_preview=preview(text),
                page_no=visual.page_no,
                image_no=visual.image_no,
                bbox=visual.bbox,
                source_kind="pdf",
                extractor_profile=profile,
                locality=result.locality.to_payload(),
            )
        )
        _emit_optional_progress(progress_callback, "vlm", index, total)
    return units


def _run_tesseract(
    command: str,
    image_path: Path,
    lang: str,
    tessdata_dir: str = "",
    psm: str = "",
) -> str:
    args = [command, str(image_path), "stdout", "-l", lang]
    if tessdata_dir:
        args.extend(["--tessdata-dir", tessdata_dir])
    if psm:
        args.extend(["--psm", psm])
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout or ""


def _ocr_extractor_profile(settings: Settings) -> str:
    profile = f"tesseract-local-ocr-v1:{settings.pdf_ocr_lang}"
    if settings.tesseract_psm:
        profile = f"{profile}:psm{settings.tesseract_psm}"
    return profile


def _pdf_table_units(
    settings: Settings,
    scanned: ScannedFile,
    path: Path,
    file_id: str,
    version_parts: tuple[str, str, str, str],
    stats: ExtractionStats,
    progress_callback: Callable[[str, int, int], object] | None,
) -> list[IndexedUnit]:
    try:
        import pdfplumber
    except ImportError:
        return []

    units: list[IndexedUnit] = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages):
            page_no = page_index + 1
            _emit_optional_progress(progress_callback, "table", page_index, total)
            for table_no, rows, bbox in _iter_pdf_tables(page):
                stats.table_attempted += 1
                text = _table_text(
                    page_no,
                    table_no,
                    rows,
                    context=_table_page_context(page),
                )
                if not text:
                    stats.table_empty += 1
                    continue
                stats.table_succeeded += 1
                units.append(
                    IndexedUnit(
                        workspace_id=settings.workspace_id,
                        root_id=scanned.root_id,
                        file_id=file_id,
                        unit_id=unit_id_for_parts(
                            *version_parts,
                            "pdf_table",
                            page_no,
                            table_no,
                        ),
                        unit_type="pdf_table",
                        relative_path=scanned.relative_path,
                        mime_type=scanned.mime_type,
                        ext=scanned.ext,
                        size_bytes=scanned.size_bytes,
                        mtime_ns=scanned.mtime_ns,
                        content_hash=scanned.content_hash,
                        modality="text",
                        text=text,
                        text_preview=preview(text),
                        page_no=page_no,
                        table_no=table_no,
                        bbox=bbox,
                        source_kind="pdf",
                        extractor_profile="pdfplumber-local-table-v1",
                    )
                )
            _emit_optional_progress(progress_callback, "table", page_index + 1, total)
    return units


def _emit_optional_progress(
    progress_callback: Callable[[str, int, int], object] | None,
    phase: str,
    processed: int,
    total: int,
) -> None:
    if progress_callback is not None:
        progress_callback(phase, processed, total)


def _iter_pdf_tables(page):
    try:
        tables = page.find_tables()
    except Exception:
        tables = []
    if tables:
        for table_no, table in enumerate(tables):
            rows = table.extract() or []
            yield table_no, rows, _bbox_tuple(getattr(table, "bbox", None))
        return
    try:
        extracted = page.extract_tables() or []
    except Exception:
        extracted = []
    for table_no, rows in enumerate(extracted):
        yield table_no, rows, None


def _table_text(page_no: int, table_no: int, rows, context: str = "") -> str:
    normalized_rows = []
    for row in rows or []:
        cells = _trim_empty_edges([_cell_text(cell) for cell in (row or [])])
        if any(cells):
            normalized_rows.append(cells)
    if not normalized_rows:
        return ""
    columns = max(len(row) for row in normalized_rows)
    body = "\n".join(" | ".join(row) for row in normalized_rows)
    context_line = f"Context: {context}\n" if context else ""
    return redact_secret_text(
        f"PDF table page {page_no} table {table_no}\n"
        f"Rows: {len(normalized_rows)} Columns: {columns}\n"
        f"{context_line}"
        f"{body}"
    ).strip()


def _table_page_context(page) -> str:
    try:
        text = page.extract_text() or ""
    except Exception:
        return ""
    return " ".join(text.split())[:600]


def _cell_text(cell) -> str:
    return " ".join(str(cell or "").split())


def _trim_empty_edges(cells: list[str]) -> list[str]:
    while cells and not cells[0]:
        cells = cells[1:]
    while cells and not cells[-1]:
        cells = cells[:-1]
    return cells


def _bbox_tuple(bbox) -> tuple[float, float, float, float] | None:
    if bbox is None or len(bbox) != 4:
        return None
    return tuple(round(float(value), 3) for value in bbox)


def _write_pdf_visual_source(
    settings: Settings,
    doc,
    page,
    xref: int,
    file_id: str,
    scanned: ScannedFile,
    page_no: int,
    image_index: int,
    rect_index: int,
    rect,
) -> Path:
    output_dir = settings.cache_dir / "pdf_images" / file_id
    output_dir.mkdir(parents=True, exist_ok=True)
    source_kind = "region" if rect is not None else "image"
    output = (
        output_dir
        / (
            f"{scanned.content_hash[:12]}_p{page_no:04d}_"
            f"i{image_index:04d}_r{rect_index:04d}_{source_kind}.png"
        )
    )
    if output.exists():
        return output
    if rect is not None:
        _write_pdf_region(page, rect, output)
        return output
    _write_pdf_image(doc, xref, output)
    return output


def _write_pdf_region(page, rect, output: Path) -> None:
    import fitz

    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
    try:
        pixmap.save(str(output))
    finally:
        pixmap = None


def _write_pdf_image(doc, xref: int, output: Path) -> None:
    import fitz

    pixmap = fitz.Pixmap(doc, xref)
    try:
        if pixmap.n > 4:
            converted = fitz.Pixmap(fitz.csRGB, pixmap)
            pixmap = converted
        pixmap.save(str(output))
    finally:
        pixmap = None


def _image_rects(page, xref: int):
    try:
        return page.get_image_rects(xref)
    except Exception:
        return []


def _rect_tuple(rect) -> tuple[float, float, float, float] | None:
    if rect is None:
        return None
    return (
        round(float(rect.x0), 3),
        round(float(rect.y0), 3),
        round(float(rect.x1), 3),
        round(float(rect.y1), 3),
    )
