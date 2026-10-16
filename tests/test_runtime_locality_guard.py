from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.ocrtable_guard_binding import paddleocr_model_cache_fingerprint
import benchmarks.runtime_locality_guard as guard


def test_runtime_guard_passes_when_probe_has_no_network_or_cache_mutation(
    tmp_path: Path,
):
    cache = tmp_path / "cache"
    cache.mkdir()
    probe = tmp_path / "probe.py"
    probe.write_text("print('probe ok')\n", encoding="utf-8")

    report = guard.run_runtime_locality_guard(
        candidate="paddleocr-table",
        cache_paths=[cache],
        probe_script=probe,
        timeout_seconds=5,
    )

    assert report["status"] == "passed"
    assert report["offline_gate"]["verification"] == "measured-runtime-guard"
    assert report["offline_gate"]["runtime_network_calls"] == 0
    assert report["offline_gate"]["automatic_model_downloads"] == 0
    assert report["offline_gate"]["external_provider_fallbacks"] == 0
    assert report["offline_gate"]["passed"] is True
    assert report["promotion_decision"] == "ready-for-isolated-poc"
    assert str(tmp_path) not in str(report)


def test_runtime_guard_holds_when_probe_attempts_network(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import socket\n"
        "sock = socket.socket()\n"
        "sock.connect(('example.com', 80))\n",
        encoding="utf-8",
    )

    report = guard.run_runtime_locality_guard(
        candidate="paddleocr-table",
        cache_paths=[cache],
        probe_script=probe,
        timeout_seconds=5,
    )

    assert report["status"] == "hold"
    assert report["offline_gate"]["runtime_network_calls"] == 1
    assert report["offline_gate"]["external_provider_fallbacks"] == 1
    assert "runtime_network_calls_not_zero" in report["hold_reasons"]
    assert "external_provider_fallbacks_not_zero" in report["hold_reasons"]
    assert report["release_claim_allowed"] is False
    assert str(tmp_path) not in str(report)


def test_runtime_guard_holds_when_probe_mutates_cache(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "cache = Path(os.environ['LOCALLENS_RUNTIME_GUARD_CACHE_1'])\n"
        "(cache / 'created-model-file.bin').write_text('model bytes')\n",
        encoding="utf-8",
    )

    report = guard.run_runtime_locality_guard(
        candidate="paddleocr-table",
        cache_paths=[cache],
        probe_script=probe,
        timeout_seconds=5,
    )

    assert report["status"] == "hold"
    assert report["offline_gate"]["runtime_network_calls"] == 0
    assert report["offline_gate"]["automatic_model_downloads"] == 1
    assert report["cache_observation"]["created_or_changed_entries"] == 1
    assert "automatic_model_downloads_not_zero" in report["hold_reasons"]
    assert str(tmp_path) not in str(report)


def test_runtime_guard_holds_when_probe_writes_to_cwd(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    probe = tmp_path / "probe.py"
    probe.write_text(
        "from pathlib import Path\n"
        "Path.cwd().joinpath('unexpected-write.bin').write_text('bytes')\n",
        encoding="utf-8",
    )

    report = guard.run_runtime_locality_guard(
        candidate="paddleocr-table",
        cache_paths=[cache],
        probe_script=probe,
        timeout_seconds=5,
    )

    assert report["status"] == "hold"
    assert report["offline_gate"]["automatic_model_downloads"] == 1
    assert "automatic_model_downloads_not_zero" in report["hold_reasons"]
    assert not (Path.cwd() / "unexpected-write.bin").exists()
    assert str(tmp_path) not in str(report)


def test_runtime_guard_records_probe_failure_without_raw_output(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    probe = tmp_path / "probe.py"
    probe.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    report = guard.run_runtime_locality_guard(
        candidate="paddleocr-table",
        cache_paths=[cache],
        probe_script=probe,
        timeout_seconds=5,
    )

    assert report["status"] == "hold"
    assert "probe_failed" in report["hold_reasons"]
    assert report["probe"]["stdout_sha256"]
    assert report["probe"]["stderr_sha256"]
    assert "boom" not in str(report)
    assert str(tmp_path) not in str(report)


def test_runtime_guard_holds_builtin_import_probe_as_not_poc_ready():
    report = guard.run_runtime_locality_guard(
        candidate="local-vlm-caption",
        timeout_seconds=5,
    )

    assert report["status"] == "hold"
    assert report["probe"]["level"] == "import"
    assert report["probe"]["readiness_probe"] is False
    assert "runtime_readiness_probe_required" in report["hold_reasons"]
    assert report["promotion_decision"] == "hold"


def test_runtime_guard_holds_without_configured_cache_path(tmp_path: Path):
    probe = tmp_path / "probe.py"
    probe.write_text("print('ready')\n", encoding="utf-8")

    report = guard.run_runtime_locality_guard(
        candidate="paddleocr-table",
        cache_paths=[],
        probe_script=probe,
        timeout_seconds=5,
    )

    assert report["status"] == "hold"
    assert report["offline_gate"]["local_cache_or_install_path"] == "cache-missing"
    assert report["offline_gate"]["passed"] is False
    assert "cache_path_not_configured" in report["hold_reasons"]


def test_runtime_guard_rejects_non_scanned_failure_artifact_format(tmp_path: Path):
    with pytest.raises(ValueError):
        guard.run_runtime_locality_guard(
            candidate="paddleocr-table",
            cache_paths=[tmp_path],
            failure_artifact_format="csv",
        )


def test_runtime_guard_cli_writes_sanitized_report(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    probe = tmp_path / "probe.py"
    output = tmp_path / "guard.json"
    probe.write_text("print('ok')\n", encoding="utf-8")

    exit_code = guard.main(
        [
            "--candidate",
            "paddleocr-table",
            "--cache-path",
            str(cache),
            "--probe-script",
            str(probe),
            "--out",
            str(output),
        ]
    )

    content = output.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "measured-runtime-guard" in content
    assert str(tmp_path) not in content


def test_runtime_guard_records_model_binding_without_raw_path(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    probe = tmp_path / "probe.py"
    probe.write_text("print('ready')\n", encoding="utf-8")

    report = guard.run_runtime_locality_guard(
        candidate="paddleocr-table",
        cache_paths=[cache],
        detector_model_id="PP-OCRv5_mobile_det",
        recognizer_model_id="en_PP-OCRv5_mobile_rec",
        model_cache_fingerprint="cache-fingerprint",
        probe_script=probe,
        timeout_seconds=5,
    )

    assert report["status"] == "passed"
    assert report["model_binding"] == {
        "schema_version": "ocrtable-guard-binding-v1",
        "candidate": "paddleocr-table",
        "detector_model_id": "PP-OCRv5_mobile_det",
        "recognizer_model_id": "en_PP-OCRv5_mobile_rec",
        "model_cache_fingerprint": "cache-fingerprint",
        "binding_present": True,
    }
    assert str(tmp_path) not in str(report)


def test_runtime_guard_constructor_probe_accepts_explicit_paddleocr_model_dirs(
    tmp_path: Path,
):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    fake_paddleocr = scratch / "paddleocr.py"
    fake_paddleocr.write_text(
        "class PaddleOCR:\n"
        "    def __init__(self, **kwargs):\n"
        "        assert kwargs['text_detection_model_name'] == 'det'\n"
        "        assert kwargs['text_recognition_model_name'] == 'rec'\n"
        "        assert kwargs['text_detection_model_dir'].endswith('det')\n"
        "        assert kwargs['text_recognition_model_dir'].endswith('rec')\n"
        "        assert kwargs['device'] == 'cpu'\n",
        encoding="utf-8",
    )
    (scratch / "paddle.py").write_text("VERSION = 'fake'\n", encoding="utf-8")
    model_cache = tmp_path / "model-cache"
    _model_dir(model_cache, "det", "det-yaml")
    _model_dir(model_cache, "rec", "rec-yaml")
    fingerprint = paddleocr_model_cache_fingerprint(
        model_cache=model_cache,
        detector_model_id="det",
        recognizer_model_id="rec",
    )

    report = guard.run_runtime_locality_guard(
        candidate="paddleocr-table",
        cache_paths=[model_cache],
        detector_model_id="det",
        recognizer_model_id="rec",
        model_cache_fingerprint=fingerprint,
        paddleocr_model_cache=model_cache,
        paddleocr_det_model="det",
        paddleocr_rec_model="rec",
        probe_level="constructor",
        scratch_dir=scratch,
        timeout_seconds=5,
    )

    assert report["status"] == "passed"
    assert report["probe"]["readiness_probe"] is True
    assert report["offline_gate"]["automatic_model_downloads"] == 0
    assert report["model_binding"]["model_cache_fingerprint"] == fingerprint
    assert str(tmp_path) not in str(report)


def _model_dir(root: Path, name: str, content: str) -> Path:
    model_dir = root / name
    model_dir.mkdir(parents=True)
    (model_dir / "inference.yml").write_text(content, encoding="utf-8")
    return model_dir
