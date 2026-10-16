from __future__ import annotations

from locallens.core.config import Settings
from locallens.core.types import IndexedUnit, ScannedFile
from locallens.extractors.chunking import preview
from locallens.ingestion.fingerprint import file_id_for_path, unit_id_for_parts


class ImageExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract(self, scanned: ScannedFile) -> list[IndexedUnit]:
        file_id = file_id_for_path(
            self.settings.workspace_id, scanned.root_id, scanned.relative_path
        )
        version_parts = (
            file_id,
            scanned.content_hash,
            self.settings.text_embedding_profile,
            self.settings.vision_embedding_profile,
        )
        text = f"Image file {scanned.relative_path}"
        return [
            IndexedUnit(
                workspace_id=self.settings.workspace_id,
                root_id=scanned.root_id,
                file_id=file_id,
                unit_id=unit_id_for_parts(*version_parts, "image", 0),
                unit_type="image",
                relative_path=scanned.relative_path,
                mime_type=scanned.mime_type,
                ext=scanned.ext,
                size_bytes=scanned.size_bytes,
                mtime_ns=scanned.mtime_ns,
                content_hash=scanned.content_hash,
                modality="image",
                text=text,
                text_preview=preview(text),
                image_no=0,
            )
        ]
