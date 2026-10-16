from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from locallens.core.config import Settings
from locallens.ingestion.scanner import Scanner


def test_scanner_reports_included_and_excluded_files(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("hello")
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.txt").write_text("ignored")

    report = Scanner(Settings()).scan(tmp_path)

    assert [file.relative_path for file in report.files] == ["notes.txt"]
    assert any(item.relative_path == ".env" for item in report.excluded)
    assert any(item.relative_path == "node_modules" for item in report.excluded)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior only")
def test_scanner_blocks_windows_junction_outside_selected_root(tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    junction = root / "linked"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("outside content")

    _create_junction_or_skip(junction, outside)

    report = Scanner(Settings()).scan(root)

    assert not report.files
    assert any(
        item.relative_path == "linked" and item.reason == "junction directory"
        for item in report.excluded
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior only")
def test_scanner_blocks_windows_junction_inside_selected_root(tmp_path: Path):
    root = tmp_path / "root"
    actual = root / "actual"
    junction = root / "linked"
    actual.mkdir(parents=True)
    (actual / "inside.txt").write_text("inside content")
    _create_junction_or_skip(junction, actual)

    report = Scanner(Settings()).scan(root)

    assert [file.relative_path for file in report.files] == ["actual/inside.txt"]
    assert any(
        item.relative_path == "linked" and item.reason == "junction directory"
        for item in report.excluded
    )


def _create_junction_or_skip(junction: Path, target: Path) -> None:
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip(f"junction creation unavailable: {completed.stderr}")
