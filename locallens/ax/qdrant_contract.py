from __future__ import annotations

from typing import Any


REQUIRED_QDRANT_PAYLOAD_KEYS = {
    "document_id",
    "chunk_id",
    "version_id",
    "page",
    "modality",
    "department_id",
    "acl_tags",
    "document_type",
    "title",
    "snippet",
}


def build_qdrant_payload(document: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    """Build the AX Qdrant payload contract for document chunks."""

    return {
        "document_id": document["document_id"],
        "chunk_id": chunk["chunk_id"],
        "version_id": document["version_id"],
        "page": chunk.get("page"),
        "modality": chunk["modality"],
        "department_id": document["department_id"],
        "acl_tags": list(document["acl_tags"]),
        "document_type": document["document_type"],
        "title": document["title"],
        "snippet": chunk["text"],
    }


def validate_qdrant_payload(payload: dict[str, Any]) -> list[str]:
    missing = sorted(REQUIRED_QDRANT_PAYLOAD_KEYS - set(payload))
    invalid = []
    if not isinstance(payload.get("acl_tags"), list):
        invalid.append("acl_tags must be a list")
    if not payload.get("document_id"):
        invalid.append("document_id is required")
    if not payload.get("chunk_id"):
        invalid.append("chunk_id is required")
    return missing + invalid

