from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from locallens.core.config import Settings
from locallens.embeddings.text_embedder import TextEmbedder
from locallens.embeddings.vision_embedder import VisionEmbedder


def test_text_embedder_uses_sentence_transformer_dimension(monkeypatch):
    calls = []

    class FakeSentenceTransformer:
        def __init__(self, model_name, **kwargs):
            self.model_name = model_name
            calls.append((model_name, kwargs))

        def get_embedding_dimension(self):
            return 3

        def encode(self, texts, normalize_embeddings=True):
            assert texts[0].startswith("query: ")
            return [[0.1, 0.2, 0.3]]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    settings = Settings(text_embedding_backend="sentence-transformers")

    embedder = TextEmbedder(settings)
    vector = embedder.embed_query("hello")

    assert embedder.dimension == 3
    assert embedder.profile == "sentence-transformers:intfloat/multilingual-e5-small"
    assert vector == [0.1, 0.2, 0.3]
    assert calls == [("intfloat/multilingual-e5-small", {})]


def test_text_embedder_supports_previous_dimension_api(monkeypatch):
    class FakeSentenceTransformer:
        def __init__(self, model_name, **kwargs):
            self.model_name = model_name

        def get_sentence_embedding_dimension(self):
            return 2

        def encode(self, texts, normalize_embeddings=True):
            assert texts[0].startswith("passage: ")
            return [[0.5, 0.5]]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    settings = Settings(text_embedding_backend="sentence-transformers")

    embedder = TextEmbedder(settings)
    vector = embedder.embed_document("hello")

    assert embedder.dimension == 2
    assert vector == [0.5, 0.5]


def test_text_embedder_can_force_local_cache_for_release_evidence(monkeypatch, tmp_path: Path):
    calls = []

    class FakeSentenceTransformer:
        def __init__(self, model_name, **kwargs):
            calls.append((model_name, kwargs))

        def get_embedding_dimension(self):
            return 3

        def encode(self, texts, normalize_embeddings=True):
            return [[0.1, 0.2, 0.3]]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    settings = Settings(
        text_embedding_backend="sentence-transformers",
        model_cache_dir=str(tmp_path / "models"),
        model_local_files_only=True,
        release_evidence_mode=True,
        hf_hub_offline=True,
        transformers_offline=True,
    )

    vector = TextEmbedder(settings).embed_query("hello")

    assert vector == [0.1, 0.2, 0.3]
    assert calls == [
        (
            "intfloat/multilingual-e5-small",
            {"cache_folder": str(tmp_path / "models"), "local_files_only": True},
        )
    ]


def test_release_evidence_model_loading_requires_offline_cache(monkeypatch):
    class FakeSentenceTransformer:
        def __init__(self, model_name, **kwargs):
            raise AssertionError("model loader should not be called")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    settings = Settings(
        text_embedding_backend="sentence-transformers",
        release_evidence_mode=True,
    )

    with pytest.raises(ValueError, match="LOCALLENS_MODEL_LOCAL_FILES_ONLY"):
        TextEmbedder(settings)


def test_vision_transformers_backend_uses_model_dimension(monkeypatch, tmp_path: Path):
    torch = pytest.importorskip("torch")
    calls = []

    class FakeInputs(dict):
        def to(self, device):
            return self

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            calls.append(("processor", model_name, kwargs))
            return cls()

        def __call__(self, **kwargs):
            return FakeInputs()

    class FakeModel:
        config = types.SimpleNamespace(projection_dim=4)

        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            calls.append(("model", model_name, kwargs))
            return cls()

        def to(self, device):
            return self

        def eval(self):
            return self

        def get_text_features(self, **kwargs):
            return torch.tensor([[1.0, 0.0, 0.0, 0.0]])

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        types.SimpleNamespace(AutoModel=FakeModel, AutoProcessor=FakeProcessor),
    )
    settings = Settings(vision_embedding_backend="transformers")

    embedder = VisionEmbedder(settings)
    vector = embedder.embed_query("image query")

    assert embedder.dimension == 4
    assert embedder.profile == "transformers:google/siglip-base-patch16-224"
    assert vector == [1.0, 0.0, 0.0, 0.0]
    assert calls == [
        ("model", "google/siglip-base-patch16-224", {}),
        ("processor", "google/siglip-base-patch16-224", {}),
    ]


def test_vision_transformers_backend_handles_pooling_output(monkeypatch):
    torch = pytest.importorskip("torch")

    class FakeInputs(dict):
        def to(self, device):
            return self

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            return cls()

        def __call__(self, **kwargs):
            return FakeInputs()

    class FakeModel:
        config = types.SimpleNamespace(projection_dim=2)

        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            return cls()

        def to(self, device):
            return self

        def eval(self):
            return self

        def get_text_features(self, **kwargs):
            return types.SimpleNamespace(pooler_output=torch.tensor([[0.0, 2.0]]))

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        types.SimpleNamespace(AutoModel=FakeModel, AutoProcessor=FakeProcessor),
    )
    settings = Settings(vision_embedding_backend="transformers")

    embedder = VisionEmbedder(settings)
    vector = embedder.embed_query("image query")

    assert vector == [0.0, 1.0]


def test_siglip_vision_query_uses_max_length_padding(monkeypatch):
    torch = pytest.importorskip("torch")
    calls = []

    class FakeInputs(dict):
        def to(self, device):
            return self

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            return cls()

        def __call__(self, **kwargs):
            calls.append(kwargs)
            return FakeInputs()

    class FakeModel:
        config = types.SimpleNamespace(projection_dim=2)

        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            return cls()

        def to(self, device):
            return self

        def eval(self):
            return self

        def get_text_features(self, **kwargs):
            return torch.tensor([[1.0, 0.0]])

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        types.SimpleNamespace(AutoModel=FakeModel, AutoProcessor=FakeProcessor),
    )
    settings = Settings(
        vision_embedding_backend="transformers",
        vision_model_name="google/siglip-base-patch16-224",
    )

    VisionEmbedder(settings).embed_query("red square")

    assert calls[-1]["padding"] == "max_length"
    assert calls[-1]["truncation"] is True


def test_vision_transformers_backend_can_force_local_files_only(
    monkeypatch, tmp_path: Path
):
    torch = pytest.importorskip("torch")
    calls = []

    class FakeInputs(dict):
        def to(self, device):
            return self

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            calls.append(("processor", model_name, kwargs))
            return cls()

        def __call__(self, **kwargs):
            return FakeInputs()

    class FakeModel:
        config = types.SimpleNamespace(projection_dim=2)

        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            calls.append(("model", model_name, kwargs))
            return cls()

        def to(self, device):
            return self

        def eval(self):
            return self

        def get_text_features(self, **kwargs):
            return torch.tensor([[1.0, 0.0]])

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        types.SimpleNamespace(AutoModel=FakeModel, AutoProcessor=FakeProcessor),
    )
    settings = Settings(
        vision_embedding_backend="transformers",
        model_cache_dir=str(tmp_path / "models"),
        model_local_files_only=True,
        release_evidence_mode=True,
        hf_hub_offline=True,
        transformers_offline=True,
    )

    vector = VisionEmbedder(settings).embed_query("red square")

    assert vector == [1.0, 0.0]
    assert calls == [
        (
            "model",
            "google/siglip-base-patch16-224",
            {"cache_dir": str(tmp_path / "models"), "local_files_only": True},
        ),
        (
            "processor",
            "google/siglip-base-patch16-224",
            {"cache_dir": str(tmp_path / "models"), "local_files_only": True},
        ),
    ]
