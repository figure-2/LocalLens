from __future__ import annotations

import gc
import shutil
import time
from pathlib import Path
from typing import Any

from locallens.core.config import Settings
from locallens.core.types import IndexedUnit, SearchResult
from locallens.ingestion.fingerprint import point_id_for_unit


class QdrantStore:
    def __init__(self, settings: Settings, in_memory: bool = False):
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError(
                "qdrant-client is required. Install with: python -m pip install -e ."
            ) from exc

        self.settings = settings
        self.collection_name = settings.collection_name
        self.in_memory = in_memory
        if in_memory:
            self.client = QdrantClient(":memory:")
        elif settings.qdrant_url:
            settings.ensure_dirs()
            self.client = QdrantClient(
                url=settings.qdrant_url,
                timeout=settings.qdrant_timeout_seconds,
            )
        else:
            settings.ensure_dirs()
            self.client = QdrantClient(path=str(settings.qdrant_path))

    def ensure_collection(self) -> None:
        from qdrant_client import models

        names = {c.name for c in self.client.get_collections().collections}
        if self.collection_name in names:
            self._validate_collection_vectors()
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                self.settings.text_vector_name: models.VectorParams(
                    size=self.settings.text_dimension,
                    distance=models.Distance.COSINE,
                ),
                self.settings.vision_vector_name: models.VectorParams(
                    size=self.settings.vision_dimension,
                    distance=models.Distance.COSINE,
                ),
            },
        )
        for field_name in (
            "workspace_id",
            "root_id",
            "file_id",
            "unit_type",
            "modality",
            "ext",
            "content_hash",
            "text_embedding_profile",
            "vision_embedding_profile",
            "has_text_vector",
            "has_vision_vector",
        ):
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass

    def upsert_units(
        self,
        units: list[IndexedUnit],
        text_vectors: dict[str, list[float]],
        vision_vectors: dict[str, list[float]],
    ) -> list[tuple[str, int]]:
        from qdrant_client import models

        self.ensure_collection()
        points = []
        result_ids: list[tuple[str, int]] = []
        zero_text = [0.0] * self.settings.text_dimension
        zero_vision = [0.0] * self.settings.vision_dimension
        for unit in units:
            point_id = point_id_for_unit(unit.unit_id)
            text_vector = text_vectors.get(unit.unit_id, zero_text)
            vision_vector = vision_vectors.get(unit.unit_id, zero_vision)
            payload = self._payload(unit, bool(text_vectors.get(unit.unit_id)), bool(vision_vectors.get(unit.unit_id)))
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={
                        self.settings.text_vector_name: text_vector,
                        self.settings.vision_vector_name: vision_vector,
                    },
                    payload=payload,
                )
            )
            result_ids.append((unit.unit_id, point_id))
        if points:
            self.client.upsert(
                collection_name=self.collection_name, points=points, wait=True
            )
        return result_ids

    def search(
        self,
        vector_name: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        from qdrant_client import models

        self.ensure_collection()
        query_filter = self._filter(filters or {})
        using = vector_name
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                using=using,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            points = response.points
        except TypeError:
            points = self.client.search(
                collection_name=self.collection_name,
                query_vector=(using, query_vector),
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        return [_result_from_point(point) for point in points]

    def delete_points(self, point_ids: list[int]) -> None:
        if not point_ids:
            return
        from qdrant_client import models

        self.ensure_collection()
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(points=point_ids),
            wait=True,
        )

    def count(self) -> int:
        self.ensure_collection()
        return int(
            self.client.count(collection_name=self.collection_name, exact=True).count
        )

    def payload_records(self) -> list[dict[str, Any]]:
        self.ensure_collection()
        records = []
        offset = None
        while True:
            batch, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in batch:
                records.append({"id": point.id, "payload": point.payload or {}})
            if offset is None:
                return records

    def purge(self) -> None:
        if self.in_memory or self.settings.qdrant_url:
            names = {c.name for c in self.client.get_collections().collections}
            if self.collection_name in names:
                self.client.delete_collection(collection_name=self.collection_name)
            self.close()
            return
        self.close()
        path = self.settings.qdrant_path
        if path.exists():
            _remove_tree(path)

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        gc.collect()

    def drop_collection(self) -> None:
        names = {c.name for c in self.client.get_collections().collections}
        if self.collection_name in names:
            self.client.delete_collection(collection_name=self.collection_name)

    def _payload(self, unit: IndexedUnit, has_text: bool, has_vision: bool) -> dict[str, Any]:
        return {
            "workspace_id": unit.workspace_id,
            "root_id": unit.root_id,
            "file_id": unit.file_id,
            "unit_id": unit.unit_id,
            "unit_type": unit.unit_type,
            "relative_path": unit.relative_path,
            "mime_type": unit.mime_type,
            "ext": unit.ext,
            "size_bytes": unit.size_bytes,
            "mtime_ns": unit.mtime_ns,
            "content_hash": unit.content_hash,
            "page_no": unit.page_no,
            "chunk_no": unit.chunk_no,
            "image_no": unit.image_no,
            "table_no": unit.table_no,
            "bbox": list(unit.bbox) if unit.bbox else None,
            "source_kind": unit.source_kind,
            "extractor_profile": unit.extractor_profile,
            "locality": dict(unit.locality),
            "modality": unit.modality,
            "text_preview": unit.text_preview,
            "text_embedding_profile": self.settings.text_embedding_profile,
            "vision_embedding_profile": self.settings.vision_embedding_profile,
            "has_text_vector": has_text,
            "has_vision_vector": has_vision,
        }

    def _validate_collection_vectors(self) -> None:
        collection = self.client.get_collection(self.collection_name)
        vectors = collection.config.params.vectors
        sizes = {
            self.settings.text_vector_name: self.settings.text_dimension,
            self.settings.vision_vector_name: self.settings.vision_dimension,
        }
        for name, expected_size in sizes.items():
            actual = vectors.get(name) if isinstance(vectors, dict) else None
            actual_size = getattr(actual, "size", None)
            if actual_size != expected_size:
                raise ValueError(
                    f"Qdrant collection vector mismatch for {name}: "
                    f"expected {expected_size}, found {actual_size}. "
                    "Use a different data directory or run purge before switching profiles."
                )

    @staticmethod
    def _filter(filters: dict[str, Any]):
        from qdrant_client import models

        conditions = []
        for key, value in filters.items():
            if value is None:
                continue
            if isinstance(value, list):
                conditions.append(
                    models.FieldCondition(
                        key=key, match=models.MatchAny(any=value)
                    )
                )
                continue
            conditions.append(
                models.FieldCondition(
                    key=key, match=models.MatchValue(value=value)
                )
            )
        return models.Filter(must=conditions) if conditions else None


def _result_from_point(point) -> SearchResult:
    payload = point.payload or {}
    modality = str(payload.get("modality", ""))
    embedding_profile = (
        payload.get("text_embedding_profile")
        if modality == "text"
        else payload.get("vision_embedding_profile")
    )
    return SearchResult(
        score=float(point.score),
        modality=modality,
        relative_path=str(payload.get("relative_path", "")),
        page_no=payload.get("page_no"),
        snippet=str(payload.get("text_preview", "")),
        unit_type=str(payload.get("unit_type", "")),
        chunk_no=payload.get("chunk_no"),
        embedding_profile=str(embedding_profile or ""),
        payload=payload,
    )


def _remove_tree(path: Path) -> None:
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            gc.collect()
            if attempt == 4:
                raise
            time.sleep(0.1 * (attempt + 1))
