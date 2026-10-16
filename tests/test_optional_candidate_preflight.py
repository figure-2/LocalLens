from __future__ import annotations

import importlib.util
from pathlib import Path

import benchmarks.optional_candidate_preflight as preflight


def test_optional_preflight_holds_when_dependency_or_cache_missing(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    report = preflight.run_optional_candidate_preflight(
        candidate="paddleocr-table",
        cache_paths=[tmp_path / "missing-cache"],
    )

    assert report["status"] == "hold"
    assert report["offline_gate"]["runtime_network_calls"] == 0
    assert report["offline_gate"]["automatic_model_downloads"] == 0
    assert report["offline_gate"]["external_provider_fallbacks"] == 0
    assert report["offline_gate"]["local_cache_or_install_path"] == "dependency-missing"
    assert report["release_claim_allowed"] is False
    assert "missing_modules:paddleocr,paddle" in report["hold_reasons"]
    assert "cache_path_missing" in report["hold_reasons"]
    assert "offline_verification_missing" in report["hold_reasons"]
    assert str(tmp_path) not in str(report)


def test_optional_preflight_stays_hold_until_runtime_guard_passes(
    monkeypatch,
    tmp_path: Path,
):
    cache = tmp_path / "model-cache"
    cache.mkdir()
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda name: f"{name}-1.0",
    )

    report = preflight.run_optional_candidate_preflight(
        candidate="paddleocr-table",
        cache_paths=[cache],
        offline_verified=True,
    )

    assert report["status"] == "hold"
    assert report["promotion_decision"] == "hold"
    assert report["offline_gate"]["passed"] is False
    assert report["offline_gate"]["verification"] == "static-preflight-only"
    assert report["offline_gate"]["local_cache_or_install_path"] == "configured-local-cache"
    assert report["isolated_poc"]["ready"] is False
    assert report["isolated_poc"]["runtime_guard_required"] is True
    assert report["environment"]["dependency_versions_recorded"] is True
    assert report["checks"]["modules"][0]["version"] == "paddleocr-1.0"
    assert report["hold_reasons"] == ["measured_runtime_guard_missing"]


def test_optional_preflight_holds_without_offline_verification(
    monkeypatch,
    tmp_path: Path,
):
    cache = tmp_path / "model-cache"
    cache.mkdir()
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda name: f"{name}-1.0",
    )

    report = preflight.run_optional_candidate_preflight(
        candidate="paddleocr-table",
        cache_paths=[cache],
    )

    assert report["status"] == "hold"
    assert report["offline_gate"]["verification"] == "static-preflight-only"
    assert "offline_verification_missing" in report["hold_reasons"]


def test_table_transformer_preflight_holds_without_cache_and_offline_verification(
    monkeypatch,
    tmp_path: Path,
):
    cache = tmp_path / "missing-cache"
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda name: f"{name}-1.0",
    )

    report = preflight.run_optional_candidate_preflight(
        candidate="table-transformer",
        cache_paths=[cache],
    )

    assert report["candidate"] == "table-transformer"
    assert report["runtime_family"] == "table-detector"
    assert report["status"] == "hold"
    assert report["offline_gate"]["runtime_network_calls"] == 0
    assert report["offline_gate"]["automatic_model_downloads"] == 0
    assert report["offline_gate"]["external_provider_fallbacks"] == 0
    assert report["offline_gate"]["verification"] == "static-preflight-only"
    assert report["offline_gate"]["local_cache_or_install_path"] == "cache-missing"
    assert report["release_claim_allowed"] is False
    assert "cache_path_missing" in report["hold_reasons"]
    assert "offline_verification_missing" in report["hold_reasons"]
    assert str(tmp_path) not in str(report)


def test_optional_preflight_cli_writes_sanitized_report(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    output = tmp_path / "preflight.json"

    exit_code = preflight.main(
        [
            "--candidate",
            "paddleocr-table",
            "--cache-path",
            str(tmp_path / "missing-cache"),
            "--out",
            str(output),
        ]
    )

    assert exit_code == 0
    content = output.read_text(encoding="utf-8")
    assert "dependency-missing" in content
    assert str(tmp_path) not in content
