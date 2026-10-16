from __future__ import annotations

import hashlib
import math
from pathlib import Path


def hash_vector(value: str | bytes, dimension: int) -> list[float]:
    if dimension <= 0:
        raise ValueError("dimension must be positive")
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(raw + counter.to_bytes(4, "big")).digest()
        for byte in digest:
            values.append((byte / 127.5) - 1.0)
            if len(values) == dimension:
                break
        counter += 1
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def file_hash_vector(path: Path, dimension: int) -> list[float]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return hash_vector(digest.digest(), dimension)

