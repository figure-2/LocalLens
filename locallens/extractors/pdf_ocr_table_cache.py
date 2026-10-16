from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from locallens.core.config import Settings
from locallens.core.types import IndexedUnit, ScannedFile
from locallens.extractors.chunking import preview
from locallens.indexing.manifest import ManifestStore


SCHEMA_VERSION = "pdf-ocr-table-readthrough-v1"
ENTRY_TYPE = "pdf_ocr_table_units"
ALLOWED_UNIT_TYPES = {"pdf_ocr_text", "pdf_table"}


@dataclass(frozen=True)
class OcrTableCacheRead:
    status: str
    cache_key: str = ""
    units: list[IndexedUnit] = field(default_factory=list)


class PdfOcrTableReadThroughCache:
    def __init__(self, settings: Settings, manifest: ManifestStore):
        self.settings = settings
        self.manifest = manifest

    @property
    def enabled(self) -> bool:
        return (
            self.settings.pdf_ocr_table_cache_mode == "read-through"
            and (
                self.settings.pdf_ocr_mode == "local-ocr"
                or self.settings.pdf_table_mode == "local-table"
            )
        )

    def read(
        self,
        scanned: ScannedFile,
        file_id: str,
        version_parts: tuple[str, str, str, str],
    ) -> OcrTableCacheRead:
        if not self.enabled:
            return OcrTableCacheRead(status="disabled")
        cache_key = self.cache_key(scanned, file_id)
        entry = self.manifest.committed_cache_entry(
            cache_key=cache_key,
            workspace_id=self.settings.workspace_id,
            root_id=scanned.root_id,
            relative_path=scanned.relative_path,
            content_hash=scanned.content_hash,
            entry_type=ENTRY_TYPE,
        )
        if entry is None:
            return OcrTableCacheRead(status="miss", cache_key=cache_key)
        payload = self._read_payload(entry)
        if payload is None or not self._metadata_matches(payload, scanned, file_id):
            return OcrTableCacheRead(status="corrupt", cache_key=cache_key)
        units_payload = payload.get("units")
        if not isinstance(units_payload, list):
            return OcrTableCacheRead(status="corrupt", cache_key=cache_key)
        units = []
        for item in units_payload:
            if not isinstance(item, dict):
                return OcrTableCacheRead(status="corrupt", cache_key=cache_key)
            unit = _unit_from_payload(
                self.settings,
                scanned,
                file_id,
                version_parts,
                item,
            )
            if unit is None:
                return OcrTableCacheRead(status="corrupt", cache_key=cache_key)
            units.append(unit)
        return OcrTableCacheRead(status="hit", cache_key=cache_key, units=units)

    def stage(
        self,
        scanned: ScannedFile,
        file_id: str,
        units: list[IndexedUnit],
    ) -> str | None:
        if not self.enabled:
            return None
        optional_units = [
            unit for unit in units if unit.unit_type in ALLOWED_UNIT_TYPES
        ]
        cache_key = self.cache_key(scanned, file_id)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "workspace_id": self.settings.workspace_id,
            "root_id": scanned.root_id,
            "file_id": file_id,
            "relative_path": scanned.relative_path,
            "content_hash": scanned.content_hash,
            "cache_profile": self._profile_payload(scanned, file_id),
            "units": [_unit_payload(unit) for unit in optional_units],
        }
        payload_sha256 = _payload_sha256(payload)
        blob_rel_path = f"product_cache/pdf_ocr_table/{cache_key[:32]}.json"
        blob_path = _safe_cache_path(self.settings.cache_dir, blob_rel_path)
        if blob_path is None:
            raise ValueError("Cache blob path must stay inside cache directory.")
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(blob_path, payload)
        self.manifest.stage_cache_entry(
            cache_key=cache_key,
            workspace_id=self.settings.workspace_id,
            root_id=scanned.root_id,
            relative_path=scanned.relative_path,
            file_id=file_id,
            unit_id="",
            content_hash=scanned.content_hash,
            entry_type=ENTRY_TYPE,
            payload_sha256=payload_sha256,
            blob_rel_path=blob_rel_path,
        )
        return cache_key

    def cache_key(self, scanned: ScannedFile, file_id: str) -> str:
        return _text_digest(_canonical_json(self._profile_payload(scanned, file_id)))

    def _profile_payload(self, scanned: ScannedFile, file_id: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "workspace_id": self.settings.workspace_id,
            "root_id": scanned.root_id,
            "file_id": file_id,
            "relative_path_hash": _text_digest(scanned.relative_path),
            "content_hash": scanned.content_hash,
            "pdf_ocr_mode": self.settings.pdf_ocr_mode,
            "pdf_ocr_lang": (
                self.settings.pdf_ocr_lang
                if self.settings.pdf_ocr_mode == "local-ocr"
                else "off"
            ),
            "tesseract_cmd_hash": (
                _text_digest(self.settings.tesseract_cmd)
                if self.settings.pdf_ocr_mode == "local-ocr"
                else "off"
            ),
            "tessdata_dir_hash": (
                _text_digest(self.settings.tessdata_dir)
                if self.settings.pdf_ocr_mode == "local-ocr"
                else "off"
            ),
            "tesseract_psm": (
                self.settings.tesseract_psm
                if self.settings.pdf_ocr_mode == "local-ocr"
                else "off"
            ),
            "pdf_table_mode": self.settings.pdf_table_mode,
            "ocr_extractor_profile": _ocr_extractor_profile(self.settings),
            "table_extractor_profile": _table_extractor_profile(self.settings),
        }

    def _read_payload(self, entry: dict) -> dict[str, Any] | None:
        blob_path = _safe_cache_path(self.settings.cache_dir, str(entry["blob_rel_path"]))
        if blob_path is None or not blob_path.exists():
            return None
        try:
            payload = json.loads(blob_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if _payload_sha256(payload) != entry["payload_sha256"]:
            return None
        return payload

    def _metadata_matches(
        self,
        payload: dict[str, Any],
        scanned: ScannedFile,
        file_id: str,
    ) -> bool:
        return (
            payload.get("schema_version") == SCHEMA_VERSION
            and payload.get("workspace_id") == self.settings.workspace_id
            and payload.get("root_id") == scanned.root_id
            and payload.get("file_id") == file_id
            and payload.get("relative_path") == scanned.relative_path
            and payload.get("content_hash") == scanned.content_hash
            and payload.get("cache_profile") == self._profile_payload(scanned, file_id)
        )


def _unit_payload(unit: IndexedUnit) -> dict[str, Any]:
    return {
        "unit_type": unit.unit_type,
        "modality": unit.modality,
        "text": unit.text,
        "text_preview": unit.text_preview or preview(unit.text),
        "page_no": unit.page_no,
        "chunk_no": unit.chunk_no,
        "image_no": unit.image_no,
        "table_no": unit.table_no,
        "bbox": list(unit.bbox) if unit.bbox else None,
        "source_kind": unit.source_kind,
        "extractor_profile": unit.extractor_profile,
        "locality": dict(unit.locality),
    }


def _unit_from_payload(
    settings: Settings,
    scanned: ScannedFile,
    file_id: str,
    version_parts: tuple[str, str, str, str],
    payload: dict[str, Any],
) -> IndexedUnit | None:
    unit_type = str(payload.get("unit_type") or "")
    if unit_type not in ALLOWED_UNIT_TYPES:
        return None
    text = str(payload.get("text") or "")
    if not text and unit_type != "pdf_table":
        return None
    bbox = payload.get("bbox")
    if bbox is not None:
        if not isinstance(bbox, list) or len(bbox) != 4:
            return None
        try:
            bbox = tuple(round(float(value), 3) for value in bbox)
        except (TypeError, ValueError):
            return None
    page_no = _optional_int(payload.get("page_no"))
    image_no = _optional_int(payload.get("image_no"))
    table_no = _optional_int(payload.get("table_no"))
    expected_unit_id = _expected_unit_id(
        version_parts,
        unit_type,
        page_no,
        image_no,
        table_no,
        settings.pdf_ocr_lang,
    )
    locality = payload.get("locality")
    if not isinstance(locality, dict):
        locality = {}
    return IndexedUnit(
        workspace_id=settings.workspace_id,
        root_id=scanned.root_id,
        file_id=file_id,
        unit_id=expected_unit_id,
        unit_type=unit_type,
        relative_path=scanned.relative_path,
        mime_type=scanned.mime_type,
        ext=scanned.ext,
        size_bytes=scanned.size_bytes,
        mtime_ns=scanned.mtime_ns,
        content_hash=scanned.content_hash,
        modality=str(payload.get("modality") or "text"),
        text=text,
        text_preview=str(payload.get("text_preview") or preview(text)),
        page_no=page_no,
        chunk_no=_optional_int(payload.get("chunk_no")),
        image_no=image_no,
        table_no=table_no,
        bbox=bbox,
        source_kind=str(payload.get("source_kind") or ""),
        extractor_profile=str(payload.get("extractor_profile") or ""),
        locality=locality,
    )


def _expected_unit_id(
    version_parts: tuple[str, str, str, str],
    unit_type: str,
    page_no: int | None,
    image_no: int | None,
    table_no: int | None,
    pdf_ocr_lang: str,
) -> str:
    from locallens.ingestion.fingerprint import unit_id_for_parts

    if unit_type == "pdf_ocr_text":
        return unit_id_for_parts(
            *version_parts,
            "pdf_ocr_text",
            page_no or 0,
            image_no or 0,
            pdf_ocr_lang,
        )
    return unit_id_for_parts(
        *version_parts,
        "pdf_table",
        page_no or 0,
        table_no or 0,
    )


def _ocr_extractor_profile(settings: Settings) -> str:
    if settings.pdf_ocr_mode != "local-ocr":
        return "off"
    profile = f"tesseract-local-ocr-v1:{settings.pdf_ocr_lang}"
    if settings.tesseract_psm:
        profile = f"{profile}:psm{settings.tesseract_psm}"
    return profile


def _table_extractor_profile(settings: Settings) -> str:
    if settings.pdf_table_mode != "local-table":
        return "off"
    return "pdfplumber-local-table-v1"


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _payload_sha256(payload: dict[str, Any]) -> str:
    return _text_digest(_canonical_json(payload))


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_cache_path(cache_dir: Path, blob_rel_path: str) -> Path | None:
    root = cache_dir.resolve()
    candidate = (cache_dir / blob_rel_path).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
