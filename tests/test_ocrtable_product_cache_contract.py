from __future__ import annotations

import json

import pytest

from benchmarks.ocrtable_product_cache_contract import ENTRY_TYPES
from benchmarks.ocrtable_product_cache_contract import SCHEMA_VERSION
from benchmarks.ocrtable_product_cache_contract import build_cache_entry
from benchmarks.ocrtable_product_cache_contract import validate_cache_entry
from benchmarks.ocrtable_product_cache_contract import validate_cache_hit


def test_product_cache_contract_accepts_valid_manifest_bound_entry():
    entry = _entry()

    result = validate_cache_hit(entry, _binding())

    assert result.hit is True
    assert result.reason == "cache-hit"
    assert result.lifecycle_action == "reuse"


@pytest.mark.parametrize("entry_type", sorted(ENTRY_TYPES))
def test_product_cache_contract_accepts_entry_type_specific_envelopes(entry_type: str):
    entry = _entry(entry_type=entry_type)

    result = validate_cache_entry(entry)

    assert result.hit is True
    assert result.reason == "valid"


def test_product_cache_contract_rejects_payload_checksum_mutation():
    entry = _entry()
    entry["payload"]["row_count"] = 99

    result = validate_cache_hit(entry, _binding())

    assert result.hit is False
    assert result.corrupt is True
    assert result.reason == "payload-checksum-mismatch"
    assert result.lifecycle_action == "quarantine"


def test_product_cache_contract_rejects_content_hash_mismatch_as_stale():
    entry = _entry()
    binding = _binding(content_hash="changed-content")

    result = validate_cache_hit(entry, binding)

    assert result.hit is False
    assert result.stale is True
    assert result.reason == "content_hash-mismatch"
    assert result.lifecycle_action == "delete-or-quarantine"


def test_product_cache_contract_rejects_missing_manifest_unit_as_stale():
    entry = _entry()
    binding = _binding(unit_exists=False)

    result = validate_cache_hit(entry, binding)

    assert result.hit is False
    assert result.stale is True
    assert result.reason == "manifest-unit-missing"


def test_product_cache_contract_rejects_detector_profile_mismatch():
    entry = _entry()
    binding = _binding()
    binding["detector_profile"] = {
        **binding["detector_profile"],
        "model_cache_fingerprint": "different-fingerprint",
    }

    result = validate_cache_hit(entry, binding)

    assert result.hit is False
    assert result.stale is True
    assert result.reason == "detector_profile-mismatch"


def test_product_cache_contract_rejects_absolute_path_payload():
    unsafe_path = "C:" + "/" + "Users/example/private-cache"
    with pytest.raises(ValueError, match="absolute paths"):
        _entry(payload={"debug_path": unsafe_path})


def test_product_cache_contract_requires_metadata_envelope():
    result = validate_cache_entry({"payload": {"row_count": 3}})

    assert result.hit is False
    assert result.corrupt is True
    assert result.reason == "invalid-entry-shape"


def test_product_cache_contract_rejects_cache_key_prefix_mismatch():
    entry = _entry()
    entry["metadata"]["cache_key"] = f"{SCHEMA_VERSION}:page_render:wrong"

    result = validate_cache_entry(entry)

    assert result.hit is False
    assert result.corrupt is True
    assert result.reason == "cache-key-prefix-mismatch"


def test_product_cache_contract_rejects_malformed_page_reference_key():
    entry = _entry()
    entry["metadata"]["page_key"] = "not-a-page-key"

    result = validate_cache_hit(entry, _binding())

    assert result.hit is False
    assert result.corrupt is True
    assert result.reason == "page-key-prefix-mismatch"


def test_product_cache_contract_rejects_malformed_roi_reference_key():
    entry = _entry(entry_type="structured_rows")
    entry["metadata"]["roi_key"] = "not-a-roi-key"

    result = validate_cache_hit(entry, _binding())

    assert result.hit is False
    assert result.corrupt is True
    assert result.reason == "roi-key-prefix-mismatch"


def test_product_cache_contract_rejects_malformed_document_result_reference_key():
    entry = _entry()
    entry["metadata"]["document_result_key"] = "not-a-document-result-key"

    result = validate_cache_hit(entry, _binding())

    assert result.hit is False
    assert result.corrupt is True
    assert result.reason == "document-result-key-prefix-mismatch"


def test_product_cache_contract_rejects_missing_document_result_key():
    entry = _entry()
    entry["metadata"]["document_result_key"] = ""
    entry["metadata"]["payload_sha256"] = entry["metadata"]["payload_sha256"]

    result = validate_cache_entry(entry)

    assert result.hit is False
    assert result.corrupt is True
    assert result.reason == "document-result-key-missing"


def test_product_cache_contract_rejects_missing_roi_key_for_structured_rows():
    entry = _entry(entry_type="structured_rows")
    entry["metadata"]["roi_key"] = ""

    result = validate_cache_entry(entry)

    assert result.hit is False
    assert result.corrupt is True
    assert result.reason == "roi-key-missing"


def _entry(payload=None, entry_type: str = "document_result"):
    return build_cache_entry(
        entry_type=entry_type,
        cache_key=f"{SCHEMA_VERSION}:{entry_type}:abc123",
        page_key="ocrtable-cache-v1:page:abc123",
        roi_key="ocrtable-cache-v1:roi:def456",
        document_result_key="ocrtable-cache-v1:document_result:ghi789",
        workspace_id="workspace",
        root_id="root",
        file_id="file",
        unit_id="unit",
        content_hash="content-hash",
        relative_path_hash="relative-path-hash",
        page_no=1,
        extractor_profile={"id": "pdf-render-v1", "render_scale": 0.75},
        detector_profile={
            "id": "PP-OCRv5_mobile_det",
            "model_cache_fingerprint": "fingerprint",
            "threshold": 0.3,
        },
        recognizer_profile={
            "id": "en_PP-OCRv5_mobile_rec",
            "model_cache_fingerprint": "fingerprint",
            "threshold": 0.3,
        },
        postprocess_profile={"id": "scanned-table-structure-poc-v1"},
        locality_profile={"verification": "measured-runtime-guard"},
        code_profile="ocrtable-cache-contract-test-v1",
        payload=payload or {"row_count": 3, "cell_count": 9},
        normalized_bbox=[0.0, 0.0, 1.0, 1.0],
        created_at="2026-06-02T00:00:00Z",
    )


def _binding(**overrides):
    metadata = json.loads(json.dumps(_entry()["metadata"]))
    binding = {
        field: metadata[field]
        for field in (
            "workspace_id",
            "root_id",
            "file_id",
            "unit_id",
            "content_hash",
            "relative_path_hash",
            "page_no",
            "extractor_profile",
            "detector_profile",
            "recognizer_profile",
            "postprocess_profile",
            "locality_profile",
            "code_profile",
        )
    }
    binding["unit_exists"] = True
    binding.update(overrides)
    return binding
