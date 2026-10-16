from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "ocrtable-cache-v1"
PATH_FRAGMENT_PATTERNS = (
    re.compile(r"file:/{3}", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\|/)"),
    re.compile(r"(?<![\w:])/(?:home|users|var|tmp|etc|mnt|opt|root|private)/", re.IGNORECASE),
    re.compile(r"(?:^|[^\\])\\\\[^\\]+\\[^\\]+"),
)
PAGE_RENDER_PROFILE_FIELDS = {
    "render_scale",
    "rotation_degrees",
    "color_mode",
    "normalization_version",
}
DETECTOR_PROFILE_FIELDS = {
    "detector_model_id",
    "model_cache_fingerprint",
    "score_threshold",
    "runtime_family",
    "runtime_options",
}
LOCALITY_PROFILE_FIELDS = {"cache_status", "verification"}
ROI_TRANSFORM_PROFILE_FIELDS = {"bbox_source", "crop_margin", "transform_version"}
RECOGNIZER_PROFILE_FIELDS = {
    "recognizer_model_id",
    "model_cache_fingerprint",
    "score_threshold",
}
POSTPROCESS_PROFILE_FIELDS = {
    "row_grouping_version",
    "cell_assignment_version",
    "table_filter_version",
    "structured_output_version",
}
DOCUMENT_ASSEMBLY_PROFILE_FIELDS = {"assembly_version"}


def page_key(
    *,
    workspace_id: str,
    root_id: str,
    file_id: str,
    content_hash: str,
    relative_path_hash: str,
    page_no: int,
    render_profile: Mapping[str, Any],
    detector_profile: Mapping[str, Any],
    locality_profile: Mapping[str, Any],
    code_profile: str,
) -> str:
    _require_non_empty_strings(
        {
            "workspace_id": workspace_id,
            "root_id": root_id,
            "file_id": file_id,
            "content_hash": content_hash,
            "relative_path_hash": relative_path_hash,
            "code_profile": code_profile,
        }
    )
    if page_no < 1:
        raise ValueError("page_no must be 1 or greater")
    _require_fields("render_profile", render_profile, PAGE_RENDER_PROFILE_FIELDS)
    _require_fields("detector_profile", detector_profile, DETECTOR_PROFILE_FIELDS)
    _require_exact_fields("locality_profile", locality_profile, LOCALITY_PROFILE_FIELDS)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "stage": "page",
        "workspace_id": workspace_id,
        "root_id": root_id,
        "file_id": file_id,
        "content_hash": content_hash,
        "relative_path_hash": relative_path_hash,
        "page_no": page_no,
        "render_profile": dict(render_profile),
        "detector_profile": dict(detector_profile),
        "locality_profile": dict(locality_profile),
        "code_profile": code_profile,
    }
    return cache_key("page", payload)


def roi_key(
    *,
    page_key_value: str,
    normalized_bbox: Sequence[float],
    roi_transform_profile: Mapping[str, Any],
    recognizer_profile: Mapping[str, Any],
    postprocess_profile: Mapping[str, Any],
    code_profile: str,
) -> str:
    _validate_key_prefix("page_key_value", page_key_value, "page")
    _validate_normalized_bbox(normalized_bbox)
    _require_non_empty_strings({"code_profile": code_profile})
    _require_fields(
        "roi_transform_profile", roi_transform_profile, ROI_TRANSFORM_PROFILE_FIELDS
    )
    _require_fields("recognizer_profile", recognizer_profile, RECOGNIZER_PROFILE_FIELDS)
    _require_fields("postprocess_profile", postprocess_profile, POSTPROCESS_PROFILE_FIELDS)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "stage": "roi",
        "page_key": page_key_value,
        "normalized_bbox": list(normalized_bbox),
        "roi_transform_profile": dict(roi_transform_profile),
        "recognizer_profile": dict(recognizer_profile),
        "postprocess_profile": dict(postprocess_profile),
        "code_profile": code_profile,
    }
    return cache_key("roi", payload)


def document_result_key(
    *,
    page_key_value: str,
    roi_key_values: Sequence[str],
    document_assembly_profile: Mapping[str, Any],
    code_profile: str,
) -> str:
    _validate_key_prefix("page_key_value", page_key_value, "page")
    if not roi_key_values:
        raise ValueError("roi_key_values must not be empty")
    for index, roi_key_value in enumerate(roi_key_values):
        _validate_key_prefix(f"roi_key_values[{index}]", roi_key_value, "roi")
    _require_non_empty_strings({"code_profile": code_profile})
    _require_fields(
        "document_assembly_profile",
        document_assembly_profile,
        DOCUMENT_ASSEMBLY_PROFILE_FIELDS,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "stage": "document_result",
        "page_key": page_key_value,
        "roi_keys": list(roi_key_values),
        "document_assembly_profile": dict(document_assembly_profile),
        "code_profile": code_profile,
    }
    return cache_key("document_result", payload)


def cache_key(stage: str, payload: Mapping[str, Any]) -> str:
    return f"{SCHEMA_VERSION}:{stage}:{canonical_json_hash(payload)}"


def canonical_json_hash(payload: Mapping[str, Any]) -> str:
    content = canonical_json_bytes(payload)
    return hashlib.sha256(content).hexdigest()


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    _reject_absolute_paths(payload)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _reject_absolute_paths(value: Any) -> None:
    if isinstance(value, Mapping):
        for nested_value in value.values():
            _reject_absolute_paths(nested_value)
        return
    if isinstance(value, (list, tuple)):
        for nested_value in value:
            _reject_absolute_paths(nested_value)
        return
    if isinstance(value, str) and _looks_like_absolute_path(value):
        raise ValueError("cache key payload must not contain absolute paths")


def _looks_like_absolute_path(value: str) -> bool:
    if not value:
        return False
    if PureWindowsPath(value).is_absolute():
        return True
    if PurePosixPath(value).is_absolute():
        return True
    return any(pattern.search(value) for pattern in PATH_FRAGMENT_PATTERNS)


def _require_non_empty_strings(values: Mapping[str, str]) -> None:
    for key, value in values.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"{key} must be a non-empty string")


def _require_fields(name: str, profile: Mapping[str, Any], fields: set[str]) -> None:
    missing = sorted(field for field in fields if field not in profile)
    if missing:
        raise ValueError(f"{name} missing required fields: {', '.join(missing)}")


def _require_exact_fields(name: str, profile: Mapping[str, Any], fields: set[str]) -> None:
    _require_fields(name, profile, fields)
    unexpected = sorted(field for field in profile if field not in fields)
    if unexpected:
        raise ValueError(f"{name} has unsupported fields: {', '.join(unexpected)}")


def _validate_key_prefix(name: str, value: str, stage: str) -> None:
    prefix = f"{SCHEMA_VERSION}:{stage}:"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError(f"{name} must be a {stage} cache key")


def _validate_normalized_bbox(value: Sequence[float]) -> None:
    if len(value) != 4:
        raise ValueError("normalized_bbox must contain four values")
    for item in value:
        number = float(item)
        if number < 0.0 or number > 1.0:
            raise ValueError("normalized_bbox values must be between 0 and 1")
