from __future__ import annotations

from pathlib import Path

import pytest

from locallens.core.config import Settings
from locallens.ingestion.fingerprint import content_hash, root_id_for_path
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService


pytest.importorskip("qdrant_client")


def test_manifest_cache_entries_are_owned_and_path_safe(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    manifest = ManifestStore(settings.manifest_path)

    _stage_cache(manifest, settings, blob_rel_path="product_cache/page.json")
    assert manifest.cache_entry_count() == 1
    assert manifest.cache_entry_count(state="staged") == 1

    assert manifest.commit_staged_cache_entries(
        settings.workspace_id,
        "root",
        "doc.txt",
        "content-v1",
    ) == 1
    assert manifest.cache_entry_count(state="committed") == 1

    with pytest.raises(ValueError, match="relative"):
        _stage_cache(
            manifest,
            settings,
            cache_key="unsafe",
            blob_rel_path="C:" + "/Users/example/cache.json",
        )


def test_sync_update_deletes_stale_committed_cache(tmp_path: Path):
    settings, source, target, store, manifest, sync, root_id = _synced_text_file(
        tmp_path
    )
    old_content_hash = _content_hash(manifest, settings, root_id)
    blob = _write_blob(settings, "product_cache/old.json")
    _stage_cache(
        manifest,
        settings,
        root_id=root_id,
        content_hash=old_content_hash,
        blob_rel_path="product_cache/old.json",
    )
    manifest.commit_staged_cache_entries(
        settings.workspace_id, root_id, "doc.txt", old_content_hash
    )

    target.write_text("version two")
    report = sync.sync_folder(source)

    assert report.updated == 1
    assert report.cache_entries_deleted == 1
    assert report.cache_stale_deleted == 1
    assert manifest.cache_entry_count() == 0
    assert not blob.exists()


def test_sync_success_commits_staged_cache_and_counts_written(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "doc.txt"
    target.write_text("version one")
    root_id = root_id_for_path(source)
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)
    blob = _write_blob(settings, "product_cache/new.json")
    _stage_cache(
        manifest,
        settings,
        root_id=root_id,
        content_hash=content_hash(target),
        blob_rel_path="product_cache/new.json",
    )

    report = sync.sync_folder(source)

    assert report.added == 1
    assert report.cache_entries_written == 1
    assert report.cache_entries_deleted == 0
    assert manifest.cache_entry_count(state="staged") == 0
    assert manifest.cache_entry_count(state="committed") == 1
    assert blob.exists()


def test_sync_delete_removes_cache_entries_and_blobs(tmp_path: Path):
    settings, source, target, store, manifest, sync, root_id = _synced_text_file(
        tmp_path
    )
    content_hash = _content_hash(manifest, settings, root_id)
    blob = _write_blob(settings, "product_cache/delete.json")
    _stage_cache(
        manifest,
        settings,
        root_id=root_id,
        content_hash=content_hash,
        blob_rel_path="product_cache/delete.json",
    )
    manifest.commit_staged_cache_entries(
        settings.workspace_id, root_id, "doc.txt", content_hash
    )

    target.unlink()
    report = sync.sync_folder(source)

    assert report.deleted == 1
    assert report.cache_entries_deleted == 1
    assert report.cache_stale_deleted == 1
    assert manifest.cache_entry_count() == 0
    assert not blob.exists()
    assert store.count() == 0


def test_sync_cancel_discards_staged_cache_and_preserves_committed(
    tmp_path: Path,
):
    settings, source, target, _store, manifest, sync, root_id = _synced_text_file(
        tmp_path
    )
    content_hash = _content_hash(manifest, settings, root_id)
    committed = _write_blob(settings, "product_cache/committed.json")
    staged = _write_blob(settings, "product_cache/staged.json")
    _stage_cache(
        manifest,
        settings,
        root_id=root_id,
        cache_key="committed",
        content_hash=content_hash,
        blob_rel_path="product_cache/committed.json",
    )
    manifest.commit_staged_cache_entries(
        settings.workspace_id, root_id, "doc.txt", content_hash
    )
    _stage_cache(
        manifest,
        settings,
        root_id=root_id,
        cache_key="staged",
        blob_rel_path="product_cache/staged.json",
    )
    target.write_text("version two")

    def cancel_on_extracting(progress):
        return progress.phase != "extracting"

    report = sync.sync_folder(source, progress_callback=cancel_on_extracting)

    assert report.cancelled is True
    assert report.cache_entries_deleted == 1
    assert report.cache_stale_deleted == 0
    assert manifest.cache_entry_count(state="staged") == 0
    assert manifest.cache_entry_count(state="committed") == 1
    assert committed.exists()
    assert not staged.exists()


def test_manifest_failure_discards_staged_cache_and_preserves_committed(
    tmp_path: Path,
    monkeypatch,
):
    settings, source, target, store, manifest, sync, root_id = _synced_text_file(
        tmp_path
    )
    old_content_hash = _content_hash(manifest, settings, root_id)
    committed = _write_blob(settings, "product_cache/committed.json")
    staged = _write_blob(settings, "product_cache/staged.json")
    _stage_cache(
        manifest,
        settings,
        root_id=root_id,
        cache_key="committed",
        content_hash=old_content_hash,
        blob_rel_path="product_cache/committed.json",
    )
    manifest.commit_staged_cache_entries(
        settings.workspace_id, root_id, "doc.txt", old_content_hash
    )
    _stage_cache(
        manifest,
        settings,
        root_id=root_id,
        cache_key="staged",
        content_hash="new-content",
        blob_rel_path="product_cache/staged.json",
    )
    old_count = store.count()
    target.write_text("version two")

    def fail_manifest_write(*args, **kwargs):
        raise RuntimeError("manifest write failed")

    monkeypatch.setattr(manifest, "upsert_file", fail_manifest_write)
    report = sync.sync_folder(source)

    assert report.failed == 1
    assert report.cache_entries_deleted == 1
    assert manifest.cache_entry_count(state="staged") == 0
    assert manifest.cache_entry_count(state="committed") == 1
    assert committed.exists()
    assert not staged.exists()
    assert store.count() == old_count


def test_purge_removes_cache_index_and_cache_files(tmp_path: Path):
    settings, _source, _target, _store, manifest, sync, root_id = _synced_text_file(
        tmp_path
    )
    content_hash = _content_hash(manifest, settings, root_id)
    blob = _write_blob(settings, "product_cache/purge.json")
    _stage_cache(
        manifest,
        settings,
        root_id=root_id,
        content_hash=content_hash,
        blob_rel_path="product_cache/purge.json",
    )
    manifest.commit_staged_cache_entries(
        settings.workspace_id, root_id, "doc.txt", content_hash
    )

    sync.purge()

    assert not blob.exists()
    assert not settings.manifest_path.exists()
    assert settings.cache_dir.exists()


def _synced_text_file(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    target = source / "doc.txt"
    target.write_text("version one")
    store = QdrantStore(settings, in_memory=True)
    manifest = ManifestStore(settings.manifest_path)
    sync = SyncService(settings, store=store, manifest=manifest)

    first = sync.sync_folder(source)

    assert first.added == 1
    return settings, source, target, store, manifest, sync, root_id_for_path(source)


def _stage_cache(
    manifest: ManifestStore,
    settings: Settings,
    *,
    root_id: str = "root",
    cache_key: str = "cache-key",
    content_hash: str = "content-v1",
    blob_rel_path: str = "product_cache/blob.json",
) -> None:
    manifest.stage_cache_entry(
        cache_key=cache_key,
        workspace_id=settings.workspace_id,
        root_id=root_id,
        relative_path="doc.txt",
        file_id="file-id",
        unit_id="unit-id",
        content_hash=content_hash,
        entry_type="document_result",
        payload_sha256="payload-hash",
        blob_rel_path=blob_rel_path,
    )


def _write_blob(settings: Settings, blob_rel_path: str) -> Path:
    path = settings.cache_dir / blob_rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("cache payload")
    return path


def _content_hash(
    manifest: ManifestStore,
    settings: Settings,
    root_id: str,
) -> str:
    record = manifest.get_file(settings.workspace_id, root_id, "doc.txt")
    assert record is not None
    return str(record["content_hash"])
