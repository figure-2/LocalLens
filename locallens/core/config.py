from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(".locallens")
    workspace_id: str = "default"
    collection_name: str = "locallens_units"
    qdrant_path_name: str = "qdrant"
    qdrant_url: str | None = None
    qdrant_timeout_seconds: float = 60.0
    manifest_name: str = "manifest.db"
    cache_name: str = "cache"
    text_vector_name: str = "text_dense_v1"
    vision_vector_name: str = "vision_dense_v1"
    text_dimension: int = 64
    vision_dimension: int = 64
    chunk_size: int = 1000
    chunk_overlap: int = 150
    max_file_size_bytes: int = 25 * 1024 * 1024
    embedding_backend: str = "hash"
    text_embedding_backend: str = "hash"
    vision_embedding_backend: str = "hash"
    text_model_name: str = "intfloat/multilingual-e5-small"
    vision_model_name: str = "google/siglip-base-patch16-224"
    model_cache_dir: str = ""
    model_local_files_only: bool = False
    release_evidence_mode: bool = False
    hf_hub_offline: bool = False
    transformers_offline: bool = False
    text_embedding_profile: str = "hash:64"
    vision_embedding_profile: str = "hash:64"
    rerank_mode: str = "off"
    kocr_query_normalization_mode: str = "off"
    follow_symlinks: bool = False
    pdf_visual_mode: str = "off"
    pdf_ocr_mode: str = "off"
    pdf_ocr_lang: str = "eng"
    tesseract_cmd: str = "tesseract"
    tessdata_dir: str = ""
    tesseract_psm: str = ""
    pdf_table_mode: str = "off"
    pdf_ocr_table_cache_mode: str = "off"
    pdf_vlm_mode: str = "off"
    pdf_vlm_model_name: str = ""
    pdf_vlm_prompt_version: str = "visual-caption-v1"
    pdf_vlm_api_base_url: str = ""
    pdf_vlm_api_key_env: str = "CLOVA_STUDIO_API_KEY"
    pdf_vlm_timeout_seconds: float = 30.0
    pdf_vlm_max_tokens: int = 256

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / self.qdrant_path_name

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / self.manifest_name

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / self.cache_name

    @classmethod
    def from_env(cls) -> "Settings":
        shared_backend = os.getenv("LOCALLENS_EMBEDDING_BACKEND", "hash")
        text_backend = os.getenv(
            "LOCALLENS_TEXT_EMBEDDING_BACKEND",
            _default_text_backend(shared_backend),
        )
        vision_backend = os.getenv(
            "LOCALLENS_VISION_EMBEDDING_BACKEND",
            _default_vision_backend(shared_backend),
        )
        return cls(
            data_dir=Path(os.getenv("LOCALLENS_DATA_DIR", ".locallens")),
            workspace_id=os.getenv("LOCALLENS_WORKSPACE_ID", "default"),
            qdrant_url=os.getenv("LOCALLENS_QDRANT_URL") or None,
            qdrant_timeout_seconds=float(
                os.getenv(
                    "LOCALLENS_QDRANT_TIMEOUT_SECONDS",
                    cls.qdrant_timeout_seconds,
                )
            ),
            embedding_backend=shared_backend,
            text_embedding_backend=text_backend,
            vision_embedding_backend=vision_backend,
            text_model_name=os.getenv(
                "LOCALLENS_TEXT_MODEL_NAME", cls.text_model_name
            ),
            vision_model_name=os.getenv(
                "LOCALLENS_VISION_MODEL_NAME", cls.vision_model_name
            ),
            model_cache_dir=os.getenv("LOCALLENS_MODEL_CACHE_DIR", ""),
            model_local_files_only=_env_bool("LOCALLENS_MODEL_LOCAL_FILES_ONLY")
            or _env_bool("HF_HUB_OFFLINE")
            or _env_bool("TRANSFORMERS_OFFLINE"),
            release_evidence_mode=_env_bool("LOCALLENS_RELEASE_EVIDENCE_MODE"),
            hf_hub_offline=_env_bool("HF_HUB_OFFLINE"),
            transformers_offline=_env_bool("TRANSFORMERS_OFFLINE"),
            rerank_mode=os.getenv("LOCALLENS_RERANK_MODE", cls.rerank_mode),
            kocr_query_normalization_mode=os.getenv(
                "LOCALLENS_KOCR_QUERY_NORMALIZATION_MODE",
                cls.kocr_query_normalization_mode,
            ),
            pdf_visual_mode=os.getenv("LOCALLENS_PDF_VISUAL_MODE", cls.pdf_visual_mode),
            pdf_ocr_mode=os.getenv("LOCALLENS_PDF_OCR_MODE", cls.pdf_ocr_mode),
            pdf_ocr_lang=os.getenv("LOCALLENS_PDF_OCR_LANG", cls.pdf_ocr_lang),
            tesseract_cmd=os.getenv("LOCALLENS_TESSERACT_CMD", cls.tesseract_cmd),
            tessdata_dir=os.getenv("LOCALLENS_TESSDATA_DIR", cls.tessdata_dir),
            tesseract_psm=os.getenv("LOCALLENS_TESSERACT_PSM", cls.tesseract_psm),
            pdf_table_mode=os.getenv("LOCALLENS_PDF_TABLE_MODE", cls.pdf_table_mode),
            pdf_ocr_table_cache_mode=os.getenv(
                "LOCALLENS_PDF_OCR_TABLE_CACHE_MODE",
                cls.pdf_ocr_table_cache_mode,
            ),
            pdf_vlm_mode=os.getenv("LOCALLENS_PDF_VLM_MODE", cls.pdf_vlm_mode),
            pdf_vlm_model_name=os.getenv(
                "LOCALLENS_PDF_VLM_MODEL_NAME", cls.pdf_vlm_model_name
            ),
            pdf_vlm_prompt_version=os.getenv(
                "LOCALLENS_PDF_VLM_PROMPT_VERSION", cls.pdf_vlm_prompt_version
            ),
            pdf_vlm_api_base_url=os.getenv(
                "LOCALLENS_PDF_VLM_API_BASE_URL", cls.pdf_vlm_api_base_url
            ),
            pdf_vlm_api_key_env=os.getenv(
                "LOCALLENS_PDF_VLM_API_KEY_ENV", cls.pdf_vlm_api_key_env
            ),
            pdf_vlm_timeout_seconds=float(
                os.getenv(
                    "LOCALLENS_PDF_VLM_TIMEOUT_SECONDS",
                    cls.pdf_vlm_timeout_seconds,
                )
            ),
            pdf_vlm_max_tokens=int(
                os.getenv("LOCALLENS_PDF_VLM_MAX_TOKENS", cls.pdf_vlm_max_tokens)
            ),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.qdrant_url:
            self.qdrant_path.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def validate_release_model_loading(self) -> None:
        if not self.release_evidence_mode:
            return
        if self.text_embedding_backend != "sentence-transformers" and self.vision_embedding_backend != "transformers":
            return
        if not self.model_local_files_only:
            raise ValueError(
                "Release evidence model loading requires LOCALLENS_MODEL_LOCAL_FILES_ONLY=1."
            )
        if not self.model_cache_dir:
            raise ValueError(
                "Release evidence model loading requires LOCALLENS_MODEL_CACHE_DIR."
            )
        if not self.hf_hub_offline or not self.transformers_offline:
            raise ValueError(
                "Release evidence model loading requires HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1."
            )

    def validate_optional_local_model_loading(self, candidate_name: str) -> None:
        if not candidate_name:
            raise ValueError("Optional local model loading requires an explicit candidate name.")
        if not self.model_local_files_only:
            raise ValueError(
                "Optional local model loading requires LOCALLENS_MODEL_LOCAL_FILES_ONLY=1."
            )
        if not self.model_cache_dir:
            raise ValueError(
                "Optional local model loading requires LOCALLENS_MODEL_CACHE_DIR."
            )
        if not self.hf_hub_offline or not self.transformers_offline:
            raise ValueError(
                "Optional local model loading requires HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1."
            )


def test_settings() -> Settings:
    return Settings(data_dir=Path(":memory:"), embedding_backend="hash")


def _default_text_backend(shared_backend: str) -> str:
    if shared_backend in {"real", "models", "sentence-transformers"}:
        return "sentence-transformers"
    return "hash"


def _default_vision_backend(shared_backend: str) -> str:
    if shared_backend in {"real", "models", "transformers"}:
        return "transformers"
    return "hash"


def _env_bool(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}
