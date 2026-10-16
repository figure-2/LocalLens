from __future__ import annotations

import re
from dataclasses import replace

from locallens.core.config import Settings
from locallens.core.types import SearchResult
from locallens.embeddings.profiles import with_embedding_profiles
from locallens.embeddings.text_embedder import TextEmbedder
from locallens.embeddings.vision_embedder import VisionEmbedder
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.retrieval.filters import (
    build_payload_filters,
    normalize_path_prefix,
    normalize_top_k,
)
from locallens.retrieval.korean_query_normalizer import normalize_korean_ocr_query
from locallens.retrieval.rerank_service import (
    RerankService,
    apply_rerank_service,
    build_rerank_service,
)


class SearchService:
    def __init__(
        self,
        settings: Settings,
        store: QdrantStore | None = None,
        manifest: ManifestStore | None = None,
        reranker: RerankService | None = None,
    ):
        self.text_embedder = TextEmbedder(settings)
        self.vision_embedder = VisionEmbedder(settings)
        self.settings = with_embedding_profiles(
            settings,
            text_dimension=self.text_embedder.dimension,
            vision_dimension=self.vision_embedder.dimension,
            text_profile=self.text_embedder.profile,
            vision_profile=self.vision_embedder.profile,
        )
        self.store = store or QdrantStore(self.settings)
        self.store.settings = self.settings
        self.manifest = manifest or ManifestStore(self.settings.manifest_path)
        self.reranker = reranker or build_rerank_service(self.settings)

    def search(
        self,
        query: str,
        top_k: int = 10,
        modality: str | None = None,
        root_id: str | None = None,
        unit_type: str | None = None,
        ext: str | None = None,
        path_prefix: str | None = None,
    ) -> list[SearchResult]:
        top_k = normalize_top_k(top_k)
        fetch_k = max(top_k * 3, top_k + 10)
        results: list[SearchResult] = []
        prefix = normalize_path_prefix(path_prefix)
        matching_paths = self._matching_paths(prefix, root_id)
        text_query = normalize_korean_ocr_query(
            query,
            self.settings.kocr_query_normalization_mode,
        )
        if prefix and not matching_paths:
            return []
        if modality in (None, "text"):
            text_filters = build_payload_filters(
                workspace_id=self.settings.workspace_id,
                root_id=root_id,
                unit_type=unit_type,
                modality="text",
                ext=ext,
                relative_path=matching_paths,
                text_embedding_profile=self.settings.text_embedding_profile,
                has_text_vector=True,
            )
            results.extend(
                self.store.search(
                    self.settings.text_vector_name,
                    self.text_embedder.embed_query(text_query),
                    top_k=fetch_k,
                    filters=text_filters,
                )
            )
        if modality in (None, "image"):
            vision_filters = build_payload_filters(
                workspace_id=self.settings.workspace_id,
                root_id=root_id,
                unit_type=unit_type,
                modality="image",
                ext=ext,
                relative_path=matching_paths,
                vision_embedding_profile=self.settings.vision_embedding_profile,
                has_vision_vector=True,
            )
            results.extend(
                self.store.search(
                    self.settings.vision_vector_name,
                    self.vision_embedder.embed_query(query),
                    top_k=fetch_k,
                    filters=vision_filters,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        results = self._drop_stale(results)
        results = _filter_path_prefix(results, prefix)
        results = _rerank_text_results(text_query, results)
        results = _rerank_table_results(query, results)
        results = apply_rerank_service(query, results, self.reranker)
        return results[:top_k]

    def _drop_stale(self, results: list[SearchResult]) -> list[SearchResult]:
        kept: list[SearchResult] = []
        for result in results:
            workspace_id = result.payload.get("workspace_id")
            root_id = result.payload.get("root_id")
            relative_path = result.payload.get("relative_path")
            unit_id = result.payload.get("unit_id")
            if (
                workspace_id
                and root_id
                and relative_path
                and unit_id
                and self.manifest.has_unit(
                    str(workspace_id),
                    str(root_id),
                    str(relative_path),
                    str(unit_id),
                    content_hash=result.payload.get("content_hash"),
                    text_embedding_profile=result.payload.get("text_embedding_profile"),
                    vision_embedding_profile=result.payload.get("vision_embedding_profile"),
                )
            ):
                kept.append(result)
        return kept

    def _matching_paths(
        self,
        path_prefix: str,
        root_id: str | None,
    ) -> list[str] | None:
        if not path_prefix:
            return None
        return sorted(
            self.manifest.matching_paths(
                self.settings.workspace_id,
                path_prefix,
                root_id=root_id,
            )
        )


def _filter_path_prefix(
    results: list[SearchResult],
    path_prefix: str | None,
) -> list[SearchResult]:
    if not path_prefix:
        return results
    return [
        result
        for result in results
        if _path_has_prefix(result.relative_path, path_prefix)
    ]


def _path_has_prefix(relative_path: str, path_prefix: str) -> bool:
    normalized_path = relative_path.replace("\\", "/").strip("/").lower()
    normalized_prefix = path_prefix.lower()
    return normalized_path == normalized_prefix or normalized_path.startswith(
        f"{normalized_prefix}/"
    )


def _rerank_table_results(query: str, results: list[SearchResult]) -> list[SearchResult]:
    if not _looks_like_table_query(query):
        return results
    reranked = [
        replace(result, score=result.score + _table_score_boost(result))
        for result in results
    ]
    reranked.sort(key=lambda item: item.score, reverse=True)
    return reranked


def _rerank_text_results(query: str, results: list[SearchResult]) -> list[SearchResult]:
    query_terms = _query_terms(query)
    if len(query_terms) < 2:
        return results
    reranked = [
        replace(result, score=result.score + _text_score_boost(query_terms, result))
        for result in results
    ]
    reranked.sort(key=lambda item: item.score, reverse=True)
    return reranked


def _query_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for term in re.findall(r"[A-Za-z0-9가-힣]+", text.lower()):
        if len(term) >= 2:
            terms.add(term)
        terms.update(char for char in term if "가" <= char <= "힣")
    return terms


def _text_score_boost(query_terms: set[str], result: SearchResult) -> float:
    haystack_terms = _query_terms(
        " ".join(
            [
                result.relative_path.replace("_", " ").replace("-", " "),
                result.snippet,
            ]
        )
    )
    if not haystack_terms:
        return 0.0
    overlap = len(query_terms & haystack_terms) / len(query_terms)
    if overlap == 0:
        return 0.0
    unit_boost = 0.0
    max_boost = 0.18
    if result.unit_type == "pdf_ocr_text":
        unit_boost = 0.03
    elif result.unit_type == "document":
        unit_boost = 0.04
        max_boost = 0.30
    elif result.modality == "image":
        unit_boost = 0.06
        max_boost = 0.40
    elif result.unit_type in {"page", "chunk", "pdf_visual_caption"}:
        unit_boost = 0.03
        max_boost = 0.28
    return min(max_boost, overlap * max_boost) + unit_boost


def _looks_like_table_query(query: str) -> bool:
    terms = {term.strip(".,:;()[]{}").lower() for term in query.split()}
    return bool(
        terms
        & {
            "table",
            "row",
            "rows",
            "column",
            "columns",
            "cell",
            "cells",
            "metric",
            "score",
            "count",
            "status",
            "owner",
            "p50",
            "p95",
            "p99",
        }
    )


def _table_score_boost(result: SearchResult) -> float:
    if result.unit_type == "pdf_table" or result.payload.get("table_no") is not None:
        return 0.18
    if result.relative_path.lower().endswith(".pdf"):
        return 0.02
    return 0.0
