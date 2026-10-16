from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from locallens.core.config import Settings
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.search_service import (
    SearchService,
    _rerank_table_results,
    _rerank_text_results,
)
from locallens.core.types import SearchResult


class FailingReranker:
    profile = "test:fail"

    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        raise RuntimeError("rerank failed")


pytest.importorskip("qdrant_client")


def test_sync_and_search_returns_relative_path(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    (source / "roadmap.md").write_text("planning roadmap architecture")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)

    report = SyncService(settings, store=store, manifest=manifest).sync_folder(source)
    results = SearchService(settings, store=store, manifest=manifest).search("planning", top_k=3)

    assert report.added == 1
    assert results
    assert results[0].relative_path == "roadmap.md"
    assert not Path(results[0].relative_path).is_absolute()
    assert results[0].chunk_no is None or isinstance(results[0].chunk_no, int)
    assert results[0].embedding_profile == "hash:64"


def test_delete_or_reindex_removes_stale_vectors(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "old.txt"
    target.write_text("old content")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    sync.sync_folder(source)
    target.unlink()
    report = sync.sync_folder(source)

    assert report.deleted == 1
    assert store.count() == 0


def test_profile_change_forces_reindex(tmp_path: Path, monkeypatch):
    class FakeTextEmbedder:
        profile = "profile-a"
        dimension = 64

        def __init__(self, settings):
            pass

        def embed_document(self, text):
            return [0.1] * 64

    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    (source / "same.txt").write_text("same content")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    monkeypatch.setattr(
        "locallens.indexing.sync_service.TextEmbedder", FakeTextEmbedder
    )

    first = SyncService(settings, store=store, manifest=manifest).sync_folder(source)
    FakeTextEmbedder.profile = "profile-b"
    second = SyncService(settings, store=store, manifest=manifest).sync_folder(source)

    assert first.added == 1
    assert second.updated == 1


def test_failed_update_keeps_existing_points(tmp_path: Path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "stable.txt"
    target.write_text("stable old content")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    sync.sync_folder(source)
    old_count = store.count()
    target.write_text("new content that fails during update")

    def fail_upsert(*args, **kwargs):
        raise RuntimeError("upsert failed")

    monkeypatch.setattr(store, "upsert_units", fail_upsert)
    report = sync.sync_folder(source)

    assert report.failed == 1
    assert report.failures[0].relative_path == "stable.txt"
    assert report.failures[0].error_type == "RuntimeError"
    assert report.updated == 0
    assert store.count() == old_count


def test_manifest_write_failure_preserves_existing_index(tmp_path: Path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "stable.txt"
    target.write_text("original searchable content")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    sync.sync_folder(source)
    old_count = store.count()
    old_hashes = {
        record["payload"]["content_hash"] for record in store.payload_records()
    }
    target.write_text("changed content after manifest failure")

    def fail_manifest_write(*args, **kwargs):
        raise RuntimeError("manifest write failed")

    monkeypatch.setattr(manifest, "upsert_file", fail_manifest_write)
    report = sync.sync_folder(source)
    results = SearchService(settings, store=store, manifest=manifest).search("original")

    assert report.failed == 1
    assert report.updated == 0
    assert store.count() == old_count
    assert {
        record["payload"]["content_hash"] for record in store.payload_records()
    } == old_hashes
    assert results
    assert results[0].relative_path == "stable.txt"


def test_sync_flow_reports_added_skipped_updated_deleted_and_excluded(
    tmp_path: Path,
):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    primary = source / "primary.txt"
    secondary = source / "secondary.md"
    primary.write_text("primary version one")
    (source / ".env").write_text("TOKEN=value")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    first = sync.sync_folder(source)
    second = sync.sync_folder(source)
    primary.write_text("primary version two")
    secondary.write_text("secondary release notes")
    third = sync.sync_folder(source)
    secondary.unlink()
    fourth = sync.sync_folder(source)

    assert first.added == 1
    assert first.excluded == 1
    assert second.skipped == 1
    assert second.excluded == 1
    assert third.added == 1
    assert third.updated == 1
    assert third.deleted == 0
    assert third.excluded == 1
    assert fourth.deleted == 1
    assert fourth.skipped == 1
    assert fourth.excluded == 1
    assert fourth.failed == 0
    assert store.count() == 2


def test_sync_folder_emits_progress_events(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    (source / "one.txt").write_text("one")
    (source / "two.md").write_text("two")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    events = []

    report = SyncService(settings, store=store, manifest=manifest).sync_folder(
        source,
        progress_callback=events.append,
    )

    assert report.added == 2
    assert events[0].phase == "scan"
    assert events[0].total == 2
    assert {"extracting", "embedding", "upserting"}.issubset(
        {event.phase for event in events}
    )
    assert {event.relative_path for event in events if event.phase == "indexed"} == {
        "one.txt",
        "two.md",
    }
    assert events[-1].phase == "complete"
    assert events[-1].processed == 2


def test_sync_progress_callback_errors_do_not_fail_sync(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    (source / "one.txt").write_text("one")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)

    def fail_callback(progress):
        raise RuntimeError("progress failed")

    report = SyncService(settings, store=store, manifest=manifest).sync_folder(
        source,
        progress_callback=fail_callback,
    )

    assert report.added == 1
    assert report.failed == 0


def test_sync_progress_callback_can_cancel_indexing(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    (source / "one.txt").write_text("one")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    events = []

    def cancel_on_extracting(progress):
        events.append(progress.phase)
        return progress.phase != "extracting"

    report = SyncService(settings, store=store, manifest=manifest).sync_folder(
        source,
        progress_callback=cancel_on_extracting,
    )

    assert report.cancelled is True
    assert report.added == 0
    assert store.count() == 0
    assert "extracting" in events


def test_sync_progress_callback_can_cancel_during_embedding(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    (source / "one.txt").write_text("one")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    events = []

    def cancel_on_embedding_unit(progress):
        events.append(progress)
        if progress.phase == "embedding" and progress.unit_total:
            return False
        return True

    report = SyncService(settings, store=store, manifest=manifest).sync_folder(
        source,
        progress_callback=cancel_on_embedding_unit,
    )

    assert report.cancelled is True
    assert report.added == 0
    assert store.count() == 0
    assert any(
        event.phase == "embedding" and event.unit_total
        for event in events
    )


def test_secret_like_content_is_redacted_from_search_results(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    sample = "api_" + "key=abcd1234" + "secret project notes"
    (source / "notes.md").write_text(sample)
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)

    SyncService(settings, store=store, manifest=manifest).sync_folder(source)
    results = SearchService(settings, store=store, manifest=manifest).search("project")

    assert results
    assert "abcd1234" + "secret" not in results[0].snippet
    assert "[REDACTED]" in results[0].snippet


def test_compound_secret_content_is_redacted_from_search_results(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    first_sample = "OPENAI_" + "API_KEY=sk-" + "abcdef123456"
    second_sample = "access_" + "token: tok_" + "abcdef123456"
    source.joinpath("notes.md").write_text(
        f"{first_sample} {second_sample} notes"
    )
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)

    SyncService(settings, store=store, manifest=manifest).sync_folder(source)
    results = SearchService(settings, store=store, manifest=manifest).search("notes")

    assert results
    assert "sk-" + "abcdef123456" not in results[0].snippet
    assert "tok_" + "abcdef123456" not in results[0].snippet
    assert results[0].snippet.count("[REDACTED]") >= 2


def test_search_drops_units_missing_from_manifest(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    (source / "unit.md").write_text("unit manifest validation target")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)

    SyncService(settings, store=store, manifest=manifest).sync_folder(source)
    with sqlite3.connect(settings.manifest_path) as conn:
        conn.execute("DELETE FROM units")

    results = SearchService(settings, store=store, manifest=manifest).search("unit")

    assert results == []


def test_same_root_can_be_indexed_by_multiple_workspaces(tmp_path: Path):
    source = tmp_path / "docs"
    source.mkdir()
    (source / "shared.md").write_text("workspace isolation target")
    data_dir = tmp_path / "data"
    first_settings = Settings(data_dir=data_dir, workspace_id="workspace-a")
    second_settings = Settings(data_dir=data_dir, workspace_id="workspace-b")
    store = QdrantStore(first_settings, in_memory=True)
    manifest = ManifestStore(first_settings.manifest_path)

    SyncService(first_settings, store=store, manifest=manifest).sync_folder(source)
    SyncService(second_settings, store=store, manifest=manifest).sync_folder(source)

    first_results = SearchService(first_settings, store=store, manifest=manifest).search(
        "workspace", top_k=5
    )
    second_results = SearchService(second_settings, store=store, manifest=manifest).search(
        "workspace", top_k=5
    )

    assert store.count() == 4
    assert first_results
    assert second_results
    assert {item.payload["workspace_id"] for item in first_results} == {"workspace-a"}
    assert {item.payload["workspace_id"] for item in second_results} == {"workspace-b"}


def test_search_filters_by_manifest_backed_path_prefix(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    nested = source / "Team"
    other = source / "archive"
    nested.mkdir()
    other.mkdir()
    (nested / "target.md").write_text("shared path prefix target")
    (other / "target.md").write_text("shared path prefix target")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)

    SyncService(settings, store=store, manifest=manifest).sync_folder(source)
    results = SearchService(settings, store=store, manifest=manifest).search(
        "shared path prefix target",
        top_k=5,
        path_prefix="team",
    )

    assert results
    assert {item.relative_path for item in results} == {"Team/target.md"}


def test_search_reranker_failure_preserves_current_result_order(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    (source / "manifest_notes.md").write_text(
        "manifest stale filtering named vectors"
    )
    (source / "generic.md").write_text("general indexing notes")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)

    SyncService(settings, store=store, manifest=manifest).sync_folder(source)
    baseline = SearchService(settings, store=store, manifest=manifest).search(
        "manifest stale filtering named vectors",
        top_k=5,
    )
    fallback = SearchService(
        settings,
        store=store,
        manifest=manifest,
        reranker=FailingReranker(),
    ).search(
        "manifest stale filtering named vectors",
        top_k=5,
    )

    assert fallback == baseline


def test_search_rejects_invalid_top_k_and_path_prefix(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    service = SearchService(settings, store=store, manifest=manifest)

    with pytest.raises(ValueError, match="Top K"):
        service.search("query", top_k=0)

    with pytest.raises(ValueError, match="Path prefix"):
        service.search("query", path_prefix="../outside")


def test_table_intent_query_boosts_pdf_table_units():
    generic_pdf = SearchResult(
        score=0.91,
        modality="text",
        relative_path="report.pdf",
        page_no=1,
        snippet="page text",
        unit_type="chunk",
    )
    table = SearchResult(
        score=0.80,
        modality="text",
        relative_path="report.pdf",
        page_no=1,
        snippet="row | status",
        unit_type="pdf_table",
        payload={"table_no": 0},
    )

    results = _rerank_table_results("status table rows", [generic_pdf, table])

    assert results[0].unit_type == "pdf_table"
    assert results[0].score > generic_pdf.score


def test_text_query_boosts_lexically_matching_text_results():
    generic = SearchResult(
        score=0.80,
        modality="text",
        relative_path="generic.md",
        page_no=None,
        snippet="general notes about indexing",
        unit_type="document",
    )
    target = SearchResult(
        score=0.78,
        modality="text",
        relative_path="manifest_stale_filter_en.md",
        page_no=None,
        snippet="manifest based stale result filtering with named text and vision vectors",
        unit_type="document",
    )

    results = _rerank_text_results(
        "manifest stale filtering named vectors",
        [generic, target],
    )

    assert results[0].relative_path == "manifest_stale_filter_en.md"


def test_text_query_gives_small_boost_to_ocr_text_units():
    page = SearchResult(
        score=0.82,
        modality="text",
        relative_path="scan.pdf",
        page_no=1,
        snippet="scanned receipt-like PDF fixture",
        unit_type="page",
    )
    ocr = SearchResult(
        score=0.80,
        modality="text",
        relative_path="scan.pdf",
        page_no=1,
        snippet="receipt total approved amount",
        unit_type="pdf_ocr_text",
        payload={"image_no": 0},
    )

    results = _rerank_text_results("receipt total amount", [page, ocr])

    assert results[0].unit_type == "pdf_ocr_text"


def test_text_query_does_not_boost_without_term_overlap():
    generic = SearchResult(
        score=0.82,
        modality="text",
        relative_path="scan.pdf",
        page_no=1,
        snippet="receipt total approved amount",
        unit_type="pdf_ocr_text",
        payload={"image_no": 0},
    )
    target = SearchResult(
        score=0.83,
        modality="text",
        relative_path="manifest.md",
        page_no=None,
        snippet="manifest based stale filtering",
        unit_type="document",
    )

    results = _rerank_text_results("completely unrelated phrase", [generic, target])

    assert results[0].relative_path == "manifest.md"


def test_text_query_matches_split_korean_ocr_syllables():
    generic = SearchResult(
        score=0.84,
        modality="text",
        relative_path="generic.pdf",
        page_no=1,
        snippet="일 반 문 서",
        unit_type="pdf_ocr_text",
    )
    target = SearchResult(
        score=0.82,
        modality="text",
        relative_path="delivery.pdf",
        page_no=1,
        snippet="배 송 확 인 완 료 상 자 번 호 칠 십 삼",
        unit_type="pdf_ocr_text",
    )

    results = _rerank_text_results("배송 확인 완료 상자 번호 칠십삼", [generic, target])

    assert results[0].relative_path == "delivery.pdf"


def test_non_table_query_keeps_original_score_order():
    generic_pdf = SearchResult(
        score=0.91,
        modality="text",
        relative_path="report.pdf",
        page_no=1,
        snippet="page text",
        unit_type="chunk",
    )
    table = SearchResult(
        score=0.80,
        modality="text",
        relative_path="report.pdf",
        page_no=1,
        snippet="row | status",
        unit_type="pdf_table",
        payload={"table_no": 0},
    )

    results = _rerank_table_results("project overview", [generic_pdf, table])

    assert results == [generic_pdf, table]
