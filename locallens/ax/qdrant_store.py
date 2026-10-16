from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5

from locallens.ax.qdrant_contract import build_qdrant_payload
from locallens.ax.qdrant_contract import validate_qdrant_payload


DEFAULT_QDRANT_COLLECTION = "locallens_ax_chunks"


@dataclass(frozen=True)
class QdrantSearchHit:
    point_id: str
    score: float
    payload: dict[str, Any]


def point_id_for_chunk(chunk_id: str) -> str:
    """Build a stable UUID point id from a chunk id.

    Qdrant point IDs are unsigned integers or UUID strings. The mock corpus uses
    human-readable chunk ids, so the adapter maps them to deterministic UUIDs.
    """

    return str(uuid5(NAMESPACE_URL, f"locallens-ax:{chunk_id}"))


def build_qdrant_filter(
    *,
    acl_tags: Iterable[str],
    filters: dict[str, Any] | None = None,
) -> Any:
    """Build a Qdrant payload filter for ACL and optional metadata filters."""

    from qdrant_client import models

    filters = filters or {}
    must: list[Any] = []
    acl_values = [tag for tag in acl_tags if tag]
    if acl_values:
        must.append(
            models.FieldCondition(
                key="acl_tags",
                match=models.MatchAny(any=acl_values),
            )
        )

    for key in ("department_id", "document_type", "document_id", "modality"):
        value = filters.get(key)
        if value:
            must.append(
                models.FieldCondition(
                    key=key,
                    match=models.MatchValue(value=value),
                )
            )

    return models.Filter(must=must)


class QdrantVectorStore:
    """Qdrant adapter for AX chunk embeddings and payload search."""

    def __init__(
        self,
        client: Any,
        *,
        collection_name: str = DEFAULT_QDRANT_COLLECTION,
    ):
        self.client = client
        self.collection_name = collection_name

    def upsert_documents(
        self,
        documents: Iterable[dict[str, Any]],
        *,
        vectors_by_chunk_id: dict[str, list[float]],
        wait: bool = True,
    ) -> dict[str, Any]:
        from qdrant_client import models

        points = []
        skipped_chunks: list[str] = []
        for document in documents:
            for chunk in document["chunks"]:
                chunk_id = chunk["chunk_id"]
                vector = vectors_by_chunk_id.get(chunk_id)
                if vector is None:
                    skipped_chunks.append(chunk_id)
                    continue
                payload = build_qdrant_payload(document, chunk)
                errors = validate_qdrant_payload(payload)
                if errors:
                    raise ValueError(
                        f"Invalid Qdrant payload for {chunk_id}: {', '.join(errors)}"
                    )
                points.append(
                    models.PointStruct(
                        id=point_id_for_chunk(chunk_id),
                        vector=vector,
                        payload=payload,
                    )
                )

        if points:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=wait,
            )

        return {
            "collection_name": self.collection_name,
            "upserted": len(points),
            "skipped_chunks": skipped_chunks,
        }

    def search(
        self,
        *,
        query_vector: list[float],
        acl_tags: Iterable[str],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[QdrantSearchHit]:
        query_filter = build_qdrant_filter(acl_tags=acl_tags, filters=filters)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=max(1, min(top_k, 20)),
            with_payload=True,
        )
        points = getattr(response, "points", response)
        return [
            QdrantSearchHit(
                point_id=str(getattr(point, "id", "")),
                score=float(getattr(point, "score", 0.0)),
                payload=dict(getattr(point, "payload", {}) or {}),
            )
            for point in points
        ]


def build_qdrant_vector_store() -> QdrantVectorStore:
    """Build a Qdrant vector store from environment variables.

    Supported modes:
    - LOCALLENS_AX_QDRANT_URL: remote/local server URL
    - LOCALLENS_AX_QDRANT_PATH: persistent local Qdrant path
    - neither: in-memory Qdrant for local smoke tests
    """

    from qdrant_client import QdrantClient

    collection_name = os.getenv(
        "LOCALLENS_AX_QDRANT_COLLECTION",
        DEFAULT_QDRANT_COLLECTION,
    )
    url = os.getenv("LOCALLENS_AX_QDRANT_URL")
    api_key = os.getenv("LOCALLENS_AX_QDRANT_API_KEY")
    path = os.getenv("LOCALLENS_AX_QDRANT_PATH")

    if url:
        client = QdrantClient(url=url, api_key=api_key)
    elif path:
        client = QdrantClient(path=path)
    else:
        client = QdrantClient(":memory:")

    return QdrantVectorStore(client, collection_name=collection_name)
