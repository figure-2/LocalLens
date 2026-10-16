from __future__ import annotations

from pathlib import Path

from locallens.ingestion.exclusion import ExclusionPolicy


def test_excludes_secret_like_files(tmp_path: Path):
    root = tmp_path
    path = root / ".env"
    path.write_text("TOKEN=value")
    policy = ExclusionPolicy()

    assert policy.should_skip_file(path, root) == "excluded file pattern: .env"


def test_excludes_secret_like_files_case_insensitively(tmp_path: Path):
    root = tmp_path
    names = [".ENV", "ApiToken.txt", "Credentials.json"]
    policy = ExclusionPolicy()

    for name in names:
        path = root / name
        path.write_text("sample")
        assert policy.should_skip_file(path, root)


def test_blocks_symlink_file_by_default(tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "outside.txt"
    link = root / "linked.txt"
    root.mkdir()
    outside.write_text("secret")
    try:
        link.symlink_to(outside)
    except OSError:
        return

    policy = ExclusionPolicy()

    assert policy.should_skip_file(link, root) == "symlink file"


def test_blocks_symlink_directory_by_default(tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    link = root / "linked_dir"
    root.mkdir()
    outside.mkdir()
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return

    policy = ExclusionPolicy()

    assert policy.should_skip_dir(link, root) == "symlink directory"
