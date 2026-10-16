from __future__ import annotations


def normalize_top_k(value: int | str) -> int:
    try:
        top_k = int(str(value).strip())
    except ValueError as exc:
        raise ValueError("Top K must be a positive integer.") from exc
    if top_k < 1:
        raise ValueError("Top K must be a positive integer.")
    return top_k


def normalize_path_prefix(path_prefix: str | None) -> str:
    if not path_prefix:
        return ""
    prefix = path_prefix.replace("\\", "/").strip()
    while prefix.startswith("./"):
        prefix = prefix[2:]
    prefix = prefix.strip("/")
    if not prefix:
        return ""
    if ":" in prefix or prefix.startswith("/") or ".." in prefix.split("/"):
        raise ValueError("Path prefix must be a relative folder.")
    return prefix


def build_payload_filters(
    workspace_id: str | None = None,
    root_id: str | None = None,
    unit_type: str | None = None,
    modality: str | None = None,
    ext: str | None = None,
    relative_path: str | list[str] | None = None,
    text_embedding_profile: str | None = None,
    vision_embedding_profile: str | None = None,
    has_text_vector: bool | None = None,
    has_vision_vector: bool | None = None,
) -> dict:
    filters: dict = {}
    if workspace_id:
        filters["workspace_id"] = workspace_id
    if root_id:
        filters["root_id"] = root_id
    if unit_type:
        filters["unit_type"] = unit_type
    if modality:
        filters["modality"] = modality
    if ext:
        filters["ext"] = ext
    if relative_path:
        filters["relative_path"] = relative_path
    if text_embedding_profile:
        filters["text_embedding_profile"] = text_embedding_profile
    if vision_embedding_profile:
        filters["vision_embedding_profile"] = vision_embedding_profile
    if has_text_vector is not None:
        filters["has_text_vector"] = has_text_vector
    if has_vision_vector is not None:
        filters["has_vision_vector"] = has_vision_vector
    return filters
