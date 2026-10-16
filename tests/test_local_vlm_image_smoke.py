from __future__ import annotations

from pathlib import Path

import benchmarks.local_vlm_image_smoke as smoke
from locallens.core.config import Settings
from locallens.core.types import LocalityReport
from locallens.extractors.pdf_vlm_adapter import CaptionResult


Image = __import__("pytest").importorskip("PIL.Image")


class FixtureCaptioner:
    @property
    def profile(self) -> str:
        return "local-vlm-caption:fixture:visual-caption-v1:adapter-ready"

    @property
    def locality(self) -> LocalityReport:
        return LocalityReport(
            runtime_network_calls=0,
            automatic_model_downloads=0,
            local_cache_or_install_path="configured-local-cache",
            external_provider_fallbacks=0,
            candidate="fixture",
            status="adapter-ready",
        )

    def caption_region(self, image_path: Path, metadata: dict) -> CaptionResult:
        assert image_path.exists()
        assert metadata["page_no"] == 1
        return CaptionResult(
            text="Synthetic chart caption for smoke only.",
            status="ok",
            locality=self.locality,
        )


def test_local_vlm_image_smoke_reports_non_empty_without_quality_claim(
    tmp_path: Path,
    monkeypatch,
):
    image_path = tmp_path / "smoke.png"
    Image.new("RGB", (24, 24), color=(80, 140, 220)).save(image_path)
    monkeypatch.setattr(
        smoke,
        "build_local_vlm_captioner",
        lambda settings: FixtureCaptioner(),
    )

    report = smoke.run_local_vlm_image_smoke(
        image_path,
        Settings(pdf_vlm_mode="local-vlm", pdf_vlm_model_name="fixture"),
    )

    assert report["status"] == "passed"
    assert report["caption"]["non_empty"] is True
    assert report["caption"]["chars"] > 0
    assert report["quality"] == {
        "status": "not-evaluated",
        "recall_at_5": None,
        "mrr_at_10": None,
        "p50_ms": None,
        "p95_ms": None,
    }
    assert report["promotion_decision"] == "hold"
    assert report["release_claim_allowed"] is False
    assert report["fixture"]["path_reported"] is False
    assert report["locality"]["runtime_network_calls"] == 0
    assert report["locality"]["automatic_model_downloads"] == 0
    assert report["locality"]["external_provider_fallbacks"] == 0


def test_local_vlm_image_smoke_main_writes_scan_safe_report(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "smoke.png"
    out_path = tmp_path / "smoke.json"
    Image.new("RGB", (24, 24), color=(80, 140, 220)).save(image_path)
    monkeypatch.setattr(
        smoke,
        "build_local_vlm_captioner",
        lambda settings: FixtureCaptioner(),
    )

    exit_code = smoke.main([str(image_path), "--out", str(out_path)])

    content = out_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "not-evaluated" in content
    assert str(tmp_path) not in content
