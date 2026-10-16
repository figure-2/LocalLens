from __future__ import annotations

from pathlib import Path

from locallens.core.config import Settings
from locallens.embeddings.hashing import file_hash_vector, hash_vector


class VisionEmbedder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.dimension = settings.vision_dimension
        self.profile = f"hash:{settings.vision_dimension}"
        self._model = None
        self._processor = None
        self._device = "cpu"
        if settings.vision_embedding_backend == "transformers":
            self._load_transformers_model()

    def embed_file(self, path: Path) -> list[float]:
        if self.settings.vision_embedding_backend == "transformers":
            return self._embed_image_with_transformers(path)
        return file_hash_vector(path, self.dimension)

    def embed_query(self, query: str) -> list[float]:
        if self.settings.vision_embedding_backend == "transformers":
            return self._embed_text_with_transformers(query)
        return hash_vector(f"vision-query:{query}", self.dimension)

    def _load_transformers_model(self) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        if self._model is not None and self._processor is not None:
            return
        self.settings.validate_release_model_loading()
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        kwargs = {}
        if self.settings.model_cache_dir:
            kwargs["cache_dir"] = self.settings.model_cache_dir
        if self.settings.model_local_files_only:
            kwargs["local_files_only"] = True
        self._model = AutoModel.from_pretrained(self.settings.vision_model_name, **kwargs)
        self._processor = AutoProcessor.from_pretrained(
            self.settings.vision_model_name, **kwargs
        )
        self._model = self._model.to(self._device).eval()
        self.dimension = _projection_dimension(self._model)
        self.profile = f"transformers:{self.settings.vision_model_name}"

    def _embed_image_with_transformers(self, path: Path) -> list[float]:
        import torch
        from PIL import Image, ImageOps

        self._load_transformers_model()
        with Image.open(path) as image:
            rgb_image = ImageOps.exif_transpose(image).convert("RGB")
            inputs = self._processor(images=[rgb_image], return_tensors="pt")
        inputs = inputs.to(self._device)
        with torch.inference_mode():
            vector = _feature_tensor(self._model.get_image_features(**inputs))
        return _normalized_list(vector)

    def _embed_text_with_transformers(self, query: str) -> list[float]:
        import torch

        self._load_transformers_model()
        inputs = self._processor(
            text=[query],
            return_tensors="pt",
            padding=_text_padding(self.settings.vision_model_name),
            truncation=True,
        )
        inputs = inputs.to(self._device)
        with torch.inference_mode():
            vector = _feature_tensor(self._model.get_text_features(**inputs))
        return _normalized_list(vector)


def _projection_dimension(model) -> int:
    config = getattr(model, "config", None)
    for name in ("projection_dim", "hidden_size"):
        value = getattr(config, name, None)
        if value:
            return int(value)
    for parent_name in ("vision_config", "text_config"):
        parent = getattr(config, parent_name, None)
        value = getattr(parent, "hidden_size", None)
        if value:
            return int(value)
    raise ValueError("Unable to determine vision embedding dimension")


def _normalized_list(vector) -> list[float]:
    import torch

    normalized = torch.nn.functional.normalize(vector.float(), dim=0)
    return normalized.cpu().tolist()


def _feature_tensor(output):
    vector = getattr(output, "pooler_output", output)
    return vector[0] if getattr(vector, "ndim", 1) > 1 else vector


def _text_padding(model_name: str) -> bool | str:
    if "siglip" in model_name.lower():
        return "max_length"
    return True
