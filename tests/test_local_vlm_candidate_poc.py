from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

import pytest

import benchmarks.local_vlm_candidate_poc as poc
import locallens.extractors.pdf_extractor as pdf_module
from benchmarks.local_vlm_candidate_poc import (
    _caption_rerank_diagnostic,
    _hold_status,
    _weak_slice_analysis,
    run_local_vlm_candidate_poc,
)
from locallens.core.config import Settings
from locallens.core.types import ExtractionStats, IndexedUnit, LocalityReport
from locallens.extractors.pdf_vlm_adapter import CaptionResult


fitz = pytest.importorskip("fitz")
Image = pytest.importorskip("PIL.Image")


LOCALITY_READY = {
    "runtime_network_calls": 0,
    "automatic_model_downloads": 0,
    "external_provider_fallbacks": 0,
    "local_cache_or_install_path": "configured-local-cache",
}


def test_local_vlm_hold_status_requires_configured_local_candidate():
    status = _hold_status(
        settings=Settings(pdf_vlm_mode="off"),
        stats=ExtractionStats(),
        caption_units=0,
        locality=LOCALITY_READY,
        has_golden=False,
        quality_passed=False,
    )

    assert status == "hold-unconfigured"


def test_local_vlm_hold_status_distinguishes_zero_captions():
    status = _hold_status(
        settings=Settings(pdf_vlm_mode="local-vlm"),
        stats=ExtractionStats(vlm_attempted=1),
        caption_units=0,
        locality=LOCALITY_READY,
        has_golden=False,
        quality_passed=False,
    )

    assert status == "hold-zero-captions"


def test_local_vlm_hold_status_requires_golden_after_captions():
    status = _hold_status(
        settings=Settings(pdf_vlm_mode="local-vlm"),
        stats=ExtractionStats(vlm_attempted=1, vlm_succeeded=1),
        caption_units=1,
        locality=LOCALITY_READY,
        has_golden=False,
        quality_passed=False,
    )

    assert status == "hold-no-golden"


def test_local_vlm_hold_status_can_mark_candidate_ready():
    status = _hold_status(
        settings=Settings(pdf_vlm_mode="local-vlm"),
        stats=ExtractionStats(vlm_attempted=1, vlm_succeeded=1),
        caption_units=1,
        locality=LOCALITY_READY,
        has_golden=True,
        quality_passed=True,
    )

    assert status == "candidate-ready"


class FixtureCaptioner:
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
        return CaptionResult(
            text="Visual caption: approval chart with blue square.",
            status="ok",
            locality=self.locality,
        )


def test_local_vlm_candidate_poc_evaluates_caption_golden_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "docs"
    source.mkdir()
    _write_pdf_with_image(source / "visual.pdf")
    golden = tmp_path / "golden.json"
    golden.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "id": "caption-approval-chart",
                        "query": "approval chart blue square",
                        "modality": "text",
                        "relevant": [
                            {
                                "relative_path": "visual.pdf",
                                "unit_type": "pdf_visual_caption",
                                "image_no": 0,
                                "max_rank": 5,
                            }
                        ],
                        "tags": ["vlm-caption"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(poc, "build_local_vlm_captioner", lambda settings: FixtureCaptioner())
    monkeypatch.setattr(
        pdf_module,
        "build_local_vlm_captioner",
        lambda settings: FixtureCaptioner(),
    )

    report = run_local_vlm_candidate_poc(
        source,
        Settings(
            data_dir=tmp_path / "data",
            pdf_vlm_mode="local-vlm",
            pdf_vlm_model_name="fixture-captioner",
        ),
        golden_path=golden,
    )

    assert report["unit_counts"]["pdf_visual_caption"] == 1
    assert report["quality"]["evaluated_queries"] == 1
    assert report["quality"]["recall_at_5"] == 1.0
    assert report["quality"]["mrr_at_10"] == 1.0
    assert report["quality"]["p50_ms"] >= 0.0
    assert report["hold_status"] == "candidate-ready"
    assert report["promotion_decision"] == "candidate-ready"
    assert report["comparison_decision"]["decision"] == "candidate-ready-for-baseline-review"
    assert report["weak_slice_analysis"]["top1_failure_count"] == 0
    assert report["rerank_diagnostic"]["product_runtime_change"] is False
    assert report["rerank_diagnostic"]["status"] == "evaluated"


def test_pdf_vlm_caption_golden_fixture_targets_caption_units():
    root = Path(__file__).resolve().parents[1]
    golden = json.loads(
        (
            root
            / "benchmarks"
            / "fixtures"
            / "golden_pdf_vlm_caption_queries.json"
        ).read_text(encoding="utf-8")
    )
    queries = golden["queries"]
    targets = [target for item in queries for target in item.get("relevant", [])]

    assert len(queries) >= 5
    assert {target["unit_type"] for target in targets} == {"pdf_visual_caption"}
    assert all(target["image_no"] == 0 for target in targets)
    assert "vlm-caption" in {tag for item in queries for tag in item.get("tags", [])}


def test_local_vlm_weak_slice_analysis_records_top1_failures():
    quality = {
        "status": "evaluated",
        "evaluated_queries": 2,
        "quality_slices": {
            "tag:receipt": {
                "evaluated_queries": 1,
                "top1_accuracy": 0.0,
                "recall_at_5": 1.0,
                "mrr_at_10": 0.5,
            },
            "tag:diagram": {
                "evaluated_queries": 1,
                "top1_accuracy": 1.0,
                "recall_at_5": 1.0,
                "mrr_at_10": 1.0,
            },
        },
        "query_results": [
            {
                "id": "receipt-query",
                "tags": ["receipt", "scanned-like"],
                "expected_paths": ["receipt.pdf"],
                "first_hit_rank": 2,
                "top_results": [
                    {"rank": 1, "relative_path": "scan.pdf", "score": 0.5},
                    {"rank": 2, "relative_path": "receipt.pdf", "score": 0.5},
                ],
            },
            {
                "id": "diagram-query",
                "tags": ["diagram"],
                "expected_paths": ["diagram.pdf"],
                "first_hit_rank": 1,
                "top_results": [
                    {"rank": 1, "relative_path": "diagram.pdf", "score": 1.0},
                ],
            },
        ],
    }

    analysis = _weak_slice_analysis(quality)

    assert analysis["top1_failure_count"] == 1
    assert analysis["top1_failure_examples"][0]["failure_mode"] == "score-tie"
    assert analysis["weak_slices"][0]["slice"] == "tag:receipt"


def test_caption_rerank_diagnostic_uses_caption_text_not_golden_label():
    units = [
        _caption_unit(
            "a_decoy.pdf",
            "scanned image generic page",
        ),
        _caption_unit(
            "z_receipt.pdf",
            "receipt total amount",
        ),
        _caption_unit(
            "b_decoy.pdf",
            "scanned image visual page",
        ),
    ]
    golden = [
        {
            "id": "receipt-rerank",
            "query": "receipt total scanned image",
            "modality": "text",
            "top_k": 10,
            "relevant": [
                {
                    "relative_path": "z_receipt.pdf",
                    "unit_type": "pdf_visual_caption",
                    "image_no": 0,
                    "max_rank": 5,
                }
            ],
            "tags": ["vlm-caption", "receipt"],
        }
    ]

    diagnostic = _caption_rerank_diagnostic(units, golden)

    assert diagnostic["product_runtime_change"] is False
    assert diagnostic["label_usage"] == "golden labels are used only for scoring"
    assert diagnostic["baseline"]["mrr_at_10"] < diagnostic["candidate"]["mrr_at_10"]
    assert diagnostic["decision"] == "benchmark-improved-hold-for-product"


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
    Image.new("RGB", (80, 80), color=(80, 140, 220)).save(buffer, format="PNG")
    return buffer.getvalue()


def _caption_unit(relative_path: str, text: str) -> IndexedUnit:
    return IndexedUnit(
        workspace_id="workspace",
        root_id="root",
        file_id=relative_path,
        unit_id=relative_path,
        unit_type="pdf_visual_caption",
        relative_path=relative_path,
        mime_type="application/pdf",
        ext=".pdf",
        size_bytes=1,
        mtime_ns=1,
        content_hash="hash",
        page_no=1,
        image_no=0,
        modality="text",
        text=text,
        text_preview=text,
    )
