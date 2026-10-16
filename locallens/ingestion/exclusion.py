from __future__ import annotations

import fnmatch
import stat
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".svn",
    ".hg",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".cache",
    ".pytest_cache",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    ".turbo",
    "coverage",
    ".idea",
    ".vscode",
    "$RECYCLE.BIN",
    "System Volume Information",
}

DEFAULT_EXCLUDED_FILES = {
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "credentials*",
    "secrets*",
    "*token*",
    "*secret*",
    "*password*",
    "*.db",
    "*.sqlite",
    "*.mdb",
    "*.bak",
    "*.dump",
    "*.zip",
    "*.7z",
    "*.tar",
    "*.gz",
    "*.code-workspace",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}


@dataclass(frozen=True)
class ExclusionPolicy:
    excluded_dirs: set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDED_DIRS))
    excluded_files: set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDED_FILES))
    max_file_size_bytes: int = 25 * 1024 * 1024
    follow_symlinks: bool = False

    def should_skip_dir(self, path: Path, root: Path) -> str | None:
        if path.is_symlink() and not self.follow_symlinks:
            return "symlink directory"
        if _is_junction(path) and not self.follow_symlinks:
            return "junction directory"
        excluded_dirs = {name.lower() for name in self.excluded_dirs}
        if path.name.lower() in excluded_dirs:
            return f"excluded directory: {path.name}"
        if not self._is_inside_root(path, root):
            return "outside selected root"
        return None

    def should_skip_file(self, path: Path, root: Path) -> str | None:
        if path.is_symlink() and not self.follow_symlinks:
            return "symlink file"
        if not self._is_inside_root(path, root):
            return "outside selected root"
        name = path.name.lower()
        for pattern in self.excluded_files:
            if fnmatch.fnmatch(name, pattern.lower()):
                return f"excluded file pattern: {pattern}"
        try:
            size = path.stat().st_size
        except OSError as exc:
            return f"stat failed: {exc.__class__.__name__}"
        if size > self.max_file_size_bytes:
            return "file too large"
        return None

    @staticmethod
    def _is_inside_root(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False


def _is_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            return bool(is_junction())
        except OSError:
            return False
    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_point and attributes & reparse_point and path.is_dir())
