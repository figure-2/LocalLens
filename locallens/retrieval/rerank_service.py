from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from locallens.core.config import Settings
from locallens.core.types import SearchResult


class RerankService(Protocol):
    profile: str

    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        ...


@dataclass(frozen=True)
class NoOpRerankService:
    profile: str = "off:no-op"

    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        return list(results)


def build_rerank_service(settings: Settings) -> RerankService:
    mode = settings.rerank_mode.strip().lower()
    if mode in {"", "off", "none", "noop", "no-op"}:
        return NoOpRerankService()
    raise ValueError("Unsupported rerank mode")


def apply_rerank_service(
    query: str,
    results: list[SearchResult],
    service: RerankService,
) -> list[SearchResult]:
    baseline = list(results)
    try:
        return service.rerank(query, baseline)
    except Exception:
        return baseline
