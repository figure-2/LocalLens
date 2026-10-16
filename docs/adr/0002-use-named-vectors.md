# ADR-0002: Use Named Vectors

## Status

Accepted

## Context

LocalLens indexes text and image units. Each modality can use a different embedding profile and vector dimension.

## Decision

Use named vectors in the `locallens_units` collection:

- `text_dense_v1`
- `vision_dense_v1`

## Consequences

- Text and image search can evolve independently.
- Collection creation must use embedder-reported dimensions.
- Model profile changes require a fresh data directory or a purge before reindexing.

## Revisit Trigger

Revisit this decision if Qdrant collection behavior, model profiles, or retrieval quality metrics show that separate collections are more reliable for the target workload.

## Release Safety Check

This decision is justified by LocalLens requirements: text and vision retrieval profiles, explicit vector dimensions, and profile-aware benchmarking.
