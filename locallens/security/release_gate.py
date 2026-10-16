from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import scan_text_artifact


RunCommand = Callable[..., subprocess.CompletedProcess]
MIN_ACTIVE_BLOCKED_TERMS = 6


@dataclass(frozen=True)
class ReleaseGateStep:
    name: str
    command: list[str]


def release_gate_steps(
    *,
    python_executable: str = sys.executable,
    blocked_terms_file: str,
    claims_file: str = "release_evidence_claims.json",
) -> list[ReleaseGateStep]:
    return [
        ReleaseGateStep("pytest", [python_executable, "-m", "pytest", "-q"]),
        ReleaseGateStep(
            "publication_scan",
            [
                python_executable,
                "-m",
                "locallens.app.cli",
                "scan-artifacts",
                "--publication-scan",
                "--manifest",
                "publication_artifacts.txt",
                "--blocked-terms-file",
                blocked_terms_file,
            ],
        ),
        ReleaseGateStep(
            "generated_evidence_scan",
            [
                python_executable,
                "-m",
                "locallens.app.cli",
                "scan-artifacts",
                "--publication-scan",
                "--manifest",
                "publication_artifacts.txt",
                "--manifest",
                "generated_evidence_artifacts.txt",
                "--blocked-terms-file",
                blocked_terms_file,
            ],
        ),
        ReleaseGateStep(
            "evidence_consistency",
            [
                python_executable,
                "-m",
                "locallens.app.cli",
                "check-evidence-consistency",
                "--claims-file",
                claims_file,
            ],
        ),
        ReleaseGateStep(
            "repo_hygiene_scan",
            [
                python_executable,
                "-m",
                "locallens.app.cli",
                "scan-artifacts",
                "--manifest",
                "repo_hygiene_artifacts.txt",
                "--blocked-terms-file",
                blocked_terms_file,
            ],
        ),
        ReleaseGateStep("git_diff_check", ["git", "diff", "--check"]),
        ReleaseGateStep(
            "git_history_scan",
            [
                "git",
                "log",
                "--all",
                "-p",
                "--format=%H%n%B",
            ],
        ),
        ReleaseGateStep("worktree_status", ["git", "status", "--short"]),
    ]


def run_release_gate(
    *,
    root: Path,
    blocked_terms_file: str | Path,
    python_executable: str = sys.executable,
    run_command: RunCommand = subprocess.run,
) -> dict:
    active_terms = load_blocked_terms([], blocked_terms_file)
    if not active_terms:
        return {
            "status": "failed",
            "error": "release gate requires at least one active blocked term",
            "steps": [],
        }
    active_term_count = len(
        {term.strip().lower() for term in active_terms if term.strip()}
    )
    if active_term_count < MIN_ACTIVE_BLOCKED_TERMS:
        return {
            "status": "failed",
            "error": "release gate requires a canonical blocked term set",
            "steps": [],
        }
    steps = []
    for step in release_gate_steps(
        python_executable=python_executable,
        blocked_terms_file=str(blocked_terms_file),
    ):
        started = time.perf_counter()
        completed = run_command(
            step.command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        exit_code = completed.returncode
        stdout_tail = _tail(completed.stdout)
        stderr_tail = _tail(completed.stderr)
        if step.name == "git_diff_check" and exit_code != 0:
            stdout_tail = "git diff check failed"
            stderr_tail = ""
        if step.name == "git_history_scan":
            if exit_code == 0:
                history_findings = scan_text_artifact(
                    completed.stdout,
                    "git-history",
                    active_terms,
                )
                if history_findings:
                    exit_code = 1
                    stdout_tail = "git history scan found blocked or sensitive content"
                    stderr_tail = ""
                else:
                    stdout_tail = "git history scan passed"
                    stderr_tail = ""
            else:
                stdout_tail = "git history scan command failed"
                stderr_tail = ""
        if step.name == "worktree_status" and exit_code == 0 and stdout_tail:
            exit_code = 1
            stdout_tail = "dirty worktree detected"
            stderr_tail = ""
        steps.append(
            {
                "name": step.name,
                "command": _public_command(step.command),
                "exit_code": exit_code,
                "duration_ms": elapsed_ms,
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
            }
        )
        if exit_code != 0:
            return {"status": "failed", "steps": steps}
    return {"status": "passed", "steps": steps}


def write_release_gate_report(report: dict, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _public_command(command: list[str]) -> list[str]:
    result = []
    skip_next = False
    for index, part in enumerate(command):
        if skip_next:
            result.append("<blocked-terms-file>")
            skip_next = False
            continue
        if part == "--blocked-terms-file":
            result.append(part)
            skip_next = True
            continue
        if index == 0:
            result.append(Path(part).name or part)
        else:
            result.append(part)
    return result


def _tail(text: str, limit: int = 1200) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[-limit:]
