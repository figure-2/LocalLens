from __future__ import annotations

import subprocess
from pathlib import Path

from locallens.security.release_gate import release_gate_steps
from locallens.security.release_gate import run_release_gate


def _write_terms(path: Path, *terms: str) -> None:
    required = list(terms)
    required.extend(f"absent marker {index}" for index in range(len(required), 6))
    path.write_text("\n".join(required) + "\n", encoding="utf-8")


def test_release_gate_steps_cover_required_checks():
    steps = release_gate_steps(
        python_executable="python",
        blocked_terms_file="terms.txt",
    )

    assert [step.name for step in steps] == [
        "pytest",
        "publication_scan",
        "generated_evidence_scan",
        "evidence_consistency",
        "repo_hygiene_scan",
        "git_diff_check",
        "git_history_scan",
        "worktree_status",
    ]
    assert "--publication-scan" in steps[1].command
    assert "generated_evidence_artifacts.txt" in steps[2].command
    assert "check-evidence-consistency" in steps[3].command
    assert "repo_hygiene_artifacts.txt" in steps[4].command
    assert "--blocked-terms-file" in steps[4].command
    assert steps[5].command == ["git", "diff", "--check"]
    assert steps[6].command[:4] == ["git", "log", "--all", "-p"]
    assert steps[7].command == ["git", "status", "--short"]


def test_release_gate_fails_closed_for_empty_terms(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    terms.write_text("\n# empty\n", encoding="utf-8")

    report = run_release_gate(root=tmp_path, blocked_terms_file=terms)

    assert report["status"] == "failed"
    assert report["steps"] == []
    assert "active blocked term" in report["error"]


def test_release_gate_fails_for_too_small_blocked_term_set(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    terms.write_text("single absent marker\n", encoding="utf-8")

    report = run_release_gate(root=tmp_path, blocked_terms_file=terms)

    assert report["status"] == "failed"
    assert report["steps"] == []
    assert "canonical blocked term set" in report["error"]
    assert "single absent marker" not in report["error"]


def test_release_gate_runs_steps_in_order(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    _write_terms(terms)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command in (
            ["git", "status", "--short"],
            ["git", "diff", "--check"],
        ):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:4] == ["git", "log", "--all", "-p"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="commit message without blocked content",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout='{"findings":[]}', stderr="")

    report = run_release_gate(
        root=tmp_path,
        blocked_terms_file=terms,
        python_executable="python",
        run_command=fake_run,
    )

    assert report["status"] == "passed"
    assert [step["name"] for step in report["steps"]] == [
        "pytest",
        "publication_scan",
        "generated_evidence_scan",
        "evidence_consistency",
        "repo_hygiene_scan",
        "git_diff_check",
        "git_history_scan",
        "worktree_status",
    ]
    assert len(calls) == 8
    assert report["steps"][1]["command"][-1] == "<blocked-terms-file>"
    assert report["steps"][4]["command"][-1] == "<blocked-terms-file>"
    assert report["steps"][6]["stdout_tail"] == "git history scan passed"


def test_release_gate_stops_on_first_failed_step(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    _write_terms(terms)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="failed", stderr="")

    report = run_release_gate(
        root=tmp_path,
        blocked_terms_file=terms,
        python_executable="python",
        run_command=fake_run,
    )

    assert report["status"] == "failed"
    assert len(report["steps"]) == 1
    assert len(calls) == 1


def test_release_gate_stops_when_publication_manifest_scan_fails(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    _write_terms(terms)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "scan-artifacts" in command and "publication_artifacts.txt" in command:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout='{"error":"artifact manifest contains unsafe path"}',
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout='{"findings":[]}', stderr="")

    report = run_release_gate(
        root=tmp_path,
        blocked_terms_file=terms,
        python_executable="python",
        run_command=fake_run,
    )

    assert report["status"] == "failed"
    assert [step["name"] for step in report["steps"]] == ["pytest", "publication_scan"]
    assert len(calls) == 2
    assert "unsafe path" in report["steps"][-1]["stdout_tail"]


def test_release_gate_stops_when_generated_manifest_scan_fails(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    _write_terms(terms)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if (
            "scan-artifacts" in command
            and "generated_evidence_artifacts.txt" in command
        ):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout='{"error":"artifact manifest contains unsafe path"}',
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout='{"findings":[]}', stderr="")

    report = run_release_gate(
        root=tmp_path,
        blocked_terms_file=terms,
        python_executable="python",
        run_command=fake_run,
    )

    assert report["status"] == "failed"
    assert [step["name"] for step in report["steps"]] == [
        "pytest",
        "publication_scan",
        "generated_evidence_scan",
    ]
    assert len(calls) == 3
    assert "unsafe path" in report["steps"][-1]["stdout_tail"]


def test_release_gate_stops_when_evidence_consistency_fails(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    _write_terms(terms)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "check-evidence-consistency" in command:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout='{"status":"failed","findings":[{"reason":"public table claim mismatch"}]}',
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout='{"findings":[]}', stderr="")

    report = run_release_gate(
        root=tmp_path,
        blocked_terms_file=terms,
        python_executable="python",
        run_command=fake_run,
    )

    assert report["status"] == "failed"
    assert [step["name"] for step in report["steps"]] == [
        "pytest",
        "publication_scan",
        "generated_evidence_scan",
        "evidence_consistency",
    ]
    assert len(calls) == 4


def test_release_gate_redacts_git_diff_check_failure(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    _write_terms(terms)

    def fake_run(command, **kwargs):
        if command == ["git", "diff", "--check"]:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="docs/private-note.md:1: trailing whitespace\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout='{"findings":[]}', stderr="")

    report = run_release_gate(
        root=tmp_path,
        blocked_terms_file=terms,
        python_executable="python",
        run_command=fake_run,
    )

    assert report["status"] == "failed"
    assert report["steps"][-1]["name"] == "git_diff_check"
    assert report["steps"][-1]["stdout_tail"] == "git diff check failed"
    assert "private-note" not in report["steps"][-1]["stdout_tail"]


def test_release_gate_fails_when_git_history_contains_blocked_term(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    _write_terms(terms, "release-history-marker")

    def fake_run(command, **kwargs):
        if command in (
            ["git", "status", "--short"],
            ["git", "diff", "--check"],
        ):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:4] == ["git", "log", "--all", "-p"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="commit body mentions release-history-marker",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout='{"findings":[]}', stderr="")

    report = run_release_gate(
        root=tmp_path,
        blocked_terms_file=terms,
        python_executable="python",
        run_command=fake_run,
    )

    assert report["status"] == "failed"
    assert report["steps"][-1]["name"] == "git_history_scan"
    assert report["steps"][-1]["stdout_tail"] == (
        "git history scan found blocked or sensitive content"
    )
    assert "release-history-marker" not in report["steps"][-1]["stdout_tail"]


def test_release_gate_fails_when_worktree_is_dirty(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    _write_terms(terms)

    def fake_run(command, **kwargs):
        if command == ["git", "status", "--short"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=" M docs/release.md\n?? secret-note.txt\n",
                stderr="",
            )
        if command == ["git", "diff", "--check"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:4] == ["git", "log", "--all", "-p"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="commit message without blocked content",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout='{"findings":[]}', stderr="")

    report = run_release_gate(
        root=tmp_path,
        blocked_terms_file=terms,
        python_executable="python",
        run_command=fake_run,
    )

    assert report["status"] == "failed"
    assert report["steps"][-1]["name"] == "worktree_status"
    assert report["steps"][-1]["exit_code"] == 1
    assert report["steps"][-1]["stdout_tail"] == "dirty worktree detected"
    assert "secret-note" not in report["steps"][-1]["stdout_tail"]
