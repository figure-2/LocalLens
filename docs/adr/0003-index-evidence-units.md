# ADR-0003: Index Evidence Units

## Status

Accepted

## Context

Search results should point to meaningful evidence, not only to whole files. Text, PDF pages, chunks, and images need distinct metadata and ranking behavior.

## Decision

Index search units with these unit types:

- `document`
- `page`
- `chunk`
- `image`

Each point id is deterministic for the workspace, root, file, unit type, and unit position.

## Consequences

- Reindexing is idempotent.
- Search results can include page numbers, chunk numbers, snippets, and modality.
- Sync logic must delete stale points when files are removed or changed.

## Revisit Trigger

Revisit this decision if benchmark results show that the current unit granularity hurts ranking quality, latency, or storage footprint.

## Release Safety Check

This decision is justified by LocalLens requirements: evidence-level results, PDF page numbers, text snippets, image units, and stale-result filtering.
