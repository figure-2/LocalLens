from __future__ import annotations

from pathlib import Path

import pytest

from locallens.core.config import Settings
from locallens.retrieval.korean_query_normalizer import (
    KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL,
    normalize_korean_ocr_query,
)
from locallens.retrieval.search_service import SearchService


def test_kocr_query_normalizer_defaults_to_unchanged():
    assert normalize_korean_ocr_query("local search archive 27") == "local search archive 27"


def test_kocr_query_normalizer_alias_backfills_korean_terms():
    normalized = normalize_korean_ocr_query(
        "local search archive 27 local",
        KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL,
    )

    assert normalized == "local search archive 27 local 로컬 검색 보관함 이십칠"


def test_kocr_query_normalizer_keeps_korean_only_query_unchanged():
    query = "배송 확인 완료 상자 번호 칠십삼"

    assert normalize_korean_ocr_query(query, KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL) == query


def test_kocr_query_normalizer_rejects_unsupported_mode_without_leaking():
    mode = "C:" + "\\Users\\name\\mode"

    with pytest.raises(ValueError) as exc:
        normalize_korean_ocr_query("local search", mode)

    assert str(exc.value) == "Unsupported KOCR query normalization mode"
    assert mode not in str(exc.value)


def test_settings_reads_kocr_query_normalization_mode_from_env(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("LOCALLENS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(
        "LOCALLENS_KOCR_QUERY_NORMALIZATION_MODE",
        KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL,
    )

    assert (
        Settings.from_env().kocr_query_normalization_mode
        == KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL
    )


def test_search_service_applies_kocr_normalizer_to_text_query_only(
    monkeypatch,
    tmp_path: Path,
):
    captured: dict[str, list[str]] = {"text": [], "vision": []}

    class FakeTextEmbedder:
        dimension = 64
        profile = "hash:64"

        def __init__(self, settings):
            pass

        def embed_query(self, query):
            captured["text"].append(query)
            return [0.0] * 64

    class FakeVisionEmbedder:
        dimension = 64
        profile = "hash:64"

        def __init__(self, settings):
            pass

        def embed_query(self, query):
            captured["vision"].append(query)
            return [0.0] * 64

    class FakeStore:
        settings = None

        def search(self, *_args, **_kwargs):
            return []

    class FakeManifest:
        def matching_paths(self, *_args, **_kwargs):
            return []

        def has_unit(self, *_args, **_kwargs):
            return True

    monkeypatch.setattr(
        "locallens.retrieval.search_service.TextEmbedder",
        FakeTextEmbedder,
    )
    monkeypatch.setattr(
        "locallens.retrieval.search_service.VisionEmbedder",
        FakeVisionEmbedder,
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        kocr_query_normalization_mode=KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL,
    )
    service = SearchService(settings, store=FakeStore(), manifest=FakeManifest())

    service.search("local search archive 27", modality="text")
    service.search("local search archive 27", modality="image")

    assert captured["text"] == ["local search archive 27 로컬 검색 보관함 이십칠"]
    assert captured["vision"] == ["local search archive 27"]
