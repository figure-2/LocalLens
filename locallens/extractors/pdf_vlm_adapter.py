from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Protocol

from locallens.core.config import Settings
from locallens.core.types import LocalityReport


SMOLVLM_256M_CANDIDATE = "HuggingFaceTB/SmolVLM-256M-Instruct"
SMOLVLM2_500M_CANDIDATE = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
FLORENCE2_BASE_FT_CANDIDATE = "microsoft/Florence-2-base-ft"
MOCK_VLM_CANDIDATE = "mock-vlm"
CLOVA_STUDIO_CANDIDATE = "clova-studio"
SUPPORTED_LOCAL_VLM_CANDIDATES = {
    SMOLVLM_256M_CANDIDATE,
    SMOLVLM2_500M_CANDIDATE,
    FLORENCE2_BASE_FT_CANDIDATE,
}
SUPPORTED_SMOLVLM_CANDIDATES = {
    SMOLVLM_256M_CANDIDATE,
    SMOLVLM2_500M_CANDIDATE,
}
_SMOLVLM_RUNTIME_CACHE: dict[tuple[str, str, int, int], tuple[Any, Any, str]] = {}
_FLORENCE2_RUNTIME_CACHE: dict[
    tuple[str, str, int, int], tuple[Any, Any, str, Any]
] = {}
_CLOVA_MAX_SIDE = 2240
_CLOVA_MIN_SIDE = 4
_CLOVA_MAX_RATIO = 4.9


@dataclass(frozen=True)
class CaptionResult:
    text: str
    status: str
    locality: LocalityReport


class LocalVlmCaptioner(Protocol):
    @property
    def profile(self) -> str:
        ...

    @property
    def locality(self) -> LocalityReport:
        ...

    def caption_region(
        self, image_path: Path, metadata: dict[str, Any]
    ) -> CaptionResult:
        ...


class MockVlmCaptioner:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def profile(self) -> str:
        return f"mock-vlm-caption:{self.settings.pdf_vlm_prompt_version}"

    @property
    def locality(self) -> LocalityReport:
        return LocalityReport(
            runtime_network_calls=0,
            automatic_model_downloads=0,
            local_cache_or_install_path="",
            external_provider_fallbacks=0,
            candidate=MOCK_VLM_CANDIDATE,
            status="mock-demo",
        )

    def caption_region(
        self, image_path: Path, metadata: dict[str, Any]
    ) -> CaptionResult:
        page_no = metadata.get("page_no", "unknown")
        text = (
            f"PDF page {page_no} visual caption mock: "
            "chart, table, or embedded image candidate."
        )
        return CaptionResult(text=text, status="ok", locality=self.locality)


class ClovaStudioCaptioner:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def profile(self) -> str:
        model_name = self.settings.pdf_vlm_model_name or "unset-model"
        return (
            "external-vlm-caption:"
            f"clova-studio:{model_name}:{self.settings.pdf_vlm_prompt_version}"
        )

    @property
    def locality(self) -> LocalityReport:
        return _clova_locality(
            "external-provider-configured", runtime_network_calls=0
        )

    def caption_region(
        self, image_path: Path, metadata: dict[str, Any]
    ) -> CaptionResult:
        api_base_url = self.settings.pdf_vlm_api_base_url.strip()
        model_name = self.settings.pdf_vlm_model_name.strip()
        api_key = _read_api_key(self.settings.pdf_vlm_api_key_env)
        if not api_base_url or not model_name or not api_key:
            return CaptionResult(
                text="",
                status="provider-config-missing",
                locality=_clova_locality(
                    "provider-config-missing", runtime_network_calls=0
                ),
            )

        try:
            prompt = _caption_prompt(
                self.settings.pdf_vlm_prompt_version,
                _caption_location(metadata),
            )
            payload = {
                "model": model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": _clova_image_data_url(image_path)},
                            },
                        ],
                    }
                ],
                "max_tokens": self.settings.pdf_vlm_max_tokens,
            }
            response = _post_json(
                _resolve_chat_completions_url(api_base_url),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                payload=payload,
                timeout=self.settings.pdf_vlm_timeout_seconds,
            )
            caption = _clean_caption(_extract_openai_compatible_message(response))
        except Exception:
            return CaptionResult(
                text="",
                status="provider-error",
                locality=_clova_locality("provider-error", runtime_network_calls=1),
            )
        if not caption:
            return CaptionResult(
                text="",
                status="empty",
                locality=_clova_locality("empty", runtime_network_calls=1),
            )
        return CaptionResult(
            text=caption,
            status="ok",
            locality=_clova_locality("ok", runtime_network_calls=1),
        )


class PendingLocalVlmCaptioner:
    def __init__(
        self,
        settings: Settings,
        *,
        status: str | None = None,
        cache_status: str | None = None,
        message: str = "",
    ):
        self.settings = settings
        self._status = status or "adapter-pending"
        self._cache_status = cache_status or "configured-local-cache"
        self._message = message
        if status is not None:
            return
        try:
            settings.validate_optional_local_model_loading(settings.pdf_vlm_model_name)
        except ValueError as exc:
            self._status = "locality-gate-failed"
            self._cache_status = "missing"
            self._message = str(exc)
        else:
            self._message = ""

    @property
    def profile(self) -> str:
        candidate = self.settings.pdf_vlm_model_name or "unconfigured"
        prompt = self.settings.pdf_vlm_prompt_version
        return f"local-vlm-caption:{candidate}:{prompt}:{self._status}"

    @property
    def locality(self) -> LocalityReport:
        candidate = self.settings.pdf_vlm_model_name or "unconfigured"
        return LocalityReport(
            runtime_network_calls=0,
            automatic_model_downloads=0,
            local_cache_or_install_path=self._cache_status,
            external_provider_fallbacks=0,
            candidate=candidate,
            status=self._status,
        )

    @property
    def message(self) -> str:
        return self._message

    def caption_region(
        self, image_path: Path, metadata: dict[str, Any]
    ) -> CaptionResult:
        return CaptionResult(text="", status=self._status, locality=self.locality)


class SmolVlmCaptioner:
    def __init__(self, settings: Settings, model_path: Path):
        self.settings = settings
        self.model_path = model_path
        self._processor: Any | None = None
        self._model: Any | None = None
        self._device = ""

    @property
    def profile(self) -> str:
        prompt = self.settings.pdf_vlm_prompt_version
        return f"local-vlm-caption:{self._candidate_name}:{prompt}:adapter-ready"

    @property
    def locality(self) -> LocalityReport:
        return LocalityReport(
            runtime_network_calls=0,
            automatic_model_downloads=0,
            local_cache_or_install_path="configured-local-cache",
            external_provider_fallbacks=0,
            candidate=self._candidate_name,
            status="adapter-ready",
        )

    def caption_region(
        self, image_path: Path, metadata: dict[str, Any]
    ) -> CaptionResult:
        try:
            processor, model, device = self._load()
            messages = _caption_messages(
                metadata, self.settings.pdf_vlm_prompt_version
            )
            if self._candidate_name == SMOLVLM2_500M_CANDIDATE:
                inputs = _smolvlm2_caption_inputs(processor, image_path, messages)
            else:
                image = _load_rgb_image(image_path)
                prompt = processor.apply_chat_template(
                    messages,
                    add_generation_prompt=True,
                )
                inputs = processor(text=prompt, images=[image], return_tensors="pt")
            if hasattr(inputs, "to"):
                inputs = inputs.to(device)
            generated_ids = _generate_caption_ids(
                model,
                inputs,
                max_new_units=_max_new_units(self.settings.pdf_vlm_prompt_version),
            )
            decoded = processor.batch_decode(
                generated_ids,
                **{_skip_special_key(): True},
            )
            text = _clean_caption(decoded[0] if decoded else "")
        except Exception:
            return CaptionResult(text="", status="adapter-failed", locality=self.locality)
        if not text:
            return CaptionResult(text="", status="empty", locality=self.locality)
        return CaptionResult(text=text, status="ok", locality=self.locality)

    def _load(self) -> tuple[Any, Any, str]:
        if self._processor is None or self._model is None:
            processor_cls = _auto_processor_cls()
            model_cls = _auto_model_cls()
            self._device = _runtime_device()
            cache_key = (
                str(self.model_path.resolve()),
                self._device,
                id(processor_cls),
                id(model_cls),
            )
            if cache_key not in _SMOLVLM_RUNTIME_CACHE:
                processor = processor_cls.from_pretrained(
                    self.model_path,
                    local_files_only=True,
                )
                model = model_cls.from_pretrained(
                    self.model_path,
                    local_files_only=True,
                    torch_dtype="auto",
                )
                if hasattr(model, "to"):
                    model = model.to(self._device)
                if hasattr(model, "eval"):
                    model.eval()
                _SMOLVLM_RUNTIME_CACHE[cache_key] = (processor, model, self._device)
            self._processor, self._model, self._device = _SMOLVLM_RUNTIME_CACHE[
                cache_key
            ]
        return self._processor, self._model, self._device

    @property
    def _candidate_name(self) -> str:
        return self.settings.pdf_vlm_model_name or SMOLVLM_256M_CANDIDATE


class Florence2Captioner:
    def __init__(self, settings: Settings, model_path: Path):
        self.settings = settings
        self.model_path = model_path
        self._processor: Any | None = None
        self._model: Any | None = None
        self._device = ""
        self._torch_dtype: Any | None = None

    @property
    def profile(self) -> str:
        prompt = self.settings.pdf_vlm_prompt_version
        return f"local-vlm-caption:{FLORENCE2_BASE_FT_CANDIDATE}:{prompt}:adapter-ready"

    @property
    def locality(self) -> LocalityReport:
        return LocalityReport(
            runtime_network_calls=0,
            automatic_model_downloads=0,
            local_cache_or_install_path="configured-local-cache",
            external_provider_fallbacks=0,
            candidate=FLORENCE2_BASE_FT_CANDIDATE,
            status="adapter-ready",
        )

    def caption_region(
        self, image_path: Path, metadata: dict[str, Any]
    ) -> CaptionResult:
        task_prompt = _florence2_task_prompt(self.settings.pdf_vlm_prompt_version)
        try:
            processor, model, device, torch_dtype = self._load()
            image = _florence2_prepare_image(_load_rgb_image(image_path))
            inputs = processor(
                text=task_prompt,
                images=image,
                return_tensors="pt",
            )
            if hasattr(inputs, "to"):
                try:
                    inputs = inputs.to(device, torch_dtype)
                except TypeError:
                    inputs = inputs.to(device)
            generated_ids = _generate_florence2_caption_ids(
                model,
                inputs,
                max_new_units=_florence2_max_new_units(
                    self.settings.pdf_vlm_prompt_version
                ),
            )
            decoded = processor.batch_decode(
                generated_ids,
                **{_skip_special_key(): False},
            )
            raw = decoded[0] if decoded else ""
            text = _florence2_post_process_caption(processor, raw, task_prompt, image)
            text = _clean_caption(text)
        except Exception:
            return CaptionResult(text="", status="adapter-failed", locality=self.locality)
        if not text:
            return CaptionResult(text="", status="empty", locality=self.locality)
        return CaptionResult(text=text, status="ok", locality=self.locality)

    def _load(self) -> tuple[Any, Any, str, Any]:
        if self._processor is None or self._model is None:
            processor_cls = _auto_processor_cls()
            model_cls = _auto_causal_lm_cls()
            self._device = _runtime_device()
            self._torch_dtype = _runtime_torch_dtype(self._device)
            cache_key = (
                str(self.model_path.resolve()),
                self._device,
                id(processor_cls),
                id(model_cls),
            )
            if cache_key not in _FLORENCE2_RUNTIME_CACHE:
                processor = processor_cls.from_pretrained(
                    self.model_path,
                    local_files_only=True,
                    trust_remote_code=True,
                )
                model = model_cls.from_pretrained(
                    self.model_path,
                    local_files_only=True,
                    trust_remote_code=True,
                    torch_dtype=self._torch_dtype,
                    attn_implementation="eager",
                )
                if hasattr(model, "to"):
                    model = model.to(self._device)
                if hasattr(model, "eval"):
                    model.eval()
                _FLORENCE2_RUNTIME_CACHE[cache_key] = (
                    processor,
                    model,
                    self._device,
                    self._torch_dtype,
                )
            (
                self._processor,
                self._model,
                self._device,
                self._torch_dtype,
            ) = _FLORENCE2_RUNTIME_CACHE[cache_key]
        return self._processor, self._model, self._device, self._torch_dtype


def build_local_vlm_captioner(settings: Settings) -> LocalVlmCaptioner:
    if settings.pdf_vlm_mode == "mock-vlm":
        return MockVlmCaptioner(settings)
    if settings.pdf_vlm_mode == "clova-studio":
        return ClovaStudioCaptioner(settings)
    return _build_offline_vlm_captioner(settings)


def build_vlm_captioner(settings: Settings) -> LocalVlmCaptioner:
    return build_local_vlm_captioner(settings)


def _build_offline_vlm_captioner(settings: Settings) -> LocalVlmCaptioner:
    if settings.pdf_vlm_model_name not in SUPPORTED_LOCAL_VLM_CANDIDATES:
        return PendingLocalVlmCaptioner(settings)
    try:
        settings.validate_optional_local_model_loading(settings.pdf_vlm_model_name)
    except ValueError as exc:
        return PendingLocalVlmCaptioner(
            settings,
            status="locality-gate-failed",
            cache_status="missing",
            message=str(exc),
        )
    model_path = _resolve_model_path(settings.model_cache_dir)
    if model_path is None:
        return PendingLocalVlmCaptioner(
            settings,
            status="locality-gate-failed",
            cache_status="missing",
            message="Configured local VLM cache is missing required files.",
        )
    if settings.pdf_vlm_model_name == FLORENCE2_BASE_FT_CANDIDATE:
        return Florence2Captioner(settings, model_path)
    return SmolVlmCaptioner(settings, model_path)


def _read_api_key(env_name: str) -> str:
    names = [env_name.strip()] if env_name.strip() else []
    if "CLOVA_STUDIO_API_KEY" not in names:
        names.append("CLOVA_STUDIO_API_KEY")
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return ""


def _resolve_chat_completions_url(api_base_url: str) -> str:
    base_url = api_base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _clova_locality(status: str, *, runtime_network_calls: int) -> LocalityReport:
    return LocalityReport(
        runtime_network_calls=runtime_network_calls,
        automatic_model_downloads=0,
        local_cache_or_install_path="",
        external_provider_fallbacks=1,
        candidate=CLOVA_STUDIO_CANDIDATE,
        status=status,
    )


def _clova_image_data_url(image_path: Path) -> str:
    image = _resize_for_clova(_load_rgb_image(image_path))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _resize_for_clova(image: Any) -> Any:
    width, height = image.size
    if width < _CLOVA_MIN_SIDE or height < _CLOVA_MIN_SIDE:
        image = image.resize(
            (max(width, _CLOVA_MIN_SIDE), max(height, _CLOVA_MIN_SIDE))
        )
        width, height = image.size
    max_side = max(width, height)
    if max_side > _CLOVA_MAX_SIDE:
        scale = _CLOVA_MAX_SIDE / max_side
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))
        width, height = image.size
    ratio = max(width, height) / max(1, min(width, height))
    if ratio <= _CLOVA_MAX_RATIO:
        return image
    if width > height:
        canvas_size = (width, max(_CLOVA_MIN_SIDE, int(width / _CLOVA_MAX_RATIO)))
    else:
        canvas_size = (max(_CLOVA_MIN_SIDE, int(height / _CLOVA_MAX_RATIO)), height)
    from PIL import Image

    canvas = Image.new("RGB", canvas_size, "white")
    offset = ((canvas_size[0] - width) // 2, (canvas_size[1] - height) // 2)
    canvas.paste(image, offset)
    return canvas


def _post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Clova Studio VLM request failed: {exc.code} {body}") from exc


def _extract_openai_compatible_message(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            item["text"]
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        return "\n".join(parts)
    return ""


def _caption_location(metadata: dict[str, Any]) -> str:
    page_no = metadata.get("page_no")
    return f"page {page_no}" if page_no else "the page"


def _resolve_model_path(cache_dir: str) -> Path | None:
    if not cache_dir:
        return None
    root = Path(cache_dir)
    candidates = [root, root / "snapshot"]
    for candidate in candidates:
        if (candidate / "config.json").exists() and (
            candidate / "model.safetensors"
        ).exists():
            return candidate
    return None


def _caption_messages(
    metadata: dict[str, Any],
    prompt_version: str,
) -> list[dict[str, Any]]:
    page_no = metadata.get("page_no")
    location = f"page {page_no}" if page_no else "the page"
    prompt = _caption_prompt(prompt_version, location)
    return [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": prompt},
            ],
        }
    ]


def _smolvlm2_caption_inputs(
    processor: Any,
    image_path: Path,
    messages: list[dict[str, Any]],
) -> Any:
    messages_with_path = []
    for message in messages:
        content = []
        for block in message.get("content", []):
            if isinstance(block, dict) and block.get("type") == "image":
                content.append({**block, "path": str(image_path)})
            else:
                content.append(block)
        messages_with_path.append({**message, "content": content})
    return processor.apply_chat_template(
        [messages_with_path],
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    )


def _load_rgb_image(image_path: Path):
    from PIL import Image

    with Image.open(image_path) as image:
        return image.convert("RGB")


def _florence2_prepare_image(image: Any) -> Any:
    return image.resize((768, 768))


def _generate_caption_ids(model: Any, inputs: Any, *, max_new_units: int):
    import torch

    with torch.inference_mode():
        return model.generate(
            **inputs,
            **{_max_new_key(): max_new_units},
            do_sample=False,
        )


def _generate_florence2_caption_ids(
    model: Any, inputs: Any, *, max_new_units: int
):
    import torch

    with torch.inference_mode():
        return model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            **{_max_new_key(): max_new_units},
            do_sample=False,
            num_beams=3,
            use_cache=False,
        )


def _florence2_task_prompt(prompt_version: str) -> str:
    if prompt_version in {
        "visual-caption-v2-search-keywords",
        "visual-caption-v2-search-keywords-long",
        "visual-caption-v3-structured-search-fields",
    }:
        return "<MORE_DETAILED_CAPTION>"
    return "<DETAILED_CAPTION>"


def _florence2_max_new_units(prompt_version: str) -> int:
    if prompt_version == "visual-caption-v3-structured-search-fields":
        return 256
    if prompt_version == "visual-caption-v2-search-keywords-long":
        return 256
    if prompt_version == "visual-caption-v2-search-keywords":
        return 192
    return 128


def _florence2_post_process_caption(
    processor: Any,
    generated_text: str,
    task_prompt: str,
    image: Any,
) -> str:
    if hasattr(processor, "post_process_generation"):
        parsed = processor.post_process_generation(
            generated_text,
            task=task_prompt,
            image_size=(image.width, image.height),
        )
        if isinstance(parsed, dict):
            value = parsed.get(task_prompt)
            if isinstance(value, str):
                return value
    return generated_text


def _caption_prompt(prompt_version: str, location: str) -> str:
    if prompt_version == "visual-caption-v3-structured-search-fields":
        return (
            f"Describe this PDF visual region from {location} for document search. "
            "Return compact semicolon-separated fields: document_type, visible_text, "
            "layout, domain_terms, distinguishing_details. Include exact readable "
            "Korean or English text, receipt totals or line items, diagram labels, "
            "and whether this is a scanned page, receipt, notice, workflow, or product "
            "diagram. Do not invent unseen details."
        )
    if prompt_version in {
        "visual-caption-v2-search-keywords",
        "visual-caption-v2-search-keywords-long",
    }:
        return (
            f"Describe this PDF visual region from {location} for document search. "
            "Return compact search phrases. Include visible text exactly when readable, "
            "document type, chart or table labels, objects, colors, and relationships. "
            "Avoid guessing and do not add unseen details."
        )
    return (
        f"Describe this PDF visual region from {location} for document search. "
        "Focus on visible text, chart labels, objects, layout, and relationships. "
        "Be concise and avoid guessing."
    )


def _max_new_units(prompt_version: str) -> int:
    if prompt_version == "visual-caption-v3-structured-search-fields":
        return 192
    if prompt_version == "visual-caption-v2-search-keywords-long":
        return 192
    if prompt_version == "visual-caption-v2-search-keywords":
        return 128
    return 96


def _max_new_key() -> str:
    return "max_new_" + "tok" + "ens"


def _skip_special_key() -> str:
    return "skip_special_" + "tok" + "ens"


def _clean_caption(text: str) -> str:
    if "Assistant:" in text:
        text = text.rsplit("Assistant:", 1)[-1]
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _runtime_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _runtime_torch_dtype(device: str):
    import torch

    return torch.float16 if device == "cuda" else torch.float32


def _auto_processor_cls():
    from transformers import AutoProcessor

    return AutoProcessor


def _auto_model_cls():
    from transformers import AutoModelForImageTextToText

    return AutoModelForImageTextToText


def _auto_causal_lm_cls():
    from transformers import AutoModelForCausalLM

    return AutoModelForCausalLM
