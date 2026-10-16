from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from benchmarks.ocrtable_guard_binding import guard_binding_payload
from benchmarks.ocrtable_guard_binding import paddleocr_model_cache_fingerprint
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


CANDIDATE_PRESETS = {
    "paddleocr-table": {
        "runtime_family": "ocr-table-structure",
        "required_modules": ["paddleocr", "paddle"],
        "default_probe": "import",
    },
    "table-transformer": {
        "runtime_family": "table-detector",
        "required_modules": ["transformers", "torch"],
        "default_probe": "import",
    },
    "local-vlm-caption": {
        "runtime_family": "visual-caption",
        "required_modules": [],
        "default_probe": "import",
    },
}

SAFE_FAILURE_ARTIFACT_FORMATS = {"json", "md"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="runtime-locality-guard")
    parser.add_argument("--candidate", required=True, choices=sorted(CANDIDATE_PRESETS))
    parser.add_argument("--cache-path", action="append", default=[])
    parser.add_argument("--detector-model-id", default=None)
    parser.add_argument("--recognizer-model-id", default=None)
    parser.add_argument("--model-cache-fingerprint", default=None)
    parser.add_argument("--paddleocr-model-cache", default=None)
    parser.add_argument("--paddleocr-det-model", default=None)
    parser.add_argument("--paddleocr-rec-model", default=None)
    parser.add_argument("--paddleocr-enable-mkldnn", action="store_true")
    parser.add_argument("--paddleocr-cpu-threads", type=int, default=0)
    parser.add_argument("--probe-script", default=None)
    parser.add_argument("--scratch-dir", default=None)
    parser.add_argument(
        "--probe-level",
        default=None,
        choices=("import", "constructor"),
        help="Candidate built-in probe level when --probe-script is not provided.",
    )
    parser.add_argument(
        "--failure-artifact-format",
        default="json",
        choices=sorted(SAFE_FAILURE_ARTIFACT_FORMATS),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--out", default=None)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)
    cache_paths = [Path(path) for path in args.cache_path]
    detector_model_id = args.detector_model_id or args.paddleocr_det_model
    recognizer_model_id = args.recognizer_model_id or args.paddleocr_rec_model
    model_cache_fingerprint = args.model_cache_fingerprint
    if (
        not model_cache_fingerprint
        and args.paddleocr_model_cache
        and detector_model_id
        and recognizer_model_id
    ):
        model_cache_fingerprint = paddleocr_model_cache_fingerprint(
            model_cache=Path(args.paddleocr_model_cache),
            detector_model_id=detector_model_id,
            recognizer_model_id=recognizer_model_id,
        )
    if args.paddleocr_model_cache:
        cache_paths.append(Path(args.paddleocr_model_cache))

    report = run_runtime_locality_guard(
        candidate=args.candidate,
        cache_paths=cache_paths,
        detector_model_id=detector_model_id,
        recognizer_model_id=recognizer_model_id,
        model_cache_fingerprint=model_cache_fingerprint,
        paddleocr_model_cache=Path(args.paddleocr_model_cache)
        if args.paddleocr_model_cache
        else None,
        paddleocr_det_model=args.paddleocr_det_model,
        paddleocr_rec_model=args.paddleocr_rec_model,
        paddleocr_enable_mkldnn=args.paddleocr_enable_mkldnn,
        paddleocr_cpu_threads=args.paddleocr_cpu_threads,
        probe_script=Path(args.probe_script) if args.probe_script else None,
        scratch_dir=Path(args.scratch_dir) if args.scratch_dir else None,
        probe_level=args.probe_level,
        failure_artifact_format=args.failure_artifact_format,
        timeout_seconds=args.timeout,
    )
    content = json.dumps(report, indent=2)
    findings = scan_text_artifact(
        content,
        args.out or "runtime-locality-guard",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    if findings:
        print(
            json.dumps(
                {"error": "artifact scan failed", "findings": public_findings(findings)},
                indent=2,
            )
        )
        return 1
    if args.out:
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    print(content)
    return 0


def run_runtime_locality_guard(
    *,
    candidate: str,
    cache_paths: list[Path] | None = None,
    detector_model_id: str | None = None,
    recognizer_model_id: str | None = None,
    model_cache_fingerprint: str | None = None,
    paddleocr_model_cache: Path | None = None,
    paddleocr_det_model: str | None = None,
    paddleocr_rec_model: str | None = None,
    paddleocr_enable_mkldnn: bool = False,
    paddleocr_cpu_threads: int = 0,
    probe_script: Path | None = None,
    probe_level: str | None = None,
    scratch_dir: Path | None = None,
    failure_artifact_format: str = "json",
    timeout_seconds: float = 30.0,
    python_executable: str = sys.executable,
) -> dict:
    if failure_artifact_format not in SAFE_FAILURE_ARTIFACT_FORMATS:
        raise ValueError("failure artifact format must be json or md")
    preset = CANDIDATE_PRESETS[candidate]
    cache_paths = list(cache_paths or [])
    with _scratch_context(scratch_dir) as active_scratch:
        effective_probe_level = probe_level or str(preset["default_probe"])
        monitored_paths = cache_paths + [active_scratch]
        before_snapshot = _snapshot_cache_paths(monitored_paths)
        completed = _run_probe(
            candidate=candidate,
            required_modules=list(preset["required_modules"]),
            probe_script=probe_script,
            probe_level=effective_probe_level,
            cache_paths=cache_paths,
            scratch_dir=active_scratch,
            paddleocr_model_cache=paddleocr_model_cache,
            paddleocr_det_model=paddleocr_det_model,
            paddleocr_rec_model=paddleocr_rec_model,
            paddleocr_enable_mkldnn=paddleocr_enable_mkldnn,
            paddleocr_cpu_threads=paddleocr_cpu_threads,
            timeout_seconds=timeout_seconds,
            python_executable=python_executable,
        )
        after_snapshot = _snapshot_cache_paths(monitored_paths)
        cache_mutation_count = _cache_mutation_count(before_snapshot, after_snapshot)
    probe_result = _decode_probe_result(completed)
    runtime_network_calls = int(probe_result.get("runtime_network_calls", 0))
    explicit_download_attempts = int(probe_result.get("automatic_model_downloads", 0))
    external_provider_fallbacks = int(probe_result.get("external_provider_fallbacks", 0))
    automatic_model_downloads = explicit_download_attempts + cache_mutation_count
    hold_reasons = _guard_hold_reasons(
        completed,
        runtime_network_calls=runtime_network_calls,
        automatic_model_downloads=automatic_model_downloads,
        external_provider_fallbacks=external_provider_fallbacks,
        readiness_probe=probe_script is not None or effective_probe_level == "constructor",
        cache_status=_cache_status(cache_paths),
    )
    status = "passed" if not hold_reasons else "hold"
    return {
        "candidate": candidate,
        "runtime_family": preset["runtime_family"],
        "status": status,
        "default_enabled": False,
        "offline_gate": {
            "runtime_network_calls": runtime_network_calls,
            "automatic_model_downloads": automatic_model_downloads,
            "external_provider_fallbacks": external_provider_fallbacks,
            "verification": "measured-runtime-guard",
            "local_cache_or_install_path": _cache_status(cache_paths),
            "passed": status == "passed",
        },
        "probe": {
            "level": effective_probe_level,
            "readiness_probe": probe_script is not None or effective_probe_level == "constructor",
            "exit_code": completed.returncode,
            "stdout_bytes": len(completed.stdout or ""),
            "stderr_bytes": len(completed.stderr or ""),
            "stdout_sha256": _digest(completed.stdout),
            "stderr_sha256": _digest(completed.stderr),
            "result_detected": bool(probe_result),
        },
        "cache_observation": {
            "paths_configured": len(cache_paths),
            "scratch_isolated": True,
            "created_or_changed_entries": cache_mutation_count,
            "absolute_paths_reported": False,
        },
        "model_binding": guard_binding_payload(
            candidate=candidate,
            detector_model_id=detector_model_id,
            recognizer_model_id=recognizer_model_id,
            model_cache_fingerprint_value=model_cache_fingerprint,
        ),
        "failure_artifact_policy": {
            "format": failure_artifact_format,
            "scan_safe": failure_artifact_format in SAFE_FAILURE_ARTIFACT_FORMATS,
            "raw_stdout_stderr_stored": False,
        },
        "promotion_decision": "ready-for-isolated-poc" if status == "passed" else "hold",
        "hold_reasons": hold_reasons,
        "release_claim_allowed": False,
    }


def _run_probe(
    *,
    candidate: str,
    required_modules: list[str],
    probe_script: Path | None,
    probe_level: str,
    cache_paths: list[Path],
    scratch_dir: Path,
    paddleocr_model_cache: Path | None,
    paddleocr_det_model: str | None,
    paddleocr_rec_model: str | None,
    paddleocr_enable_mkldnn: bool,
    paddleocr_cpu_threads: int,
    timeout_seconds: float,
    python_executable: str,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "MODELSCOPE_OFFLINE": "1",
            "LOCALLENS_MODEL_LOCAL_FILES_ONLY": "1",
            "LOCALLENS_RUNTIME_GUARD": "1",
            "LOCALLENS_RUNTIME_GUARD_CANDIDATE": candidate,
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(scratch_dir),
            "USERPROFILE": str(scratch_dir),
            "APPDATA": str(scratch_dir),
            "LOCALAPPDATA": str(scratch_dir),
            "XDG_CACHE_HOME": str(scratch_dir),
            "PADDLE_HOME": str(scratch_dir),
            "PADDLEOCR_HOME": str(scratch_dir),
            "PADDLE_HUB_HOME": str(scratch_dir),
            "PADDLE_DOWNLOAD_DIR": str(scratch_dir),
            "PADDLE_MODEL_HOME": str(scratch_dir),
        }
    )
    for index, path in enumerate(cache_paths, start=1):
        env[f"LOCALLENS_RUNTIME_GUARD_CACHE_{index}"] = str(path)
    if cache_paths:
        env["LOCALLENS_MODEL_CACHE_DIR"] = str(cache_paths[0])
    wrapper_code = _probe_wrapper_code(
        candidate=candidate,
        required_modules=required_modules,
        probe_script=probe_script,
        probe_level=probe_level,
        paddleocr_model_cache=paddleocr_model_cache,
        paddleocr_det_model=paddleocr_det_model,
        paddleocr_rec_model=paddleocr_rec_model,
        paddleocr_enable_mkldnn=paddleocr_enable_mkldnn,
        paddleocr_cpu_threads=paddleocr_cpu_threads,
    )
    try:
        return subprocess.run(
            [python_executable, "-c", wrapper_code],
            cwd=scratch_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=[python_executable, "-c", "<runtime-locality-guard>"],
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "runtime locality guard timed out",
        )


def _probe_wrapper_code(
    *,
    candidate: str,
    required_modules: list[str],
    probe_script: Path | None,
    probe_level: str,
    paddleocr_model_cache: Path | None,
    paddleocr_det_model: str | None,
    paddleocr_rec_model: str | None,
    paddleocr_enable_mkldnn: bool,
    paddleocr_cpu_threads: int,
) -> str:
    payload = {
        "candidate": candidate,
        "required_modules": required_modules,
        "probe_script": str(probe_script) if probe_script else None,
        "probe_level": probe_level,
        "paddleocr_model_cache": str(paddleocr_model_cache)
        if paddleocr_model_cache
        else None,
        "paddleocr_det_model": paddleocr_det_model,
        "paddleocr_rec_model": paddleocr_rec_model,
        "paddleocr_enable_mkldnn": paddleocr_enable_mkldnn,
        "paddleocr_cpu_threads": paddleocr_cpu_threads,
    }
    return f"""
import http.client
import importlib
import json
import runpy
import socket
import urllib.request

payload = json.loads({json.dumps(payload)!r})
network_calls = []
download_attempts = []
fallback_attempts = []

def _record_network(api):
    network_calls.append(api)
    fallback_attempts.append(api)
    raise RuntimeError("runtime locality guard blocked network")

def _record_download(api):
    download_attempts.append(api)
    return _record_network(api)

_original_socket_connect = socket.socket.connect
_original_create_connection = socket.create_connection
_original_urlopen = urllib.request.urlopen
_original_urlretrieve = urllib.request.urlretrieve
_original_http_connect = http.client.HTTPConnection.connect
_original_https_connect = http.client.HTTPSConnection.connect

socket.socket.connect = lambda self, address: _record_network("socket.connect")
socket.create_connection = lambda *args, **kwargs: _record_network("socket.create_connection")
urllib.request.urlopen = lambda *args, **kwargs: _record_download("urllib.request.urlopen")
urllib.request.urlretrieve = lambda *args, **kwargs: _record_download("urllib.request.urlretrieve")
http.client.HTTPConnection.connect = lambda self: _record_network("http.client.HTTPConnection.connect")
http.client.HTTPSConnection.connect = lambda self: _record_network("http.client.HTTPSConnection.connect")

try:
    import requests
    requests.sessions.Session.request = lambda self, *args, **kwargs: _record_network("requests.Session.request")
except Exception:
    pass

try:
    if payload["probe_script"]:
        runpy.run_path(payload["probe_script"], run_name="__main__")
    else:
        for module_name in payload["required_modules"]:
            importlib.import_module(module_name)
        if payload["candidate"] == "paddleocr-table" and payload["probe_level"] == "constructor":
            from paddleocr import PaddleOCR
            if payload["paddleocr_model_cache"] and payload["paddleocr_det_model"] and payload["paddleocr_rec_model"]:
                from pathlib import Path

                model_cache = Path(payload["paddleocr_model_cache"])

                def _model_dir(model_name):
                    direct = model_cache / model_name
                    if (direct / "inference.yml").exists():
                        return direct
                    return model_cache / "official_models" / model_name

                runtime_kwargs = {{
                    "device": "cpu",
                    "enable_mkldnn": bool(payload["paddleocr_enable_mkldnn"]),
                }}
                if int(payload["paddleocr_cpu_threads"] or 0) > 0:
                    runtime_kwargs["cpu_threads"] = int(payload["paddleocr_cpu_threads"])
                PaddleOCR(
                    text_detection_model_name=payload["paddleocr_det_model"],
                    text_detection_model_dir=str(_model_dir(payload["paddleocr_det_model"])),
                    text_recognition_model_name=payload["paddleocr_rec_model"],
                    text_recognition_model_dir=str(_model_dir(payload["paddleocr_rec_model"])),
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    **runtime_kwargs,
                )
            else:
                PaddleOCR()
except Exception as exc:
    probe_error = exc.__class__.__name__
else:
    probe_error = None

print("LOCALLENS_RUNTIME_GUARD_RESULT=" + json.dumps({{
    "runtime_network_calls": len(network_calls),
    "automatic_model_downloads": len(download_attempts),
    "external_provider_fallbacks": len(fallback_attempts),
    "probe_error": probe_error,
}}, sort_keys=True))

if probe_error:
    raise SystemExit(2)
"""


def _scratch_context(scratch_dir: Path | None):
    if scratch_dir is not None:
        scratch_dir.mkdir(parents=True, exist_ok=True)
        return _ProvidedScratch(scratch_dir)
    return _TemporaryScratch()


class _ProvidedScratch:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _TemporaryScratch:
    def __enter__(self) -> Path:
        self._manager = tempfile.TemporaryDirectory(prefix="locallens-runtime-guard-")
        return Path(self._manager.__enter__())

    def __exit__(self, exc_type, exc, tb) -> None:
        self._manager.__exit__(exc_type, exc, tb)


def _decode_probe_result(completed: subprocess.CompletedProcess) -> dict:
    marker = "LOCALLENS_RUNTIME_GUARD_RESULT="
    for line in (completed.stdout or "").splitlines():
        if line.startswith(marker):
            try:
                return json.loads(line[len(marker) :])
            except json.JSONDecodeError:
                return {}
    return {}


def _guard_hold_reasons(
    completed: subprocess.CompletedProcess,
    *,
    runtime_network_calls: int,
    automatic_model_downloads: int,
    external_provider_fallbacks: int,
    readiness_probe: bool,
    cache_status: str,
) -> list[str]:
    reasons: list[str] = []
    if not _decode_probe_result(completed):
        reasons.append("probe_result_missing")
    if completed.returncode != 0:
        reasons.append("probe_failed")
    if not readiness_probe:
        reasons.append("runtime_readiness_probe_required")
    if cache_status == "cache-missing":
        reasons.append("cache_path_not_configured")
    if runtime_network_calls:
        reasons.append("runtime_network_calls_not_zero")
    if automatic_model_downloads:
        reasons.append("automatic_model_downloads_not_zero")
    if external_provider_fallbacks:
        reasons.append("external_provider_fallbacks_not_zero")
    return reasons


def _snapshot_cache_paths(cache_paths: list[Path]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for index, root in enumerate(cache_paths, start=1):
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            label = f"cache-{index}:{path.relative_to(root).as_posix()}"
            snapshot[label] = f"{path.stat().st_size}:{path.stat().st_mtime_ns}"
    return snapshot


def _cache_mutation_count(before: dict[str, str], after: dict[str, str]) -> int:
    changed = 0
    for label, value in after.items():
        if before.get(label) != value:
            changed += 1
    return changed


def _cache_status(cache_paths: list[Path]) -> str:
    if not cache_paths:
        return "cache-missing"
    if any(path.exists() for path in cache_paths):
        return "configured-local-cache"
    return "cache-missing"


def _digest(text: str | bytes | None) -> str:
    if text is None:
        raw = b""
    elif isinstance(text, bytes):
        raw = text
    else:
        raw = text.encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
