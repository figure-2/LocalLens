# ADR-0001: Use Qdrant Local Mode

## Status

Accepted

## Context

LocalLens needs a local vector store that persists search units, supports metadata filters, and can run without a separate service in the default setup.

## Decision

Use Qdrant local mode as the default vector store.

## Consequences

- Default setup stays local and simple.
- The same store abstraction can later compare local mode with server mode.
- Release checks must verify collection integrity, stale vector count, and duplicate vector count.

## Revisit Trigger

Revisit this decision if local mode cannot meet measured indexing, search latency, storage, or concurrency requirements for the target corpus.

## Release Safety Check

This decision is justified by LocalLens requirements: local persistence, metadata filtering, named-vector support, and benchmarkable store integrity.
