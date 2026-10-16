from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from locallens.ax.e2e_scenarios import MOCK_E2E_SCENARIO
from locallens.ax.metadata import metadata_repository
from locallens.ax.retriever import list_documents
from locallens.ax.retriever import search_documents
from locallens.core.config import Settings
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.search_service import SearchService


class SearchResult(BaseModel):
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


class SearchResponse(BaseModel):
    query: str
    user_id: str
    results: list[SearchResult]


class AgentSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    user_id: str = "employee_hr"
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, Any] = Field(default_factory=dict)


class AgentSearchResponse(BaseModel):
    tool_name: str
    tool_input: dict[str, Any]
    evidence_packets: list[SearchResult]
    answer_ready_context: dict[str, Any]
    mock_answer: str
    claim_boundary: str


class FeedbackRequest(BaseModel):
    query: str
    document_id: str
    chunk_id: str
    user_id: str = "employee_hr"
    rating: int = Field(ge=1, le=5)
    note: str = ""


class LocalSyncRequest(BaseModel):
    root_path: str = Field(min_length=1)
    workspace_id: str = "demo-local"
    data_dir: str = ".locallens/api-local-demo"
    pdf_visual_mode: str = "off"
    pdf_ocr_mode: str = "off"
    pdf_table_mode: str = "off"
    pdf_vlm_mode: str = "off"
    pdf_vlm_model_name: str = ""
    max_progress_events: int = Field(default=25, ge=1, le=200)


class LocalSyncResponse(BaseModel):
    status: str
    root_path: str
    workspace_id: str
    report: dict[str, Any]
    progress_events: list[dict[str, Any]]
    search_surface: str
    claim_boundary: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="LocalLens AX API",
        version="0.1.0",
        description="LocalLens multimodal search demo API with an AX workspace extension.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5174",
            "http://127.0.0.1:5175",
            "http://127.0.0.1:5176",
            "http://127.0.0.1:5177",
            "http://127.0.0.1:5178",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://localhost:5176",
            "http://localhost:5177",
            "http://localhost:5178",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": f"{metadata_repository.backend_name}-e2e"}

    @app.get("/api/v1/demo/scenario")
    async def demo_scenario() -> dict[str, Any]:
        return MOCK_E2E_SCENARIO

    @app.post("/api/v1/local/sync", response_model=LocalSyncResponse)
    async def local_sync(request: LocalSyncRequest) -> LocalSyncResponse:
        root_path = Path(request.root_path).expanduser()
        if not root_path.is_absolute():
            root_path = Path.cwd() / root_path
        root_path = root_path.resolve()
        if not root_path.exists() or not root_path.is_dir():
            raise HTTPException(
                status_code=400,
                detail="root_path must be an existing local directory.",
            )

        settings = _settings_from_env_with_overrides(
            data_dir=request.data_dir,
            workspace_id=request.workspace_id,
            pdf_visual_mode=request.pdf_visual_mode,
            pdf_ocr_mode=request.pdf_ocr_mode,
            pdf_table_mode=request.pdf_table_mode,
            pdf_vlm_mode=request.pdf_vlm_mode,
            pdf_vlm_model_name=request.pdf_vlm_model_name,
        )
        progress_events: list[dict[str, Any]] = []

        def capture_progress(progress) -> bool:
            progress_events.append(asdict(progress))
            if len(progress_events) > request.max_progress_events:
                del progress_events[0 : len(progress_events) - request.max_progress_events]
            return True

        report = SyncService(settings).sync_folder(
            root_path,
            progress_callback=capture_progress,
        )
        return LocalSyncResponse(
            status="completed" if not report.cancelled else "cancelled",
            root_path=str(root_path),
            workspace_id=request.workspace_id,
            report=asdict(report),
            progress_events=progress_events,
            search_surface="core_local_index",
            claim_boundary=(
                "This endpoint indexes a local folder into the LocalLens core index. "
                "It does not claim production operation or real-data benchmark accuracy."
            ),
        )

    @app.get("/api/v1/documents")
    async def documents(user_id: str = "employee_hr") -> dict[str, Any]:
        return {
            "user_id": user_id,
            "documents": [
                doc.public_dict()
                for doc in metadata_repository.list_visible_documents(user_id)
            ],
            "source": f"{metadata_repository.backend_name}_metadata_repository",
        }

    @app.get("/api/v1/search", response_model=SearchResponse)
    async def search(
        q: str = Query(min_length=1),
        user_id: str = "employee_hr",
        top_k: int = Query(default=5, ge=1, le=20),
        department_id: str | None = None,
        document_type: str | None = None,
        modality: str | None = None,
    ) -> SearchResponse:
        filters = {
            key: value
            for key, value in {
                "department_id": department_id,
                "document_type": document_type,
                "modality": modality,
            }.items()
            if value
        }
        results = [
            SearchResult(**packet.to_dict())
            for packet in search_documents(
                q,
                user_id=user_id,
                top_k=top_k,
                filters=filters,
            )
        ]
        metadata_repository.record_search(
            user_id=user_id,
            query=q,
            filters=filters,
            result_count=len(results),
        )
        return SearchResponse(query=q, user_id=user_id, results=results)

    @app.get("/api/v1/local/search", response_model=SearchResponse)
    async def local_search(
        q: str = Query(min_length=1),
        user_id: str = "demo-local",
        workspace_id: str = "demo-local",
        data_dir: str = ".locallens/api-local-demo",
        top_k: int = Query(default=5, ge=1, le=20),
        modality: str | None = None,
        unit_type: str | None = None,
        ext: str | None = None,
        path_prefix: str | None = None,
    ) -> SearchResponse:
        settings = _settings_from_env_with_overrides(
            data_dir=data_dir,
            workspace_id=workspace_id,
        )
        service = SearchService(settings)
        try:
            try:
                core_results = service.search(
                    q,
                    top_k=top_k,
                    modality=modality,
                    unit_type=unit_type,
                    ext=ext,
                    path_prefix=path_prefix,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            results = [_local_result_to_packet(result) for result in core_results]
        finally:
            service.store.close()
        return SearchResponse(query=q, user_id=user_id, results=results)

    @app.post(
        "/api/v1/agent/tools/document-search",
        response_model=AgentSearchResponse,
    )
    async def agent_document_search(request: AgentSearchRequest) -> AgentSearchResponse:
        packets = [
            SearchResult(**packet.to_dict())
            for packet in search_documents(
                request.query,
                user_id=request.user_id,
                top_k=request.top_k,
                filters=request.filters,
            )
        ]
        answer_ready_context = {
            "query": request.query,
            "user_id": request.user_id,
            "source_refs": [packet.source_ref for packet in packets],
            "snippets": [
                {
                    "title": packet.title,
                    "source_ref": packet.source_ref,
                    "snippet": packet.snippet,
                    "match_type": packet.match_type,
                }
                for packet in packets
            ],
            "instruction": (
                "Use only the returned evidence packets. If the evidence is not "
                "sufficient, say that the document evidence is insufficient."
            ),
        }
        return AgentSearchResponse(
            tool_name="search_documents",
            tool_input={
                "query": request.query,
                "user_id": request.user_id,
                "top_k": request.top_k,
                "filters": request.filters,
            },
            evidence_packets=packets,
            answer_ready_context=answer_ready_context,
            mock_answer=_compose_mock_answer(request.query, packets),
            claim_boundary="This mock tool returns evidence packets only. It does not claim final answer correctness.",
        )

    @app.post("/api/v1/search/feedback")
    async def feedback(request: FeedbackRequest) -> dict[str, Any]:
        event = metadata_repository.record_feedback(request.model_dump())
        return {
            "status": "accepted",
            "feedback": event,
            "storage": metadata_repository.backend_name,
        }

    return app


def _compose_mock_answer(query: str, packets: list[SearchResult]) -> str:
    if not packets:
        return (
            f"'{query}'에 대해 사용할 수 있는 문서 근거를 찾지 못했습니다. "
            "권한 범위나 검색어를 다시 확인해야 합니다."
        )
    primary = packets[0]
    return (
        f"'{query}'에 대한 1차 근거는 '{primary.title}'의 "
        f"{primary.source_ref}입니다. 핵심 내용은 {primary.snippet} 입니다. "
        "이 답변은 mock composer가 evidence packet만 사용해 만든 시연용 답변입니다."
    )


def _local_result_to_packet(result) -> SearchResult:
    payload = result.payload or {}
    source_ref = _local_source_ref(result)
    relative_path = result.relative_path or "unknown"
    return SearchResult(
        document_id=str(payload.get("file_id") or relative_path),
        chunk_id=str(payload.get("unit_id") or f"{relative_path}:{result.unit_type}"),
        title=relative_path,
        snippet=result.snippet,
        source_ref=source_ref,
        page=result.page_no,
        modality=result.modality,
        score=result.score,
        keyword_score=0.0,
        semantic_score=result.score,
        match_type="local-semantic",
        department_id="local",
        document_type=str(payload.get("ext") or ""),
    )


def _local_source_ref(result) -> str:
    parts = [result.relative_path or "unknown"]
    if result.page_no is not None:
        parts.append(f"page={result.page_no}")
    if result.chunk_no is not None:
        parts.append(f"chunk={result.chunk_no}")
    image_no = result.payload.get("image_no") if result.payload else None
    if image_no is not None:
        parts.append(f"image={image_no}")
    unit_type = result.unit_type
    if unit_type:
        parts.append(f"type={unit_type}")
    return "#".join([parts[0], "&".join(parts[1:])]) if len(parts) > 1 else parts[0]


def _settings_from_env_with_overrides(
    *,
    data_dir: str,
    workspace_id: str,
    pdf_visual_mode: str | None = None,
    pdf_ocr_mode: str | None = None,
    pdf_table_mode: str | None = None,
    pdf_vlm_mode: str | None = None,
    pdf_vlm_model_name: str | None = None,
) -> Settings:
    base = Settings.from_env()
    return Settings(
        data_dir=Path(data_dir),
        workspace_id=workspace_id,
        collection_name=base.collection_name,
        qdrant_path_name=base.qdrant_path_name,
        qdrant_url=base.qdrant_url,
        qdrant_timeout_seconds=base.qdrant_timeout_seconds,
        manifest_name=base.manifest_name,
        cache_name=base.cache_name,
        text_vector_name=base.text_vector_name,
        vision_vector_name=base.vision_vector_name,
        text_dimension=base.text_dimension,
        vision_dimension=base.vision_dimension,
        chunk_size=base.chunk_size,
        chunk_overlap=base.chunk_overlap,
        max_file_size_bytes=base.max_file_size_bytes,
        embedding_backend=base.embedding_backend,
        text_embedding_backend=base.text_embedding_backend,
        vision_embedding_backend=base.vision_embedding_backend,
        text_model_name=base.text_model_name,
        vision_model_name=base.vision_model_name,
        model_cache_dir=base.model_cache_dir,
        model_local_files_only=base.model_local_files_only,
        release_evidence_mode=base.release_evidence_mode,
        hf_hub_offline=base.hf_hub_offline,
        transformers_offline=base.transformers_offline,
        text_embedding_profile=base.text_embedding_profile,
        vision_embedding_profile=base.vision_embedding_profile,
        rerank_mode=base.rerank_mode,
        kocr_query_normalization_mode=base.kocr_query_normalization_mode,
        follow_symlinks=base.follow_symlinks,
        pdf_visual_mode=pdf_visual_mode if pdf_visual_mode is not None else base.pdf_visual_mode,
        pdf_ocr_mode=pdf_ocr_mode if pdf_ocr_mode is not None else base.pdf_ocr_mode,
        pdf_ocr_lang=base.pdf_ocr_lang,
        tesseract_cmd=base.tesseract_cmd,
        tessdata_dir=base.tessdata_dir,
        tesseract_psm=base.tesseract_psm,
        pdf_table_mode=pdf_table_mode if pdf_table_mode is not None else base.pdf_table_mode,
        pdf_ocr_table_cache_mode=base.pdf_ocr_table_cache_mode,
        pdf_vlm_mode=pdf_vlm_mode if pdf_vlm_mode is not None else base.pdf_vlm_mode,
        pdf_vlm_model_name=pdf_vlm_model_name if pdf_vlm_model_name is not None else base.pdf_vlm_model_name,
        pdf_vlm_prompt_version=base.pdf_vlm_prompt_version,
        pdf_vlm_api_base_url=base.pdf_vlm_api_base_url,
        pdf_vlm_api_key_env=base.pdf_vlm_api_key_env,
        pdf_vlm_timeout_seconds=base.pdf_vlm_timeout_seconds,
        pdf_vlm_max_tokens=base.pdf_vlm_max_tokens,
    )


app = create_app()
