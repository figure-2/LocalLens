from __future__ import annotations

from pathlib import Path

import pytest

from locallens.core.config import Settings
from locallens.core.types import SearchResult
from locallens.retrieval.rerank_service import (
    NoOpRerankService,
    apply_rerank_service,
    build_rerank_service,
)


class FailingRerankService:
    profile = "test:fail"

    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        raise RuntimeError("rerank failed")


def test_build_rerank_service_defaults_to_noop(tmp_path: Path):
    service = build_rerank_service(Settings(data_dir=tmp_path / "data"))

    assert isinstance(service, NoOpRerankService)
    assert service.profile == "off:no-op"


def test_settings_reads_rerank_mode_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALLENS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LOCALLENS_RERANK_MODE", "off")

    assert Settings.from_env().rerank_mode == "off"


def test_build_rerank_service_rejects_unsupported_mode(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", rerank_mode="image-key")

    with pytest.raises(ValueError, match="Unsupported rerank mode"):
        build_rerank_service(settings)


@pytest.mark.parametrize(
    "mode",
    [
        "golden:image_key",
        "expected_paths",
        "C:" + "\\Users\\name\\selected.png",
        "/Users/name/selected.png",
    ],
)
def test_build_rerank_service_rejects_label_and_path_modes_without_leaking(
    tmp_path: Path,
    mode: str,
):
    settings = Settings(data_dir=tmp_path / "data", rerank_mode=mode)

    with pytest.raises(ValueError) as exc:
        build_rerank_service(settings)

    message = str(exc.value)
    assert message == "Unsupported rerank mode"
    assert mode not in message


def test_noop_rerank_service_preserves_candidate_order():
    results = _results_in_search_order()

    reranked = NoOpRerankService().rerank("visual query", results)

    assert [item.relative_path for item in reranked] == [
        "first.png",
        "second.png",
        "third.png",
    ]
    assert [item.score for item in reranked] == [0.90, 0.80, 0.70]
    assert [item.payload for item in reranked] == [{}, {}, {}]
    assert reranked is not results


def test_noop_rerank_service_ignores_forbidden_payload_labels():
    results = _results_in_search_order()
    results[1].payload.update(
        {
            "golden": {"image_key": "red-camera"},
            "image_key": "red-camera",
            "expected_paths": ["first.png"],
            "absolute_path": "C:" + "\\Users\\name\\first.png",
        }
    )

    reranked = NoOpRerankService().rerank("visual query", results)

    assert [item.relative_path for item in reranked] == [
        "first.png",
        "second.png",
        "third.png",
    ]
    assert [item.score for item in reranked] == [0.90, 0.80, 0.70]


def test_failed_rerank_service_falls_back_to_candidate_order():
    results = _results_in_search_order()

    reranked = apply_rerank_service(
        "visual query",
        results,
        FailingRerankService(),
    )

    assert [item.relative_path for item in reranked] == [
        "first.png",
        "second.png",
        "third.png",
    ]
    assert [item.score for item in reranked] == [0.90, 0.80, 0.70]


def _results_in_search_order() -> list[SearchResult]:
    return [
        SearchResult(
            score=0.90,
            modality="image",
            relative_path="first.png",
            page_no=None,
            snippet="",
            unit_type="image",
        ),
        SearchResult(
            score=0.80,
            modality="image",
            relative_path="second.png",
            page_no=None,
            snippet="",
            unit_type="image",
        ),
        SearchResult(
            score=0.70,
            modality="image",
            relative_path="third.png",
            page_no=None,
            snippet="",
            unit_type="image",
        ),
    ]
