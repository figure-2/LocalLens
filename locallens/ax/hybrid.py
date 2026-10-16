from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RetrievalCandidate:
    document_id: str
    chunk_id: str
    title: str
    snippet: str
    source_ref: str
    page: int | None
    modality: str
    department_id: str
    document_type: str
    score: float
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    match_type: str = "keyword"


def fuse_candidates(
    keyword_candidates: Iterable[RetrievalCandidate],
    semantic_candidates: Iterable[RetrievalCandidate],
    *,
    top_k: int = 5,
    keyword_weight: float = 0.55,
    semantic_weight: float = 0.45,
    overlap_bonus: float = 0.10,
) -> list[RetrievalCandidate]:
    """Fuse keyword and semantic retrieval candidates into one ranked list."""

    keyword_items = list(keyword_candidates)
    semantic_items = list(semantic_candidates)
    keyword_norm = _normalized_scores(keyword_items)
    semantic_norm = _normalized_scores(semantic_items)
    by_key: dict[tuple[str, str], dict[str, object]] = {}

    for item in keyword_items:
        key = (item.document_id, item.chunk_id)
        by_key[key] = {
            "base": item,
            "keyword_score": keyword_norm[key],
            "semantic_score": 0.0,
        }

    for item in semantic_items:
        key = (item.document_id, item.chunk_id)
        if key not in by_key:
            by_key[key] = {
                "base": item,
                "keyword_score": 0.0,
                "semantic_score": semantic_norm[key],
            }
        else:
            by_key[key]["semantic_score"] = semantic_norm[key]

    fused: list[RetrievalCandidate] = []
    for item in by_key.values():
        base = item["base"]
        assert isinstance(base, RetrievalCandidate)
        keyword_score = float(item["keyword_score"])
        semantic_score = float(item["semantic_score"])
        score = keyword_weight * keyword_score + semantic_weight * semantic_score
        match_type = "keyword"
        if keyword_score and semantic_score:
            score += overlap_bonus
            match_type = "hybrid"
        elif semantic_score:
            match_type = "semantic"
        fused.append(
            RetrievalCandidate(
                document_id=base.document_id,
                chunk_id=base.chunk_id,
                title=base.title,
                snippet=base.snippet,
                source_ref=base.source_ref,
                page=base.page,
                modality=base.modality,
                department_id=base.department_id,
                document_type=base.document_type,
                score=min(score, 1.0),
                keyword_score=keyword_score,
                semantic_score=semantic_score,
                match_type=match_type,
            )
        )

    fused.sort(key=lambda candidate: candidate.score, reverse=True)
    return fused[: max(1, min(top_k, 20))]


def _normalized_scores(
    candidates: list[RetrievalCandidate],
) -> dict[tuple[str, str], float]:
    if not candidates:
        return {}
    max_score = max(candidate.score for candidate in candidates) or 1.0
    return {
        (candidate.document_id, candidate.chunk_id): candidate.score / max_score
        for candidate in candidates
    }
