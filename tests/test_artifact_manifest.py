from __future__ import annotations

from pathlib import Path

import pytest

from locallens.security.artifact_manifest import ManifestEntryError
from locallens.security.artifact_manifest import artifact_paths_from_manifest
from locallens.security.artifact_manifest import manifest_entries


def test_manifest_entries_normalize_relative_paths(tmp_path: Path):
    manifest = tmp_path / "release_artifacts.txt"
    manifest.write_text(
        "# comment\ndocs\\release.md\n.locallens/current.json\n",
        encoding="utf-8",
    )

    assert manifest_entries(manifest) == {
        "docs/release.md",
        ".locallens/current.json",
    }


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        ("C:" + "/" + "Users/example/private.md", "drive-letter path"),
        ("C:" + "private.md", "drive-letter path"),
        ("D:" + "folder/report.json", "drive-letter path"),
        ("//" + "server/share/private.md", "UNC path"),
        ("file:" + "///" + "tmp/private.md", "file URI"),
        ("../private.md", "repo escape"),
        (".", "empty path segment"),
    ],
)
def test_manifest_entries_reject_unsafe_paths(
    tmp_path: Path, entry: str, reason: str
):
    manifest = tmp_path / "release_artifacts.txt"
    manifest.write_text(f"{entry}\n", encoding="utf-8")

    with pytest.raises(ManifestEntryError) as exc:
        manifest_entries(manifest)

    assert exc.value.reason == reason
    assert str(exc.value.line_no) == "1"
    assert entry not in str(exc.value)


def test_artifact_paths_from_manifest_keeps_entries_manifest_relative(tmp_path: Path):
    manifest = tmp_path / "release_artifacts.txt"
    manifest.write_text("docs/release.md\n", encoding="utf-8")

    paths = artifact_paths_from_manifest(manifest)

    assert paths == [tmp_path / "docs" / "release.md"]
