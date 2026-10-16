from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def root_id_for_path(path: Path) -> str:
    return sha256_text(str(path.resolve()))[:16]


def file_id_for_path(workspace_id: str, root_id: str, relative_path: str) -> str:
    return sha256_text(f"{workspace_id}:{root_id}:{relative_path}")[:24]


def unit_id_for_parts(*parts: object) -> str:
    return sha256_text(":".join("" if part is None else str(part) for part in parts))


def point_id_for_unit(unit_id: str) -> int:
    return int(unit_id[:16], 16) & ((1 << 63) - 1)
