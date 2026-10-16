from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\|/)")
FILE_URI = re.compile(r"^file:/+", re.IGNORECASE)
UNC_PATH = re.compile(r"^(?:\\\\|//)")


@dataclass(frozen=True)
class ManifestEntryError(ValueError):
    manifest: Path
    line_no: int
    reason: str

    def __str__(self) -> str:
        return f"unsafe artifact manifest entry at line {self.line_no}: {self.reason}"


def manifest_entries(manifest: Path) -> set[str]:
    entries: set[str] = set()
    for line_no, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        entry = _normalize_manifest_entry(line)
        if not entry:
            continue
        entries.add(_validate_manifest_entry(entry, manifest=manifest, line_no=line_no))
    return entries


def artifact_paths_from_manifest(manifest: Path) -> list[Path]:
    base = manifest.parent
    return [base / entry for entry in sorted(manifest_entries(manifest))]


def _normalize_manifest_entry(line: str) -> str:
    entry = line.strip()
    if not entry or entry.startswith("#"):
        return ""
    return entry.replace("\\", "/")


def _validate_manifest_entry(entry: str, *, manifest: Path, line_no: int) -> str:
    if "\x00" in entry:
        _raise_unsafe(manifest, line_no, "nul byte")
    if entry in {".", "./"}:
        _raise_unsafe(manifest, line_no, "empty path segment")
    if DRIVE_PREFIX.search(entry):
        _raise_unsafe(manifest, line_no, "drive-letter path")
    if FILE_URI.search(entry):
        _raise_unsafe(manifest, line_no, "file URI")
    if UNC_PATH.search(entry):
        _raise_unsafe(manifest, line_no, "UNC path")
    if DRIVE_PATH.search(entry):
        _raise_unsafe(manifest, line_no, "drive-letter path")
    if PureWindowsPath(entry).is_absolute() or PurePosixPath(entry).is_absolute():
        _raise_unsafe(manifest, line_no, "absolute path")
    path = PurePosixPath(entry)
    if any(part == ".." for part in path.parts):
        _raise_unsafe(manifest, line_no, "repo escape")
    if any(part in {"", "."} for part in path.parts):
        _raise_unsafe(manifest, line_no, "empty path segment")
    return path.as_posix()


def _raise_unsafe(manifest: Path, line_no: int, reason: str) -> None:
    raise ManifestEntryError(manifest=manifest, line_no=line_no, reason=reason)
