# ADR-0005: Use Benchmark And Release Gates

## Status

Accepted

## Context

LocalLens needs measurable quality checks for search behavior, storage integrity, privacy rules, publication artifacts, and repository hygiene.

## Decision

Use benchmark reports and release gates before publishing artifacts.

Required evidence includes:

- Unit, contract, integration, and security tests.
- Recall and ranking metrics for golden queries.
- Search latency percentiles.
- Stale and duplicate vector counts.
- Publication artifact scan results.
- Repository hygiene scan results.

## Consequences

- README metrics must come from measured reports.
- Search quality changes must update benchmark evidence.
- Publication artifacts and repository hygiene checks must pass the release gate before publication.

## Revisit Trigger

Revisit this decision if the metric set no longer reflects LocalLens behavior, supported modalities, storage modes, publication artifact requirements, or repository hygiene requirements.

## Release Safety Check

This decision is justified by LocalLens requirements: measurable retrieval quality, privacy checks, store integrity, and evidence-backed release documentation.
