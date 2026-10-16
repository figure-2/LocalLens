from __future__ import annotations

import pytest

from benchmarks.ocrtable_cache_keys import (
    canonical_json_hash,
    document_result_key,
    page_key,
    roi_key,
)


def test_canonical_json_hash_is_stable_for_mapping_order():
    left = {
        "schema_version": "ocrtable-cache-v1",
        "stage": "page",
        "render_profile": {"scale": 1.0, "rotation": 0.0},
        "content_hash": "content-hash",
    }
    right = {
        "content_hash": "content-hash",
        "render_profile": {"rotation": 0.0, "scale": 1.0},
        "stage": "page",
        "schema_version": "ocrtable-cache-v1",
    }

    assert canonical_json_hash(left) == canonical_json_hash(right)


def test_page_key_changes_when_render_profile_changes():
    base = _page_key(render_scale=1.0)
    changed = _page_key(render_scale=2.0)

    assert base != changed
    assert base.startswith("ocrtable-cache-v1:page:")


def test_roi_key_changes_when_bbox_changes():
    page = _page_key(render_scale=1.0)

    first = roi_key(
        page_key_value=page,
        normalized_bbox=[0.1, 0.2, 0.8, 0.9],
        roi_transform_profile=_roi_transform_profile(),
        recognizer_profile=_recognizer_profile(),
        postprocess_profile=_postprocess_profile(),
        code_profile="scanned-table-structure-poc-v1",
    )
    second = roi_key(
        page_key_value=page,
        normalized_bbox=[0.1, 0.2, 0.7, 0.9],
        roi_transform_profile=_roi_transform_profile(),
        recognizer_profile=_recognizer_profile(),
        postprocess_profile=_postprocess_profile(),
        code_profile="scanned-table-structure-poc-v1",
    )

    assert first != second
    assert first.startswith("ocrtable-cache-v1:roi:")


def test_document_result_key_preserves_roi_order():
    page = _page_key(render_scale=1.0)
    first_roi = _roi_key(page, [0.1, 0.2, 0.8, 0.9])
    second_roi = _roi_key(page, [0.2, 0.3, 0.7, 0.8])

    first = document_result_key(
        page_key_value=page,
        roi_key_values=[first_roi, second_roi],
        document_assembly_profile={"assembly_version": "assembly-v1"},
        code_profile="scanned-table-structure-poc-v1",
    )
    second = document_result_key(
        page_key_value=page,
        roi_key_values=[second_roi, first_roi],
        document_assembly_profile={"assembly_version": "assembly-v1"},
        code_profile="scanned-table-structure-poc-v1",
    )

    assert first != second
    assert first.startswith("ocrtable-cache-v1:document_result:")


def test_cache_key_rejects_absolute_windows_path():
    absolute_path = "C:" + "\\Users\\operator\\doc.pdf"

    with pytest.raises(ValueError, match="absolute paths"):
        canonical_json_hash(
            {
                "schema_version": "ocrtable-cache-v1",
                "stage": "page",
                "nested": {"cache_path": absolute_path},
            }
        )


def test_cache_key_rejects_absolute_posix_path():
    absolute_path = "/" + "private/cache/model"

    with pytest.raises(ValueError, match="absolute paths"):
        canonical_json_hash(
            {
                "schema_version": "ocrtable-cache-v1",
                "stage": "page",
                "nested": {"cache_path": absolute_path},
            }
        )


def test_page_key_accepts_relative_path_hash_without_raw_path():
    key = page_key(
        workspace_id="poc",
        root_id="root-id",
        file_id="file-id",
        content_hash="content-hash",
        relative_path_hash="sha256-relative-label",
        page_no=1,
        render_profile=_render_profile(1.0),
        detector_profile=_detector_profile("mobile-cache-fingerprint"),
        locality_profile=_locality_profile(),
        code_profile="scanned-table-structure-poc-v1",
    )

    assert key.startswith("ocrtable-cache-v1:page:")


def test_page_key_requires_detector_cache_fingerprint():
    detector_profile = _detector_profile("mobile-cache-fingerprint")
    detector_profile.pop("model_cache_fingerprint")

    with pytest.raises(ValueError, match="model_cache_fingerprint"):
        page_key(
            workspace_id="poc",
            root_id="root-id",
            file_id="file-id",
            content_hash="content-hash",
            relative_path_hash="relative-path-hash",
            page_no=1,
            render_profile=_render_profile(1.0),
            detector_profile=detector_profile,
            locality_profile=_locality_profile(),
            code_profile="scanned-table-structure-poc-v1",
        )


def test_detector_fingerprint_changes_page_key():
    first = _page_key_with_profile(render_scale=1.0, detector_fingerprint="fingerprint-a")
    second = _page_key_with_profile(render_scale=1.0, detector_fingerprint="fingerprint-b")

    assert first != second


def test_locality_profile_rejects_runtime_counters():
    locality_profile = _locality_profile()
    locality_profile["runtime_network_calls"] = 0

    with pytest.raises(ValueError, match="unsupported fields"):
        page_key(
            workspace_id="poc",
            root_id="root-id",
            file_id="file-id",
            content_hash="content-hash",
            relative_path_hash="relative-path-hash",
            page_no=1,
            render_profile=_render_profile(1.0),
            detector_profile=_detector_profile("mobile-cache-fingerprint"),
            locality_profile=locality_profile,
            code_profile="scanned-table-structure-poc-v1",
        )


def test_cache_key_rejects_embedded_absolute_path_fragments():
    with pytest.raises(ValueError, match="absolute paths"):
        canonical_json_hash(
            {
                "schema_version": "ocrtable-cache-v1",
                "stage": "page",
                "profile": {"note": "cache_root=" + "C:" + "\\model-cache"},
            }
        )


def test_cache_key_rejects_file_uri_path():
    file_uri = "file:" + "/" * 3 + "private/cache/model"

    with pytest.raises(ValueError, match="absolute paths"):
        canonical_json_hash(
            {
                "schema_version": "ocrtable-cache-v1",
                "stage": "page",
                "profile": {"uri": file_uri},
            }
        )


def _page_key(*, render_scale: float) -> str:
    return _page_key_with_profile(
        render_scale=render_scale,
        detector_fingerprint="mobile-cache-fingerprint",
    )


def _page_key_with_profile(*, render_scale: float, detector_fingerprint: str) -> str:
    return page_key(
        workspace_id="poc",
        root_id="root-id",
        file_id="file-id",
        content_hash="content-hash",
        relative_path_hash="relative-path-hash",
        page_no=1,
        render_profile=_render_profile(render_scale),
        detector_profile=_detector_profile(detector_fingerprint),
        locality_profile=_locality_profile(),
        code_profile="scanned-table-structure-poc-v1",
    )


def _roi_key(page_key_value: str, bbox: list[float]) -> str:
    return roi_key(
        page_key_value=page_key_value,
        normalized_bbox=bbox,
        roi_transform_profile=_roi_transform_profile(),
        recognizer_profile=_recognizer_profile(),
        postprocess_profile=_postprocess_profile(),
        code_profile="scanned-table-structure-poc-v1",
    )


def _render_profile(render_scale: float) -> dict:
    return {
        "render_scale": render_scale,
        "rotation_degrees": 0.0,
        "color_mode": "RGB",
        "normalization_version": "render-normalize-v1",
    }


def _detector_profile(fingerprint: str) -> dict:
    return {
        "detector_model_id": "PP-OCRv5_mobile_det",
        "model_cache_fingerprint": fingerprint,
        "score_threshold": 0.3,
        "runtime_family": "paddleocr-table",
        "runtime_options": {"device": "cpu", "mkldnn": False, "threads": 0},
    }


def _locality_profile() -> dict:
    return {
        "cache_status": "configured-local-cache",
        "verification": "measured-runtime-guard",
    }


def _roi_transform_profile() -> dict:
    return {
        "bbox_source": "detector-boxes",
        "crop_margin": 0.02,
        "transform_version": "roi-transform-v1",
    }


def _recognizer_profile() -> dict:
    return {
        "recognizer_model_id": "en_PP-OCRv5_mobile_rec",
        "model_cache_fingerprint": "recognizer-cache-fingerprint",
        "score_threshold": 0.3,
    }


def _postprocess_profile() -> dict:
    return {
        "row_grouping_version": "row-grouping-v1",
        "cell_assignment_version": "cell-assignment-v1",
        "table_filter_version": "table-filter-v1",
        "structured_output_version": "structured-output-v1",
    }
