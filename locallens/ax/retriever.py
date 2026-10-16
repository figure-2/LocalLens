from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from locallens.ax.embeddings import deterministic_text_vector
from locallens.ax.hybrid import RetrievalCandidate
from locallens.ax.hybrid import fuse_candidates
from locallens.ax.metadata import metadata_repository
from locallens.ax.mock_corpus import MOCK_DOCUMENTS, MOCK_USERS
from locallens.ax.qdrant_store import build_qdrant_vector_store


@dataclass(frozen=True)
class EvidencePacket:
    document_id: str
    chunk_id: str
    title: str
    snippet: str
    source_ref: str
    page: int | None
    modality: str
    score: float
    keyword_score: float
    semantic_score: float
    match_type: str
    department_id: str
    document_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "snippet": self.snippet,
            "source_ref": self.source_ref,
            "page": self.page,
            "modality": self.modality,
            "score": round(self.score, 4),
            "keyword_score": round(self.keyword_score, 4),
            "semantic_score": round(self.semantic_score, 4),
            "match_type": self.match_type,
            "department_id": self.department_id,
            "document_type": self.document_type,
        }


def list_documents(user_id: str) -> list[dict[str, Any]]:
    user = _user(user_id)
    visible = []
    for doc in MOCK_DOCUMENTS:
        if _can_access(user, doc):
            visible.append(
                {
                    "document_id": doc["document_id"],
                    "title": doc["title"],
                    "department_id": doc["department_id"],
                    "document_type": doc["document_type"],
                    "version_id": doc["version_id"],
                    "chunk_count": len(doc["chunks"]),
                }
            )
    return visible


def search_documents(
    query: str,
    *,
    user_id: str = "employee_hr",
    top_k: int = 5,
    filters: dict[str, Any] | None = None,
) -> list[EvidencePacket]:
    backend = os.getenv("LOCALLENS_AX_RETRIEVAL_BACKEND", "mock").strip().lower()
    if backend == "hybrid":
        return _hybrid_search_documents(
            query,
            user_id=user_id,
            top_k=top_k,
            filters=filters,
        )
    return _mock_search_documents(
        query,
        user_id=user_id,
        top_k=top_k,
        filters=filters,
    )


def _mock_search_documents(
    query: str,
    *,
    user_id: str = "employee_hr",
    top_k: int = 5,
    filters: dict[str, Any] | None = None,
) -> list[EvidencePacket]:
    user = _user(user_id)
    query_terms = _terms(query)
    filters = filters or {}
    scored: list[EvidencePacket] = []
    for doc in MOCK_DOCUMENTS:
        if not _can_access(user, doc):
            continue
        if not _passes_filters(doc, filters):
            continue
        for chunk in doc["chunks"]:
            if filters.get("modality") and chunk.get("modality") != filters["modality"]:
                continue
            packet = _score_chunk(query_terms, query, doc, chunk)
            if packet.score > 0:
                scored.append(packet)
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[: max(1, min(top_k, 20))]


def _hybrid_search_documents(
    query: str,
    *,
    user_id: str = "employee_hr",
    top_k: int = 5,
    filters: dict[str, Any] | None = None,
) -> list[EvidencePacket]:
    filters = filters or {}
    keyword_candidates = metadata_repository.keyword_search_chunks(
        query,
        user_id=user_id,
        top_k=top_k * 2,
        filters=filters,
    )
    semantic_candidates = _qdrant_semantic_candidates(
        query,
        user_id=user_id,
        top_k=top_k * 2,
        filters=filters,
    )
    fused = fuse_candidates(
        keyword_candidates,
        semantic_candidates,
        top_k=top_k,
    )
    return [_candidate_to_packet(candidate) for candidate in fused]


def _qdrant_semantic_candidates(
    query: str,
    *,
    user_id: str,
    top_k: int,
    filters: dict[str, Any],
) -> list[RetrievalCandidate]:
    try:
        user = metadata_repository.user_context(user_id)
        vector_size = int(os.getenv("LOCALLENS_AX_MOCK_VECTOR_SIZE", "8"))
        hits = _qdrant_store().search(
            query_vector=deterministic_text_vector(query, size=vector_size),
            acl_tags=user.get("acl_tags", []),
            top_k=top_k,
            filters=filters,
        )
    except Exception:
        return []

    candidates: list[RetrievalCandidate] = []
    for hit in hits:
        if hit.score <= 0:
            continue
        payload = hit.payload
        document_id = payload.get("document_id", "")
        chunk_id = payload.get("chunk_id", "")
        page = payload.get("page")
        if not document_id or not chunk_id:
            continue
        candidates.append(
            RetrievalCandidate(
                document_id=document_id,
                chunk_id=chunk_id,
                title=payload.get("title", ""),
                snippet=payload.get("snippet", ""),
                source_ref=_source_ref(document_id, chunk_id, page),
                page=page,
                modality=payload.get("modality", "text"),
                department_id=payload.get("department_id", ""),
                document_type=payload.get("document_type", ""),
                score=hit.score,
                semantic_score=hit.score,
                match_type="semantic",
            )
        )
    return candidates


@lru_cache(maxsize=1)
def _qdrant_store():
    return build_qdrant_vector_store()


def _candidate_to_packet(candidate: RetrievalCandidate) -> EvidencePacket:
    return EvidencePacket(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        title=candidate.title,
        snippet=candidate.snippet,
        source_ref=candidate.source_ref,
        page=candidate.page,
        modality=candidate.modality,
        score=candidate.score,
        keyword_score=candidate.keyword_score,
        semantic_score=candidate.semantic_score,
        match_type=candidate.match_type,
        department_id=candidate.department_id,
        document_type=candidate.document_type,
    )


def _source_ref(document_id: str, chunk_id: str, page: int | None) -> str:
    if page is None:
        return f"{document_id}#chunk={chunk_id}"
    return f"{document_id}#page={page}&chunk={chunk_id}"


def _score_chunk(
    query_terms: set[str],
    raw_query: str,
    doc: dict[str, Any],
    chunk: dict[str, Any],
) -> EvidencePacket:
    chunk_terms = _terms(chunk["text"]) | set(chunk.get("keywords", []))
    title_terms = _terms(doc["title"])
    overlap = query_terms & (chunk_terms | title_terms)
    keyword_score = len(overlap) / max(1, len(query_terms))
    semantic_score = _semantic_score(raw_query, doc, chunk)
    score = keyword_score * 0.65 + semantic_score * 0.35
    match_type = "hybrid"
    if keyword_score > 0 and semantic_score == 0:
        match_type = "keyword"
    elif semantic_score > 0 and keyword_score == 0:
        match_type = "semantic"
    source_ref = f"{doc['document_id']}#chunk={chunk['chunk_id']}"
    if chunk.get("page") is not None:
        source_ref = f"{doc['document_id']}#page={chunk['page']}&chunk={chunk['chunk_id']}"
    return EvidencePacket(
        document_id=doc["document_id"],
        chunk_id=chunk["chunk_id"],
        title=doc["title"],
        snippet=chunk["text"],
        source_ref=source_ref,
        page=chunk.get("page"),
        modality=chunk["modality"],
        score=score,
        keyword_score=keyword_score,
        semantic_score=semantic_score,
        match_type=match_type,
        department_id=doc["department_id"],
        document_type=doc["document_type"],
    )


def _semantic_score(query: str, doc: dict[str, Any], chunk: dict[str, Any]) -> float:
    normalized = query.lower()
    groups = [
        ({"휴가", "연차", "반차", "근태", "쉬는", "병가"}, {"휴가", "연차", "병가", "근태"}),
        ({"장애", "에러", "온콜", "알림", "장애대응"}, {"장애", "온콜", "에러율", "재발"}),
        ({"제안", "고객", "영업", "비용", "도입"}, {"제안서", "고객", "비용", "일정"}),
        ({"보안", "권한", "기밀", "접근"}, {"보안", "권한", "기밀", "접근"}),
        ({"ax", "자동화", "문서검색", "지식"}, {"AX", "문서", "검색", "지식"}),
    ]
    chunk_terms = set(chunk.get("keywords", [])) | _terms(chunk["text"]) | _terms(doc["title"])
    for query_group, chunk_group in groups:
        if any(term.lower() in normalized for term in query_group) and chunk_terms & chunk_group:
            return 0.8
    return 0.0


def _passes_filters(doc: dict[str, Any], filters: dict[str, Any]) -> bool:
    department_id = filters.get("department_id")
    if department_id and doc["department_id"] != department_id:
        return False
    document_type = filters.get("document_type")
    if document_type and doc["document_type"] != document_type:
        return False
    return True


def _can_access(user: dict[str, Any], doc: dict[str, Any]) -> bool:
    return bool(set(user["acl_tags"]) & set(doc["acl_tags"]))


def _user(user_id: str) -> dict[str, Any]:
    if user_id not in MOCK_USERS:
        return MOCK_USERS["employee_hr"]
    return MOCK_USERS[user_id]


def _terms(text: str) -> set[str]:
    return {
        term.lower()
        for term in re.findall(r"[A-Za-z0-9가-힣]+", text)
        if len(term) >= 2
    }
