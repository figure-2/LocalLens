from __future__ import annotations

import argparse
import importlib.util
import importlib.metadata
import json
import platform
import subprocess
import shutil
import sys
from pathlib import Path

from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact


CANDIDATE_PRESETS = {
    "paddleocr-table": {
        "required_modules": ["paddleocr", "paddle"],
        "required_commands": [],
        "runtime_family": "ocr-table-structure",
    },
    "table-transformer": {
        "required_modules": ["transformers", "torch"],
        "required_commands": [],
        "runtime_family": "table-detector",
    },
    "local-vlm-caption": {
        "required_modules": [],
        "required_commands": [],
        "runtime_family": "visual-caption",
    },
}

MODULE_VERSION_ALIASES = {
    "paddle": ["paddlepaddle", "paddle"],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="optional-candidate-preflight")
    parser.add_argument("--candidate", required=True, choices=sorted(CANDIDATE_PRESETS))
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--cache-path", action="append", default=[])
    parser.add_argument("--offline-verified", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)

    report = run_optional_candidate_preflight(
        candidate=args.candidate,
        extra_modules=args.module,
        extra_commands=args.command,
        cache_paths=[Path(path) for path in args.cache_path],
        offline_verified=args.offline_verified,
    )
    content = json.dumps(report, indent=2)
    findings = scan_text_artifact(
        content,
        args.out or "optional-candidate-preflight",
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


def run_optional_candidate_preflight(
    *,
    candidate: str,
    extra_modules: list[str] | None = None,
    extra_commands: list[str] | None = None,
    cache_paths: list[Path] | None = None,
    offline_verified: bool = False,
) -> dict:
    preset = CANDIDATE_PRESETS[candidate]
    required_modules = list(preset["required_modules"]) + list(extra_modules or [])
    required_commands = list(preset["required_commands"]) + list(extra_commands or [])
    module_checks = [_module_check(name) for name in required_modules]
    command_checks = [_command_check(name) for name in required_commands]
    cache_checks = [_cache_check(path, index) for index, path in enumerate(cache_paths or [], start=1)]
    hold_reasons = _hold_reasons(
        module_checks,
        command_checks,
        cache_checks,
        offline_verified=offline_verified,
    )
    if not hold_reasons:
        hold_reasons.append("measured_runtime_guard_missing")
    status = "hold"
    return {
        "candidate": candidate,
        "runtime_family": preset["runtime_family"],
        "status": status,
        "default_enabled": False,
        "offline_gate": {
            "runtime_network_calls": 0,
            "automatic_model_downloads": 0,
            "external_provider_fallbacks": 0,
            "verification": "static-preflight-only",
            "local_cache_or_install_path": _locality_status(
                module_checks,
                command_checks,
                cache_checks,
            ),
            "passed": False,
        },
        "isolated_poc": {
            "required": True,
            "dependency_policy": "optional-environment-only",
            "default_dependency_promotion": False,
            "ready": False,
            "runtime_guard_required": True,
        },
        "environment": {
            "python": _python_label(),
            "platform": platform.system(),
            "dependency_versions_recorded": True,
        },
        "checks": {
            "modules": module_checks,
            "commands": command_checks,
            "cache_paths": cache_checks,
        },
        "promotion_decision": "hold",
        "hold_reasons": hold_reasons,
        "release_claim_allowed": False,
    }


def _module_check(name: str) -> dict:
    available = importlib.util.find_spec(name) is not None
    return {
        "name": name,
        "available": available,
        "version": _module_version(name) if available else None,
    }


def _command_check(name: str) -> dict:
    path = shutil.which(name)
    return {
        "name": name,
        "available": path is not None,
        "version": _command_version(name) if path else None,
    }


def _cache_check(path: Path, index: int) -> dict:
    return {
        "label": f"configured-cache-{index}",
        "provided": bool(str(path)),
        "exists": path.exists(),
    }


def _hold_reasons(
    module_checks: list[dict],
    command_checks: list[dict],
    cache_checks: list[dict],
    *,
    offline_verified: bool,
) -> list[str]:
    reasons = []
    missing_modules = [item["name"] for item in module_checks if not item["available"]]
    missing_commands = [item["name"] for item in command_checks if not item["available"]]
    if missing_modules:
        reasons.append("missing_modules:" + ",".join(missing_modules))
    if missing_commands:
        reasons.append("missing_commands:" + ",".join(missing_commands))
    missing_versions = [
        item["name"]
        for item in module_checks
        if item["available"] and not item.get("version")
    ]
    if missing_versions:
        reasons.append("missing_module_versions:" + ",".join(missing_versions))
    if cache_checks and not any(item["exists"] for item in cache_checks):
        reasons.append("cache_path_missing")
    if not cache_checks:
        reasons.append("cache_path_not_provided")
    if not offline_verified:
        reasons.append("offline_verification_missing")
    return reasons


def _locality_status(
    module_checks: list[dict],
    command_checks: list[dict],
    cache_checks: list[dict],
) -> str:
    if any(not item["available"] for item in module_checks):
        return "dependency-missing"
    if any(not item["available"] for item in command_checks):
        return "command-missing"
    if cache_checks and any(item["exists"] for item in cache_checks):
        return "configured-local-cache"
    return "cache-missing"


def _module_version(name: str) -> str | None:
    for package_name in MODULE_VERSION_ALIASES.get(name, [name]):
        try:
            return importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


def _command_version(name: str) -> str | None:
    try:
        completed = subprocess.run(
            [name, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return output[0][:120] if output else None


def _python_label() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


if __name__ == "__main__":
    raise SystemExit(main())
