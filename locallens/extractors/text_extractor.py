from __future__ import annotations

from pathlib import Path

from locallens.core.config import Settings
from locallens.core.types import IndexedUnit, ScannedFile
from locallens.extractors.chunking import chunk_text, preview
from locallens.ingestion.fingerprint import file_id_for_path, unit_id_for_parts
from locallens.security.redaction import redact_secret_text


class TextExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract(self, scanned: ScannedFile) -> list[IndexedUnit]:
        path = scanned.root_path / scanned.relative_path
        text = redact_secret_text(_read_text(path))
        file_id = file_id_for_path(
            self.settings.workspace_id, scanned.root_id, scanned.relative_path
        )
        version_parts = (
            file_id,
            scanned.content_hash,
            self.settings.text_embedding_profile,
            self.settings.vision_embedding_profile,
        )
        units: list[IndexedUnit] = []
        document_id = unit_id_for_parts(*version_parts, "document")
        units.append(
            _unit(
                self.settings.workspace_id,
                scanned,
                file_id,
                document_id,
                "document",
                "text",
                text,
                None,
                None,
            )
        )
        for index, chunk in enumerate(
            chunk_text(text, self.settings.chunk_size, self.settings.chunk_overlap)
        ):
            unit_id = unit_id_for_parts(*version_parts, "chunk", index)
            units.append(
                _unit(
                    self.settings.workspace_id,
                    scanned,
                    file_id,
                    unit_id,
                    "chunk",
                    "text",
                    chunk,
                    None,
                    index,
                )
            )
        return units


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp949", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


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
