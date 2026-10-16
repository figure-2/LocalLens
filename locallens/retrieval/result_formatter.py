from __future__ import annotations

from locallens.core.types import SearchResult


def to_public_dict(result: SearchResult) -> dict:
    return {
        "score": round(result.score, 6),
        "modality": result.modality,
        "relative_path": result.relative_path,
        "page_no": result.page_no,
        "chunk_no": result.chunk_no,
        "snippet": result.snippet,
        "unit_type": result.unit_type,
        "embedding_profile": result.embedding_profile,
    }
