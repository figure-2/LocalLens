from __future__ import annotations

from locallens.core.config import Settings
from locallens.embeddings.hashing import hash_vector


class TextEmbedder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.dimension = settings.text_dimension
        self.profile = f"hash:{settings.text_dimension}"
        self._model = None
        if settings.text_embedding_backend == "sentence-transformers":
            self._load_sentence_transformer()

    def embed(self, text: str) -> list[float]:
        return self.embed_document(text)

    def embed_document(self, text: str) -> list[float]:
        if self.settings.text_embedding_backend == "sentence-transformers":
            return self._embed_with_sentence_transformers(_as_document(text))
        return hash_vector(f"query-or-text:{text}", self.dimension)

    def embed_query(self, query: str) -> list[float]:
        if self.settings.text_embedding_backend == "sentence-transformers":
            return self._embed_with_sentence_transformers(_as_query(query))
        return hash_vector(f"query-or-text:{query}", self.dimension)

    def _load_sentence_transformer(self) -> None:
        from sentence_transformers import SentenceTransformer

        if self._model is None:
            self.settings.validate_release_model_loading()
            kwargs = {}
            if self.settings.model_cache_dir:
                kwargs["cache_folder"] = self.settings.model_cache_dir
            if self.settings.model_local_files_only:
                kwargs["local_files_only"] = True
            self._model = SentenceTransformer(self.settings.text_model_name, **kwargs)
            if hasattr(self._model, "get_embedding_dimension"):
                self.dimension = int(self._model.get_embedding_dimension())
            else:
                self.dimension = int(self._model.get_sentence_embedding_dimension())
            self.profile = f"sentence-transformers:{self.settings.text_model_name}"

    def _embed_with_sentence_transformers(self, text: str) -> list[float]:
        self._load_sentence_transformer()
        vector = self._model.encode([text], normalize_embeddings=True)[0]
        return vector.tolist() if hasattr(vector, "tolist") else list(vector)


def _as_document(text: str) -> str:
    return f"passage: {text}"


def _as_query(query: str) -> str:
    return f"query: {query}"
