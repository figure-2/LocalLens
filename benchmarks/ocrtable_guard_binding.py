from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

from benchmarks.ocrtable_cache_keys import canonical_json_hash


SCHEMA_VERSION = "ocrtable-guard-binding-v1"
PADDLEOCR_GUARD_CANDIDATE = "paddleocr-table"
MEASURED_RUNTIME_GUARD = "measured-runtime-guard"
CONFIGURED_LOCAL_CACHE = "configured-local-cache"


def paddleocr_model_dir(model_cache: Path, model_name: str) -> Path:
    direct = model_cache / model_name
    if (direct / "inference.yml").exists():
        return direct
    return model_cache / "official_models" / model_name


def paddleocr_model_cache_fingerprint(
    *,
    model_cache: Path,
    detector_model_id: str,
    recognizer_model_id: str,
) -> str:
    return model_cache_fingerprint(
        {
            "detector": paddleocr_model_dir(model_cache, detector_model_id),
            "recognizer": paddleocr_model_dir(model_cache, recognizer_model_id),
        }
    )


def model_cache_fingerprint(model_dirs: Mapping[str, Path]) -> str:
    if not model_dirs:
        raise ValueError("model_dirs must not be empty")
    entries = []
    for role, model_dir in sorted(model_dirs.items()):
        if not role:
            raise ValueError("model role must be a non-empty string")
        inference_file = model_dir / "inference.yml"
        if not inference_file.exists():
            raise FileNotFoundError("model dir must contain inference.yml")
        files = []
        for path in sorted(item for item in model_dir.rglob("*") if item.is_file()):
            files.append(
                {
                    "relative_file": path.relative_to(model_dir).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": _file_digest(path),
                }
            )
        entries.append({"role": role, "files": files})
    return canonical_json_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "stage": "model_cache_fingerprint",
            "models": entries,
        }
    )


def guard_binding_payload(
    *,
    candidate: str = PADDLEOCR_GUARD_CANDIDATE,
    detector_model_id: str | None,
    recognizer_model_id: str | None,
    model_cache_fingerprint_value: str | None,
) -> dict:
    binding_present = all(
        [
            detector_model_id,
            recognizer_model_id,
            model_cache_fingerprint_value,
        ]
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "candidate": candidate,
        "detector_model_id": detector_model_id or "",
        "recognizer_model_id": recognizer_model_id or "",
        "model_cache_fingerprint": model_cache_fingerprint_value or "",
        "binding_present": binding_present,
    }
    canonical_json_hash(payload)
    return payload


def validate_paddleocr_guard_binding(
    guard_report: Mapping | None,
    *,
    detector_model_id: str,
    recognizer_model_id: str,
    model_cache_fingerprint_value: str,
) -> dict:
    expected = guard_binding_payload(
        detector_model_id=detector_model_id,
        recognizer_model_id=recognizer_model_id,
        model_cache_fingerprint_value=model_cache_fingerprint_value,
    )
    reasons = []
    if guard_report is None:
        reasons.append("guard_artifact_missing")
        return _validation_result(expected, reasons, guard_report)

    offline_gate = dict(guard_report.get("offline_gate") or {})
    cache_observation = dict(guard_report.get("cache_observation") or {})
    model_binding = dict(guard_report.get("model_binding") or {})

    if guard_report.get("candidate") != PADDLEOCR_GUARD_CANDIDATE:
        reasons.append("guard_candidate_mismatch")
    if guard_report.get("status") != "passed":
        reasons.append("guard_status_not_passed")
    if offline_gate.get("passed") is not True:
        reasons.append("offline_gate_not_passed")
    if offline_gate.get("verification") != MEASURED_RUNTIME_GUARD:
        reasons.append("runtime_locality_not_measured")
    if offline_gate.get("local_cache_or_install_path") != CONFIGURED_LOCAL_CACHE:
        reasons.append("cache_path_not_configured")
    if int(offline_gate.get("runtime_network_calls") or 0) != 0:
        reasons.append("runtime_network_calls_not_zero")
    if int(offline_gate.get("automatic_model_downloads") or 0) != 0:
        reasons.append("automatic_model_downloads_not_zero")
    if int(offline_gate.get("external_provider_fallbacks") or 0) != 0:
        reasons.append("external_provider_fallbacks_not_zero")
    if int(cache_observation.get("created_or_changed_entries") or 0) != 0:
        reasons.append("cache_mutation_not_zero")
    if cache_observation.get("absolute_paths_reported") is not False:
        reasons.append("absolute_path_observation_not_sanitized")
    if model_binding.get("binding_present") is not True:
        reasons.append("model_binding_missing")
    if model_binding.get("detector_model_id") != detector_model_id:
        reasons.append("detector_model_id_mismatch")
    if model_binding.get("recognizer_model_id") != recognizer_model_id:
        reasons.append("recognizer_model_id_mismatch")
    if model_binding.get("model_cache_fingerprint") != model_cache_fingerprint_value:
        reasons.append("model_cache_fingerprint_mismatch")

    return _validation_result(expected, reasons, guard_report)


def _validation_result(expected: dict, reasons: list[str], guard_report: Mapping | None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "required": True,
        "status": "passed" if not reasons else "failed",
        "expected": expected,
        "guard_candidate": guard_report.get("candidate", "") if guard_report else "",
        "guard_status": guard_report.get("status", "") if guard_report else "",
        "reasons": reasons,
    }


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
