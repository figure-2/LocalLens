# ADR-0004: Disable External Providers By Default

## Status

Accepted

## Context

LocalLens handles user-selected local folders. The default workflow must avoid unexpected network calls and data transfer.

## Decision

External OCR, VLM, remote embedding, and cloud indexing providers stay disabled unless the user explicitly opts in.

## Consequences

- Default indexing remains local-first.
- Optional provider settings must be visible and testable.
- Release checks must verify that default workflows do not require external API keys.

## Revisit Trigger

Revisit this decision only if a provider can be enabled through explicit user configuration, clear privacy labeling, and release-gated tests.

## Release Safety Check

This decision is justified by LocalLens requirements: selected-folder processing, predictable local defaults, and no unexpected data transfer in default workflows.
