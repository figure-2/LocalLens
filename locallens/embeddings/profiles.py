from __future__ import annotations

from dataclasses import replace

from locallens.core.config import Settings


def with_embedding_profiles(
    settings: Settings,
    text_dimension: int,
    vision_dimension: int,
    text_profile: str,
    vision_profile: str,
) -> Settings:
    return replace(
        settings,
        text_dimension=text_dimension,
        vision_dimension=vision_dimension,
        text_embedding_profile=text_profile,
        vision_embedding_profile=vision_profile,
    )
