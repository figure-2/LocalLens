from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from locallens.core.config import Settings
from locallens.extractors.text_extractor import TextExtractor
from locallens.indexing.qdrant_store import QdrantStore
from locallens.ingestion.scanner import Scanner


pytest.importorskip("qdrant_client")


def test_qdrant_store_uses_server_url(monkeypatch, tmp_path: Path):
    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def close(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "qdrant_client",
        types.SimpleNamespace(QdrantClient=FakeClient),
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        qdrant_url="http://localhost:6333",
    )

    store = QdrantStore(settings)

    assert calls == [((), {"url": "http://localhost:6333", "timeout": 60.0})]
    assert not settings.qdrant_path.exists()
    store.close()


def test_qdrant_collection_created_with_named_vectors(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    store = QdrantStore(settings, in_memory=True)

    store.ensure_collection()
    collection = store.client.get_collection(settings.collection_name)

    assert settings.text_vector_name in collection.config.params.vectors
    assert settings.vision_vector_name in collection.config.params.vectors


def test_indexing_upserts_units_idempotently(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    source = tmp_path / "docs"
    source.mkdir()
    (source / "note.txt").write_text("alpha beta gamma")
    scanned = Scanner(settings).scan(source).files[0]
    units = TextExtractor(settings).extract(scanned)
    text_vectors = {unit.unit_id: [0.1] * settings.text_dimension for unit in units}
    store = QdrantStore(settings, in_memory=True)

    store.upsert_units(units, text_vectors=text_vectors, vision_vectors={})
    first_count = store.count()
    store.upsert_units(units, text_vectors=text_vectors, vision_vectors={})

    assert first_count == store.count()


def test_existing_collection_dimension_mismatch_fails(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    store = QdrantStore(settings, in_memory=True)
    store.ensure_collection()
    store.settings = Settings(data_dir=tmp_path / "data", text_dimension=32)

    with pytest.raises(ValueError, match="vector mismatch"):
        store.ensure_collection()
