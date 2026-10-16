from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

import locallens.extractors.pdf_extractor as pdf_module
import locallens.extractors.pdf_vlm_adapter as vlm_module
from locallens.core.config import Settings
from locallens.core.types import LocalityReport
from locallens.extractors.pdf_extractor import PdfExtractor
from locallens.extractors.pdf_vlm_adapter import CaptionResult, build_local_vlm_captioner
from locallens.indexing.manifest import ManifestStore
from locallens.indexing.qdrant_store import QdrantStore
from locallens.indexing.sync_service import SyncService
from locallens.ingestion.scanner import Scanner


fitz = pytest.importorskip("fitz")
Image = pytest.importorskip("PIL.Image")
pytest.importorskip("qdrant_client")


class FakeCaptioner:
    @property
    def profile(self) -> str:
        return "local-vlm-caption:fixture-captioner:visual-caption-v1"

    @property
    def locality(self) -> LocalityReport:
        return LocalityReport(
            runtime_network_calls=0,
            automatic_model_downloads=0,
            local_cache_or_install_path="configured-local-cache",
            external_provider_fallbacks=0,
            candidate="fixture-captioner",
            status="ok",
        )

    def caption_region(self, image_path: Path, metadata: dict) -> CaptionResult:
        assert image_path.exists()
        assert metadata["relative_path"].endswith(".pdf")
        return CaptionResult(
            text="Visual caption: approval chart with blue square.",
            status="ok",
            locality=self.locality,
        )


def test_pdf_vlm_mode_off_keeps_default_pdf_units(tmp_path: Path):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "visual.pdf")
    settings = Settings(data_dir=tmp_path / "data")
    scanned = Scanner(settings).scan(source).files[0]

    extractor = PdfExtractor(settings)
    units = extractor.extract(scanned)

    assert {unit.unit_type for unit in units}.isdisjoint({"pdf_visual_caption"})
    assert extractor.last_stats.vlm_attempted == 0


def test_pdf_local_vlm_creates_caption_units_with_locality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "visual.pdf")
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_vlm_mode="local-vlm",
        pdf_vlm_model_name="fixture-captioner",
    )
    scanned = Scanner(settings).scan(source).files[0]
    monkeypatch.setattr(
        pdf_module,
        "build_local_vlm_captioner",
        lambda settings: FakeCaptioner(),
    )

    extractor = PdfExtractor(settings)
    units = extractor.extract(scanned)
    captions = [unit for unit in units if unit.unit_type == "pdf_visual_caption"]

    assert len(captions) == 1
    assert {unit.unit_type for unit in units}.isdisjoint({"pdf_region", "pdf_image"})
    assert extractor.last_stats.vlm_attempted == 1
    assert extractor.last_stats.vlm_succeeded == 1
    assert extractor.last_stats.vlm_empty == 0
    caption = captions[0]
    assert caption.modality == "text"
    assert caption.page_no == 1
    assert caption.image_no == 0
    assert caption.bbox is not None
    assert caption.source_kind == "pdf"
    assert caption.extractor_profile == FakeCaptioner().profile
    assert caption.locality["runtime_network_calls"] == 0
    assert caption.locality["automatic_model_downloads"] == 0
    assert caption.locality["external_provider_fallbacks"] == 0
    assert caption.locality["local_cache_or_install_path"] == "configured-local-cache"
    assert "approval chart" in caption.text


def test_pdf_local_vlm_pending_adapter_records_empty_count(tmp_path: Path):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "visual.pdf")
    settings = Settings(data_dir=tmp_path / "data", pdf_vlm_mode="local-vlm")
    scanned = Scanner(settings).scan(source).files[0]

    extractor = PdfExtractor(settings)
    units = extractor.extract(scanned)

    assert [unit for unit in units if unit.unit_type == "pdf_visual_caption"] == []
    assert extractor.last_stats.vlm_attempted == 1
    assert extractor.last_stats.vlm_succeeded == 0
    assert extractor.last_stats.vlm_empty == 1
    assert extractor.last_stats.vlm_failed == 0


def test_mock_vlm_captioner_returns_demo_caption(tmp_path: Path) -> None:
    image_path = tmp_path / "visual.png"
    Image.new("RGB", (24, 24), "white").save(image_path)
    settings = Settings(data_dir=tmp_path / "data", pdf_vlm_mode="mock-vlm")

    result = build_local_vlm_captioner(settings).caption_region(image_path, {"page_no": 3})

    assert result.status == "ok"
    assert "visual caption mock" in result.text
    assert result.locality.runtime_network_calls == 0
    assert result.locality.external_provider_fallbacks == 0


def test_clova_captioner_fails_closed_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOVA_STUDIO_API_KEY", raising=False)
    image_path = tmp_path / "visual.png"
    Image.new("RGB", (24, 24), "white").save(image_path)
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_vlm_mode="clova-studio",
        pdf_vlm_model_name="HCX-005",
        pdf_vlm_api_base_url="https://clova.example/v1/openai",
    )

    result = build_local_vlm_captioner(settings).caption_region(image_path, {"page_no": 1})

    assert result.text == ""
    assert result.status == "provider-config-missing"
    assert result.locality.runtime_network_calls == 0
    assert result.locality.external_provider_fallbacks == 1


def test_clova_captioner_uses_openai_compatible_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("CLOVA_STUDIO_API_KEY", "test-key")

    def fake_post_json(
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout: float,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {"choices": [{"message": {"content": "표와 그래프가 포함된 페이지입니다."}}]}

    monkeypatch.setattr(vlm_module, "_post_json", fake_post_json)
    image_path = tmp_path / "visual.png"
    Image.new("RGB", (24, 24), "white").save(image_path)
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_vlm_mode="clova-studio",
        pdf_vlm_model_name="HCX-005",
        pdf_vlm_api_base_url="https://clova.example/v1/openai",
        pdf_vlm_max_tokens=77,
        pdf_vlm_timeout_seconds=12.5,
    )

    result = build_local_vlm_captioner(settings).caption_region(image_path, {"page_no": 2})

    assert result.status == "ok"
    assert result.text == "표와 그래프가 포함된 페이지입니다."
    assert captured["url"] == "https://clova.example/v1/openai/chat/completions"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert captured["timeout"] == 12.5
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "HCX-005"
    assert payload["max_tokens"] == 77
    messages = payload["messages"]
    assert isinstance(messages, list)
    content = messages[0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result.locality.runtime_network_calls == 1
    assert result.locality.external_provider_fallbacks == 1


def test_smolvlm_captioner_fails_closed_when_cache_missing(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_vlm_mode="local-vlm",
        pdf_vlm_model_name=vlm_module.SMOLVLM_256M_CANDIDATE,
        model_cache_dir=str(tmp_path / "missing-cache"),
        model_local_files_only=True,
        hf_hub_offline=True,
        transformers_offline=True,
    )

    captioner = build_local_vlm_captioner(settings)
    result = captioner.caption_region(tmp_path / "missing.png", {})

    assert result.text == ""
    assert result.status == "locality-gate-failed"
    assert result.locality.runtime_network_calls == 0
    assert result.locality.automatic_model_downloads == 0
    assert result.locality.external_provider_fallbacks == 0
    assert result.locality.local_cache_or_install_path == "missing"


def test_smolvlm_captioner_generates_with_local_path_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cache = tmp_path / "cache" / "snapshot"
    cache.mkdir(parents=True)
    (cache / "config.json").write_text("{}", encoding="utf-8")
    (cache / "model.safetensors").write_text("weights", encoding="utf-8")
    image_path = tmp_path / "region.png"
    Image.new("RGB", (24, 24), color=(80, 140, 220)).save(image_path)
    calls: dict[str, object] = {}

    class FakeInputs(dict):
        def to(self, device: str):
            calls["inputs_device"] = device
            return self

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, path: Path, *, local_files_only: bool):
            calls["processor_path"] = path
            calls["processor_local_only"] = local_files_only
            return cls()

        def apply_chat_template(self, messages: list[dict], *, add_generation_prompt: bool):
            calls["messages"] = messages
            calls["add_generation_prompt"] = add_generation_prompt
            return "prompt"

        def __call__(self, *, text: str, images: list, return_tensors: str):
            calls["text"] = text
            calls["image_mode"] = images[0].mode
            calls["return_tensors"] = return_tensors
            return FakeInputs({"input_ids": [1]})

        def batch_decode(self, generated_ids, **kwargs):
            calls["skip_special_tokens"] = kwargs["skip_special_tokens"]
            return ["User: prompt\nAssistant: blue chart with approval labels"]

    class FakeModel:
        @classmethod
        def from_pretrained(
            cls,
            path: Path,
            *,
            local_files_only: bool,
            torch_dtype: str,
        ):
            calls["model_path"] = path
            calls["model_local_only"] = local_files_only
            calls["torch_dtype"] = torch_dtype
            return cls()

        def to(self, device: str):
            calls["model_device"] = device
            return self

        def eval(self):
            calls["eval"] = True
            return self

        def generate(self, **kwargs):
            calls["generate_kwargs"] = kwargs
            return [[1, 2, 3]]

    monkeypatch.setattr(vlm_module, "_auto_processor_cls", lambda: FakeProcessor)
    monkeypatch.setattr(vlm_module, "_auto_model_cls", lambda: FakeModel)
    monkeypatch.setattr(vlm_module, "_runtime_device", lambda: "cpu")
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_vlm_mode="local-vlm",
        pdf_vlm_model_name=vlm_module.SMOLVLM_256M_CANDIDATE,
        model_cache_dir=str(cache.parent),
        model_local_files_only=True,
        hf_hub_offline=True,
        transformers_offline=True,
    )

    captioner = build_local_vlm_captioner(settings)
    result = captioner.caption_region(image_path, {"page_no": 1})

    assert result.text == "blue chart with approval labels"
    assert result.status == "ok"
    assert result.locality.runtime_network_calls == 0
    assert result.locality.automatic_model_downloads == 0
    assert result.locality.external_provider_fallbacks == 0
    assert result.locality.local_cache_or_install_path == "configured-local-cache"
    assert "adapter-ready" in captioner.profile
    assert calls["processor_path"] == cache
    assert calls["model_path"] == cache
    assert calls["processor_local_only"] is True
    assert calls["model_local_only"] is True
    assert calls["image_mode"] == "RGB"
    assert calls["return_tensors"] == "pt"
    assert calls["skip_special_tokens"] is True
    assert calls["generate_kwargs"]["max_new_tokens"] == 96


def test_smolvlm2_candidate_uses_same_local_caption_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cache = tmp_path / "cache" / "snapshot"
    cache.mkdir(parents=True)
    (cache / "config.json").write_text("{}", encoding="utf-8")
    (cache / "model.safetensors").write_text("weights", encoding="utf-8")
    image_path = tmp_path / "region.png"
    Image.new("RGB", (24, 24), color=(80, 140, 220)).save(image_path)

    class FakeInputs(dict):
        def to(self, device: str):
            return self

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, path: Path, *, local_files_only: bool):
            return cls()

        def apply_chat_template(
            self,
            conversations: list[list[dict]],
            *,
            add_generation_prompt: bool,
            tokenize: bool,
            return_dict: bool,
            return_tensors: str,
        ):
            content = conversations[0][0]["content"]
            image_blocks = [block for block in content if block.get("type") == "image"]
            assert image_blocks[0]["path"] == str(image_path)
            assert add_generation_prompt is True
            assert tokenize is True
            assert return_dict is True
            assert return_tensors == "pt"
            return FakeInputs({"input_ids": [1]})

        def batch_decode(self, generated_ids, **kwargs):
            return ["Assistant: second candidate caption"]

    class FakeModel:
        @classmethod
        def from_pretrained(
            cls,
            path: Path,
            *,
            local_files_only: bool,
            torch_dtype: str,
        ):
            return cls()

        def to(self, device: str):
            return self

        def eval(self):
            return self

        def generate(self, **kwargs):
            return [[1, 2, 3]]

    monkeypatch.setattr(vlm_module, "_auto_processor_cls", lambda: FakeProcessor)
    monkeypatch.setattr(vlm_module, "_auto_model_cls", lambda: FakeModel)
    monkeypatch.setattr(vlm_module, "_runtime_device", lambda: "cpu")
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_vlm_mode="local-vlm",
        pdf_vlm_model_name=vlm_module.SMOLVLM2_500M_CANDIDATE,
        model_cache_dir=str(cache.parent),
        model_local_files_only=True,
        hf_hub_offline=True,
        transformers_offline=True,
    )

    captioner = build_local_vlm_captioner(settings)
    result = captioner.caption_region(image_path, {"page_no": 1})

    assert result.text == "second candidate caption"
    assert result.locality.candidate == vlm_module.SMOLVLM2_500M_CANDIDATE
    assert captioner.profile.startswith(
        f"local-vlm-caption:{vlm_module.SMOLVLM2_500M_CANDIDATE}:"
    )


def test_florence2_candidate_uses_local_remote_code_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cache = tmp_path / "cache" / "snapshot"
    cache.mkdir(parents=True)
    (cache / "config.json").write_text("{}", encoding="utf-8")
    (cache / "model.safetensors").write_text("weights", encoding="utf-8")
    image_path = tmp_path / "region.png"
    Image.new("RGB", (24, 24), color=(80, 140, 220)).save(image_path)
    calls: dict[str, object] = {}

    class FakeInputs(dict):
        def to(self, device: str, torch_dtype=None):
            calls["inputs_device"] = device
            calls["inputs_dtype"] = torch_dtype
            return self

    class FakeProcessor:
        @classmethod
        def from_pretrained(
            cls,
            path: Path,
            *,
            local_files_only: bool,
            trust_remote_code: bool,
        ):
            calls["processor_path"] = path
            calls["processor_local_only"] = local_files_only
            calls["processor_trust_remote_code"] = trust_remote_code
            return cls()

        def __call__(self, *, text: str, images, return_tensors: str):
            calls["task_prompt"] = text
            calls["image_mode"] = images.mode
            calls["input_size"] = images.size
            calls["return_tensors"] = return_tensors
            return FakeInputs({"input_ids": [1], "pixel_values": [2]})

        def batch_decode(self, generated_ids, **kwargs):
            calls["skip_special_tokens"] = kwargs["skip_special_tokens"]
            return ["raw generated caption"]

        def post_process_generation(self, text: str, *, task: str, image_size: tuple):
            calls["post_process_text"] = text
            calls["post_process_task"] = task
            calls["image_size"] = image_size
            return {task: "florence detailed caption"}

    class FakeModel:
        @classmethod
        def from_pretrained(
            cls,
            path: Path,
            *,
            local_files_only: bool,
            trust_remote_code: bool,
            torch_dtype,
            attn_implementation: str,
        ):
            calls["model_path"] = path
            calls["model_local_only"] = local_files_only
            calls["model_trust_remote_code"] = trust_remote_code
            calls["torch_dtype"] = torch_dtype
            calls["attn_implementation"] = attn_implementation
            return cls()

        def to(self, device: str):
            calls["model_device"] = device
            return self

        def eval(self):
            calls["eval"] = True
            return self

        def generate(self, **kwargs):
            calls["generate_kwargs"] = kwargs
            return [[1, 2, 3]]

    monkeypatch.setattr(vlm_module, "_auto_processor_cls", lambda: FakeProcessor)
    monkeypatch.setattr(vlm_module, "_auto_causal_lm_cls", lambda: FakeModel)
    monkeypatch.setattr(vlm_module, "_runtime_device", lambda: "cpu")
    monkeypatch.setattr(vlm_module, "_runtime_torch_dtype", lambda device: "float32")
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_vlm_mode="local-vlm",
        pdf_vlm_model_name=vlm_module.FLORENCE2_BASE_FT_CANDIDATE,
        pdf_vlm_prompt_version="visual-caption-v3-structured-search-fields",
        model_cache_dir=str(cache.parent),
        model_local_files_only=True,
        hf_hub_offline=True,
        transformers_offline=True,
    )

    captioner = build_local_vlm_captioner(settings)
    result = captioner.caption_region(image_path, {"page_no": 1})

    assert result.text == "florence detailed caption"
    assert result.status == "ok"
    assert result.locality.candidate == vlm_module.FLORENCE2_BASE_FT_CANDIDATE
    assert result.locality.runtime_network_calls == 0
    assert result.locality.automatic_model_downloads == 0
    assert result.locality.external_provider_fallbacks == 0
    assert calls["processor_path"] == cache
    assert calls["model_path"] == cache
    assert calls["processor_local_only"] is True
    assert calls["model_local_only"] is True
    assert calls["processor_trust_remote_code"] is True
    assert calls["model_trust_remote_code"] is True
    assert calls["task_prompt"] == "<MORE_DETAILED_CAPTION>"
    assert calls["image_mode"] == "RGB"
    assert calls["input_size"] == (768, 768)
    assert calls["return_tensors"] == "pt"
    assert calls["skip_special_tokens"] is False
    assert calls["attn_implementation"] == "eager"
    assert calls["generate_kwargs"]["max_new_tokens"] == 256
    assert calls["generate_kwargs"]["num_beams"] == 3
    assert calls["generate_kwargs"]["use_cache"] is False
    assert calls["post_process_task"] == "<MORE_DETAILED_CAPTION>"
    assert calls["image_size"] == (768, 768)


def test_smolvlm_prompt_variant_uses_search_keyword_budget():
    message = vlm_module._caption_messages(
        {"page_no": 2},
        "visual-caption-v2-search-keywords",
    )[0]
    text = message["content"][1]["text"]

    assert "page 2" in text
    assert "search phrases" in text
    assert "visible text exactly" in text
    assert vlm_module._max_new_units("visual-caption-v2-search-keywords") == 128
    assert vlm_module._max_new_units("visual-caption-v1") == 96


def test_smolvlm_repair_prompt_uses_structured_search_fields():
    message = vlm_module._caption_messages(
        {"page_no": 3},
        "visual-caption-v3-structured-search-fields",
    )[0]
    text = message["content"][1]["text"]

    assert "page 3" in text
    assert "semicolon-separated fields" in text
    assert "document_type" in text
    assert "visible_text" in text
    assert "distinguishing_details" in text
    assert "Korean or English text" in text
    assert "receipt totals or line items" in text
    assert vlm_module._max_new_units("visual-caption-v3-structured-search-fields") == 192


def test_smolvlm_repair_prompt_can_extend_v2_generation_budget():
    v2 = vlm_module._caption_messages(
        {"page_no": 4},
        "visual-caption-v2-search-keywords",
    )[0]["content"][1]["text"]
    v2_long = vlm_module._caption_messages(
        {"page_no": 4},
        "visual-caption-v2-search-keywords-long",
    )[0]["content"][1]["text"]

    assert v2_long == v2
    assert vlm_module._max_new_units("visual-caption-v2-search-keywords") == 128
    assert vlm_module._max_new_units("visual-caption-v2-search-keywords-long") == 192
    assert vlm_module._florence2_task_prompt(
        "visual-caption-v2-search-keywords-long"
    ) == "<MORE_DETAILED_CAPTION>"
    assert vlm_module._florence2_max_new_units(
        "visual-caption-v2-search-keywords-long"
    ) == 256


def test_smolvlm_captioner_reuses_local_runtime_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cache = tmp_path / "cache" / "snapshot"
    cache.mkdir(parents=True)
    (cache / "config.json").write_text("{}", encoding="utf-8")
    (cache / "model.safetensors").write_text("weights", encoding="utf-8")
    image_path = tmp_path / "region.png"
    Image.new("RGB", (24, 24), color=(80, 140, 220)).save(image_path)
    vlm_module._SMOLVLM_RUNTIME_CACHE.clear()
    calls = {"processor_loads": 0, "model_loads": 0}

    class FakeInputs(dict):
        def to(self, device: str):
            return self

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, path: Path, *, local_files_only: bool):
            calls["processor_loads"] += 1
            return cls()

        def apply_chat_template(self, messages: list[dict], *, add_generation_prompt: bool):
            return "prompt"

        def __call__(self, *, text: str, images: list, return_tensors: str):
            return FakeInputs({"input_ids": [1]})

        def batch_decode(self, generated_ids, **kwargs):
            return ["Assistant: cached caption"]

    class FakeModel:
        @classmethod
        def from_pretrained(
            cls,
            path: Path,
            *,
            local_files_only: bool,
            torch_dtype: str,
        ):
            calls["model_loads"] += 1
            return cls()

        def to(self, device: str):
            return self

        def eval(self):
            return self

        def generate(self, **kwargs):
            return [[1, 2, 3]]

    monkeypatch.setattr(vlm_module, "_auto_processor_cls", lambda: FakeProcessor)
    monkeypatch.setattr(vlm_module, "_auto_model_cls", lambda: FakeModel)
    monkeypatch.setattr(vlm_module, "_runtime_device", lambda: "cpu")
    settings = Settings(
        data_dir=tmp_path / "data",
        pdf_vlm_mode="local-vlm",
        pdf_vlm_model_name=vlm_module.SMOLVLM_256M_CANDIDATE,
        model_cache_dir=str(cache.parent),
        model_local_files_only=True,
        hf_hub_offline=True,
        transformers_offline=True,
    )

    first = build_local_vlm_captioner(settings)
    second = build_local_vlm_captioner(settings)
    assert first.caption_region(image_path, {}).text == "cached caption"
    assert second.caption_region(image_path, {}).text == "cached caption"

    assert calls == {"processor_loads": 1, "model_loads": 1}


def test_pdf_vlm_mode_change_forces_reindex_and_stale_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "visual.pdf")
    base_settings = Settings(data_dir=tmp_path / "data")
    vlm_settings = Settings(
        data_dir=tmp_path / "data",
        pdf_vlm_mode="local-vlm",
        pdf_vlm_model_name="fixture-captioner",
    )
    store = QdrantStore(base_settings, in_memory=True)
    manifest = ManifestStore(base_settings.manifest_path)
    monkeypatch.setattr(
        pdf_module,
        "build_local_vlm_captioner",
        lambda settings: FakeCaptioner(),
    )

    first = SyncService(base_settings, store=store, manifest=manifest).sync_folder(source)
    second = SyncService(vlm_settings, store=store, manifest=manifest).sync_folder(source)
    caption_payloads = [
        record["payload"]
        for record in store.payload_records()
        if record["payload"].get("unit_type") == "pdf_visual_caption"
    ]
    third = SyncService(base_settings, store=store, manifest=manifest).sync_folder(source)
    remaining_caption_payloads = [
        record["payload"]
        for record in store.payload_records()
        if record["payload"].get("unit_type") == "pdf_visual_caption"
    ]

    assert first.added == 1
    assert second.updated == 1
    assert second.vlm_attempted == 1
    assert second.vlm_succeeded == 1
    assert second.vlm_empty == 0
    assert caption_payloads
    assert caption_payloads[0]["has_text_vector"] is True
    assert caption_payloads[0]["has_vision_vector"] is False
    assert caption_payloads[0]["locality"]["runtime_network_calls"] == 0
    assert caption_payloads[0]["locality"]["automatic_model_downloads"] == 0
    assert caption_payloads[0]["locality"]["external_provider_fallbacks"] == 0
    assert third.updated == 1
    assert remaining_caption_payloads == []


def _write_pdf_with_image(path: Path) -> None:
    image_bytes = _png_bytes()
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_text((36, 36), "Local visual caption evidence page")
    page.insert_image(fitz.Rect(72, 72, 168, 168), stream=image_bytes)
    doc.save(str(path))
    doc.close()


def _png_bytes() -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", (80, 80), color=(80, 140, 220))
    image.save(buffer, format="PNG")
    return buffer.getvalue()
