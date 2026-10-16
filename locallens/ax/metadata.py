from __future__ import annotations

import os
import re
import time
import atexit
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from locallens.ax.hybrid import RetrievalCandidate
from locallens.ax.mock_corpus import MOCK_DOCUMENTS, MOCK_USERS


@dataclass(frozen=True)
class DocumentMetadata:
    document_id: str
    title: str
    department_id: str
    document_type: str
    version_id: str
    acl_tags: list[str]
    chunk_count: int

    def public_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "department_id": self.department_id,
            "document_type": self.document_type,
            "version_id": self.version_id,
            "chunk_count": self.chunk_count,
        }


class MetadataRepository(Protocol):
    backend_name: str

    def user_context(self, user_id: str) -> dict[str, Any]:
        ...

    def list_visible_documents(self, user_id: str) -> list[DocumentMetadata]:
        ...

    def can_read(self, user: dict[str, Any], document: dict[str, Any]) -> bool:
        ...

    def record_search(
        self,
        *,
        user_id: str,
        query: str,
        filters: dict[str, Any],
        result_count: int,
        latency_ms: int = 0,
    ) -> dict[str, Any]:
        ...

    def record_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def keyword_search_chunks(
        self,
        query: str,
        *,
        user_id: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalCandidate]:
        ...


class MockMetadataRepository:
    """PostgreSQL metadata adapter contract backed by mock corpus.

    The class mirrors the future PostgreSQL responsibilities without requiring a
    running database in mock E2E mode.
    """

    backend_name = "mock"

    def __init__(self):
        self.search_logs: list[dict[str, Any]] = []
        self.feedback: list[dict[str, Any]] = []

    def user_context(self, user_id: str) -> dict[str, Any]:
        return MOCK_USERS.get(user_id, MOCK_USERS["employee_hr"])

    def list_visible_documents(self, user_id: str) -> list[DocumentMetadata]:
        user = self.user_context(user_id)
        docs = []
        for doc in MOCK_DOCUMENTS:
            if self.can_read(user, doc):
                docs.append(
                    DocumentMetadata(
                        document_id=doc["document_id"],
                        title=doc["title"],
                        department_id=doc["department_id"],
                        document_type=doc["document_type"],
                        version_id=doc["version_id"],
                        acl_tags=list(doc["acl_tags"]),
                        chunk_count=len(doc["chunks"]),
                    )
                )
        return docs

    def can_read(self, user: dict[str, Any], document: dict[str, Any]) -> bool:
        return bool(set(user["acl_tags"]) & set(document["acl_tags"]))

    def record_search(
        self,
        *,
        user_id: str,
        query: str,
        filters: dict[str, Any],
        result_count: int,
        latency_ms: int = 0,
    ) -> dict[str, Any]:
        event = {
            "search_id": f"search_{uuid4().hex[:12]}",
            "user_id": user_id,
            "query": query,
            "filters": filters,
            "result_count": result_count,
            "latency_ms": latency_ms,
            "created_at": time.time(),
            "storage": "mock",
        }
        self.search_logs.append(event)
        return event

    def record_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "feedback_id": f"feedback_{uuid4().hex[:12]}",
            "created_at": time.time(),
            "storage": "mock",
            **payload,
        }
        self.feedback.append(event)
        return event

    def keyword_search_chunks(
        self,
        query: str,
        *,
        user_id: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalCandidate]:
        import re

        user = self.user_context(user_id)
        filters = filters or {}
        query_terms = {
            term.lower()
            for term in re.findall(r"[A-Za-z0-9가-힣]+", query)
            if len(term) >= 2
        }
        candidates: list[RetrievalCandidate] = []
        for doc in MOCK_DOCUMENTS:
            if not self.can_read(user, doc):
                continue
            if filters.get("department_id") and doc["department_id"] != filters["department_id"]:
                continue
            if filters.get("document_type") and doc["document_type"] != filters["document_type"]:
                continue
            for chunk in doc["chunks"]:
                if filters.get("modality") and chunk.get("modality") != filters["modality"]:
                    continue
                chunk_terms = {
                    term.lower()
                    for term in re.findall(r"[A-Za-z0-9가-힣]+", chunk["text"])
                    if len(term) >= 2
                } | {keyword.lower() for keyword in chunk.get("keywords", [])}
                overlap = query_terms & chunk_terms
                if not overlap:
                    continue
                score = len(overlap) / max(1, len(query_terms))
                source_ref = f"{doc['document_id']}#chunk={chunk['chunk_id']}"
                if chunk.get("page") is not None:
                    source_ref = (
                        f"{doc['document_id']}#page={chunk['page']}"
                        f"&chunk={chunk['chunk_id']}"
                    )
                candidates.append(
                    RetrievalCandidate(
                        document_id=doc["document_id"],
                        chunk_id=chunk["chunk_id"],
                        title=doc["title"],
                        snippet=chunk["text"],
                        source_ref=source_ref,
                        page=chunk.get("page"),
                        modality=chunk["modality"],
                        department_id=doc["department_id"],
                        document_type=doc["document_type"],
                        score=score,
                        keyword_score=score,
                        match_type="keyword",
                    )
                )
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates[: max(1, min(top_k, 20))]


class PostgresMetadataRepository:
    """PostgreSQL metadata adapter for AX document metadata and audit logs.

    Qdrant remains responsible for vector payload search. PostgreSQL owns user,
    document, access policy, search log, and feedback metadata.
    """

    backend_name = "postgres"

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 5):
        try:
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL metadata backend requires psycopg[binary,pool]."
            ) from exc

        self._jsonb = Jsonb
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
        )
        atexit.register(self.close)

    def close(self) -> None:
        self._pool.close(timeout=5.0)

    def user_context(self, user_id: str) -> dict[str, Any]:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT user_id, display_name, department_id, role
                FROM users
                WHERE user_id = %s
                """,
                (user_id,),
            ).fetchone()
        if not row:
            return {
                "user_id": user_id,
                "name": "",
                "department_id": "",
                "acl_tags": [],
            }
        acl_tags = ["all_employee", row["department_id"], row["role"]]
        return {
            "user_id": row["user_id"],
            "name": row["display_name"],
            "department_id": row["department_id"],
            "acl_tags": [tag for tag in acl_tags if tag],
        }

    def list_visible_documents(self, user_id: str) -> list[DocumentMetadata]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                WITH user_acl AS (
                    SELECT ARRAY['all_employee', department_id, role]::text[] AS tags
                    FROM users
                    WHERE user_id = %s
                )
                SELECT
                    d.document_id,
                    d.title,
                    d.owner_department_id AS department_id,
                    d.document_type,
                    d.current_version_id AS version_id,
                    COALESCE(
                        array_agg(DISTINCT ap.acl_tag)
                            FILTER (WHERE ap.acl_tag IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS acl_tags,
                    COUNT(DISTINCT dc.chunk_id)::int AS chunk_count
                FROM documents d
                JOIN access_policies ap
                    ON ap.document_id = d.document_id
                   AND ap.can_read = true
                JOIN user_acl ua
                    ON ap.acl_tag = ANY(ua.tags)
                LEFT JOIN document_chunks dc
                    ON dc.document_id = d.document_id
                   AND dc.version_id = d.current_version_id
                GROUP BY
                    d.document_id,
                    d.title,
                    d.owner_department_id,
                    d.document_type,
                    d.current_version_id,
                    d.updated_at
                ORDER BY d.updated_at DESC, d.title ASC
                """,
                (user_id,),
            ).fetchall()
        return [
            DocumentMetadata(
                document_id=row["document_id"],
                title=row["title"],
                department_id=row["department_id"],
                document_type=row["document_type"],
                version_id=row["version_id"],
                acl_tags=list(row["acl_tags"]),
                chunk_count=row["chunk_count"],
            )
            for row in rows
        ]

    def can_read(self, user: dict[str, Any], document: dict[str, Any]) -> bool:
        user_tags = set(user.get("acl_tags", []))
        document_tags = set(document.get("acl_tags", []))
        return bool(user_tags & document_tags)

    def record_search(
        self,
        *,
        user_id: str,
        query: str,
        filters: dict[str, Any],
        result_count: int,
        latency_ms: int = 0,
    ) -> dict[str, Any]:
        event = {
            "search_id": f"search_{uuid4().hex[:12]}",
            "user_id": user_id,
            "query": query,
            "filters": filters,
            "result_count": result_count,
            "latency_ms": latency_ms,
            "created_at": time.time(),
            "storage": self.backend_name,
        }
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO search_logs (
                    search_id,
                    user_id,
                    query,
                    filters,
                    result_count,
                    latency_ms
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    event["search_id"],
                    user_id,
                    query,
                    self._jsonb(filters),
                    result_count,
                    latency_ms,
                ),
            )
        return event

    def record_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "feedback_id": f"feedback_{uuid4().hex[:12]}",
            "created_at": time.time(),
            "storage": self.backend_name,
            **payload,
        }
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO feedback (
                    feedback_id,
                    search_id,
                    user_id,
                    document_id,
                    chunk_id,
                    rating,
                    note
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event["feedback_id"],
                    payload.get("search_id"),
                    payload["user_id"],
                    payload["document_id"],
                    payload["chunk_id"],
                    payload["rating"],
                    payload.get("note", ""),
                ),
            )
        return event

    def keyword_search_chunks(
        self,
        query: str,
        *,
        user_id: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalCandidate]:
        filters = filters or {}
        department_id = filters.get("department_id")
        document_type = filters.get("document_type")
        modality = filters.get("modality")
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                WITH user_acl AS (
                    SELECT ARRAY['all_employee', department_id, role]::text[] AS tags
                    FROM users
                    WHERE user_id = %s
                )
                SELECT DISTINCT ON (document_id, chunk_id)
                    d.document_id,
                    d.title,
                    d.owner_department_id AS department_id,
                    d.document_type,
                    dc.chunk_id,
                    dc.page_no AS page,
                    dc.modality,
                    dc.text_preview AS snippet
                FROM document_chunks dc
                JOIN documents d
                    ON d.document_id = dc.document_id
                   AND d.current_version_id = dc.version_id
                JOIN access_policies ap
                    ON ap.document_id = d.document_id
                   AND ap.can_read = true
                JOIN user_acl ua
                    ON ap.acl_tag = ANY(ua.tags)
                WHERE (%s::text IS NULL OR d.owner_department_id = %s)
                  AND (%s::text IS NULL OR d.document_type = %s)
                  AND (%s::text IS NULL OR dc.modality = %s)
                ORDER BY document_id, chunk_id, d.updated_at DESC
                LIMIT %s
                """,
                (
                    user_id,
                    department_id,
                    department_id,
                    document_type,
                    document_type,
                    modality,
                    modality,
                    max(20, min(top_k * 10, 200)),
                ),
            ).fetchall()
        candidates = []
        for row in rows:
            score = _token_overlap_score(query, row["title"], row["snippet"])
            if score <= 0:
                continue
            candidates.append(
                RetrievalCandidate(
                    document_id=row["document_id"],
                    chunk_id=row["chunk_id"],
                    title=row["title"],
                    snippet=row["snippet"],
                    source_ref=_source_ref(row["document_id"], row["chunk_id"], row["page"]),
                    page=row["page"],
                    modality=row["modality"],
                    department_id=row["department_id"],
                    document_type=row["document_type"],
                    score=score,
                    keyword_score=score,
                    match_type="keyword",
                )
            )
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates[: max(1, min(top_k, 20))]


def build_metadata_repository() -> MetadataRepository:
    backend = os.getenv("LOCALLENS_AX_METADATA_BACKEND", "mock").strip().lower()
    if backend in {"", "mock"}:
        return MockMetadataRepository()
    if backend == "postgres":
        dsn = os.getenv("LOCALLENS_AX_DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "LOCALLENS_AX_DATABASE_URL is required when "
                "LOCALLENS_AX_METADATA_BACKEND=postgres."
            )
        return PostgresMetadataRepository(dsn)
    raise RuntimeError(
        "Unsupported LOCALLENS_AX_METADATA_BACKEND. Use 'mock' or 'postgres'."
    )


metadata_repository = build_metadata_repository()


def _source_ref(document_id: str, chunk_id: str, page: int | None) -> str:
    if page is None:
        return f"{document_id}#chunk={chunk_id}"
    return f"{document_id}#page={page}&chunk={chunk_id}"


def _query_terms(text: str) -> set[str]:
    return {
        term.lower()
        for term in re.findall(r"[A-Za-z0-9가-힣]+", text)
        if len(term) >= 2
    }


def _token_overlap_score(query: str, title: str, snippet: str) -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.0
    title_lower = title.lower()
    snippet_lower = snippet.lower()
    title_matches = {term for term in terms if term in title_lower}
    snippet_matches = {term for term in terms if term in snippet_lower}
    matched = title_matches | snippet_matches
    base_score = len(matched) / len(terms)
    title_bonus = 0.10 * (len(title_matches) / len(terms))
    snippet_bonus = 0.20 * (len(snippet_matches) / len(terms))
    intent_bonus = _query_intent_bonus(query, snippet_lower)
    return min(base_score + title_bonus + snippet_bonus + intent_bonus, 1.25)


def _query_intent_bonus(query: str, snippet_lower: str) -> float:
    """Small local-smoke reranking bonus for Korean action-intent queries.

    This is not a production Korean search model. It only reduces obvious mock
    ranking noise when a user asks for an action such as "신청" or "작성" and
    the target chunk contains that action in its body.
    """

    query_lower = query.lower()
    bonus = 0.0
    action_terms = ("신청", "작성", "대응", "조치", "기록", "확인")
    for term in action_terms:
        if term in query_lower and term in snippet_lower:
            bonus += 0.35
            break
    if ("절차" in query_lower or "순서" in query_lower) and any(
        marker in snippet_lower
        for marker in ("신청합니다", "먼저", "순서", "단계", "메뉴")
    ):
        bonus += 0.15
    return min(bonus, 0.45)
