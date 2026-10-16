from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from locallens.core.config import Settings
from locallens.core.types import ExcludedPath, ScanReport, ScannedFile
from locallens.ingestion.exclusion import ExclusionPolicy
from locallens.ingestion.fingerprint import (
    content_hash,
    root_id_for_path,
)


SUPPORTED_EXTENSIONS = {
    ".txt": "text",
    ".md": "text",
    ".html": "text",
    ".htm": "text",
    ".pdf": "pdf",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
}


class Scanner:
    def __init__(self, settings: Settings, policy: ExclusionPolicy | None = None):
        self.settings = settings
        self.policy = policy or ExclusionPolicy(
            max_file_size_bytes=settings.max_file_size_bytes,
            follow_symlinks=settings.follow_symlinks,
        )

    def scan(self, root_path: str | Path) -> ScanReport:
        root = Path(root_path).resolve()
        root_id = root_id_for_path(root)
        report = ScanReport(root_id=root_id, root_path=root)
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Selected folder does not exist: {root}")

        for current, dirs, files in os.walk(root, followlinks=self.policy.follow_symlinks):
            current_path = Path(current)
            kept_dirs: list[str] = []
            for directory in dirs:
                path = current_path / directory
                reason = self.policy.should_skip_dir(path, root)
                if reason:
                    report.excluded.append(
                        ExcludedPath(_relative_or_name(path, root), reason)
                    )
                else:
                    kept_dirs.append(directory)
            dirs[:] = kept_dirs

            for filename in files:
                path = current_path / filename
                relative_path = _relative_or_name(path, root)
                reason = self.policy.should_skip_file(path, root)
                if reason:
                    report.excluded.append(ExcludedPath(relative_path, reason))
                    continue
                ext = path.suffix.lower()
                file_type = SUPPORTED_EXTENSIONS.get(ext)
                if not file_type:
                    report.excluded.append(
                        ExcludedPath(relative_path, f"unsupported extension: {ext}")
                    )
                    continue
                stat = path.stat()
                mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                report.files.append(
                    ScannedFile(
                        root_id=root_id,
                        root_path=root,
                        relative_path=relative_path,
                        file_type=file_type,
                        mime_type=mime_type,
                        ext=ext,
                        size_bytes=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                        content_hash=content_hash(path),
                    )
                )
        return report


def _relative_or_name(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return path.name
