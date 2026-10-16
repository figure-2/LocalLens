from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from benchmarks.ocrtable_cache_keys import SCHEMA_VERSION as CACHE_KEY_SCHEMA_VERSION
from benchmarks.ocrtable_cache_keys import canonical_json_hash


SCHEMA_VERSION = "ocrtable-product-cache-v1"
ENTRY_TYPES = {
    "page_render",
    "detector_boxes",
    "recognized_words",
    "structured_rows",
    "document_result",
}
REQUIRED_METADATA_FIELDS = {
    "schema_version",
    "entry_type",
    "cache_key",
    "page_key",
    "roi_key",
    "document_result_key",
    "workspace_id",
    "root_id",
    "file_id",
    "unit_id",
    "content_hash",
    "relative_path_hash",
    "page_no",
    "normalized_bbox",
    "extractor_profile",
    "detector_profile",
    "recognizer_profile",
    "postprocess_profile",
    "locality_profile",
    "code_profile",
    "payload_sha256",
    "created_at",
}
BINDING_FIELDS = {
    "workspace_id",
    "root_id",
    "file_id",
    "unit_id",
    "content_hash",
    "relative_path_hash",
    "page_no",
    "extractor_profile",
    "detector_profile",
    "recognizer_profile",
    "postprocess_profile",
    "locality_profile",
    "code_profile",
}
STALE_REASONS = {
    "manifest-unit-missing",
    "workspace_id-mismatch",
    "root_id-mismatch",
    "file_id-mismatch",
    "unit_id-mismatch",
    "content_hash-mismatch",
    "relative_path_hash-mismatch",
    "page_no-mismatch",
    "extractor_profile-mismatch",
    "detector_profile-mismatch",
    "recognizer_profile-mismatch",
    "postprocess_profile-mismatch",
    "locality_profile-mismatch",
    "code_profile-mismatch",
}


@dataclass(frozen=True)
class CacheValidationResult:
    hit: bool
    reason: str
    stale: bool = False
    corrupt: bool = False

    @property
    def lifecycle_action(self) -> str:
        if self.hit:
            return "reuse"
        if self.stale:
            return "delete-or-quarantine"
        if self.corrupt:
            return "quarantine"
        return "miss"


def build_cache_entry(
    *,
    entry_type: str,
    cache_key: str,
    workspace_id: str,
    root_id: str,
    file_id: str,
    unit_id: str,
    content_hash: str,
    relative_path_hash: str,
    page_no: int,
    extractor_profile: Mapping[str, Any],
    detector_profile: Mapping[str, Any],
    recognizer_profile: Mapping[str, Any],
    postprocess_profile: Mapping[str, Any],
    locality_profile: Mapping[str, Any],
    code_profile: str,
    payload: Mapping[str, Any],
    page_key: str | None = None,
    roi_key: str | None = None,
    document_result_key: str | None = None,
    normalized_bbox: list[float] | None = None,
    created_at: str = "1970-01-01T00:00:00Z",
) -> dict[str, Any]:
    if entry_type not in ENTRY_TYPES:
        raise ValueError(f"unsupported cache entry type: {entry_type}")
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "entry_type": entry_type,
        "cache_key": cache_key,
        "page_key": page_key or "",
        "roi_key": roi_key or "",
        "document_result_key": document_result_key or "",
        "workspace_id": workspace_id,
        "root_id": root_id,
        "file_id": file_id,
        "unit_id": unit_id,
        "content_hash": content_hash,
        "relative_path_hash": relative_path_hash,
        "page_no": page_no,
        "normalized_bbox": normalized_bbox or [],
        "extractor_profile": dict(extractor_profile),
        "detector_profile": dict(detector_profile),
        "recognizer_profile": dict(recognizer_profile),
        "postprocess_profile": dict(postprocess_profile),
        "locality_profile": dict(locality_profile),
        "code_profile": code_profile,
        "payload_sha256": _payload_sha256(payload),
        "created_at": created_at,
    }
    canonical_json_hash(metadata)
    return {"metadata": metadata, "payload": dict(payload)}


def validate_cache_entry(entry: Mapping[str, Any]) -> CacheValidationResult:
    metadata = entry.get("metadata")
    payload = entry.get("payload")
    if not isinstance(metadata, Mapping) or not isinstance(payload, Mapping):
        return CacheValidationResult(False, "invalid-entry-shape", corrupt=True)
    missing = sorted(field for field in REQUIRED_METADATA_FIELDS if field not in metadata)
    if missing:
        return CacheValidationResult(False, f"missing-metadata:{','.join(missing)}", corrupt=True)
    try:
        canonical_json_hash(metadata)
        canonical_json_hash(payload)
    except ValueError:
        return CacheValidationResult(False, "absolute-path-payload", corrupt=True)
    if metadata["schema_version"] != SCHEMA_VERSION:
        return CacheValidationResult(False, "schema-version-mismatch", corrupt=True)
    if metadata["entry_type"] not in ENTRY_TYPES:
        return CacheValidationResult(False, "entry-type-mismatch", corrupt=True)
    key_result = _validate_entry_keys(metadata)
    if key_result is not None:
        return key_result
    if _payload_sha256(payload) != metadata["payload_sha256"]:
        return CacheValidationResult(False, "payload-checksum-mismatch", corrupt=True)
    return CacheValidationResult(True, "valid")


def validate_cache_hit(
    entry: Mapping[str, Any],
    current_binding: Mapping[str, Any],
) -> CacheValidationResult:
    entry_result = validate_cache_entry(entry)
    if not entry_result.hit:
        return entry_result
    metadata = entry["metadata"]
    if not current_binding.get("unit_exists", True):
        return CacheValidationResult(False, "manifest-unit-missing", stale=True)
    for field in sorted(BINDING_FIELDS):
        if metadata.get(field) != current_binding.get(field):
            reason = f"{field}-mismatch"
            return CacheValidationResult(False, reason, stale=reason in STALE_REASONS)
    return CacheValidationResult(True, "cache-hit")


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return canonical_json_hash(payload)


def _validate_entry_keys(metadata: Mapping[str, Any]) -> CacheValidationResult | None:
    entry_type = str(metadata["entry_type"])
    cache_key = str(metadata["cache_key"])
    if not cache_key.startswith(f"{SCHEMA_VERSION}:{entry_type}:"):
        return CacheValidationResult(False, "cache-key-prefix-mismatch", corrupt=True)
    if not metadata.get("page_key"):
        return CacheValidationResult(False, "page-key-missing", corrupt=True)
    page_result = _validate_reference_key(metadata["page_key"], "page")
    if page_result is not None:
        return page_result
    if entry_type in {"recognized_words", "structured_rows"}:
        if not metadata.get("roi_key"):
            return CacheValidationResult(False, "roi-key-missing", corrupt=True)
        roi_result = _validate_reference_key(metadata["roi_key"], "roi")
        if roi_result is not None:
            return roi_result
        if not metadata.get("normalized_bbox"):
            return CacheValidationResult(False, "normalized-bbox-missing", corrupt=True)
    if entry_type == "document_result":
        if not metadata.get("document_result_key"):
            return CacheValidationResult(False, "document-result-key-missing", corrupt=True)
        document_result = _validate_reference_key(
            metadata["document_result_key"], "document_result"
        )
        if document_result is not None:
            return document_result
    return None


def _validate_reference_key(value: Any, stage: str) -> CacheValidationResult | None:
    prefix = f"{CACHE_KEY_SCHEMA_VERSION}:{stage}:"
    if not isinstance(value, str) or not value.startswith(prefix):
        reason_stage = stage.replace("_", "-")
        return CacheValidationResult(
            False, f"{reason_stage}-key-prefix-mismatch", corrupt=True
        )
    return None
