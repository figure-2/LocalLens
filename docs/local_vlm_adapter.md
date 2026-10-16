# Local VLM Adapter

Local VLM captioning is an optional PDF visual caption path. It is not enabled
by default and is not part of the v0.1 quality claim.

## Runtime Contract

The adapter receives a cached PDF region image and metadata:

- `relative_path`
- `page_no`
- `image_no`
- `bbox`

If the adapter produces supported text, LocalLens indexes a text unit:

- `unit_type`: `pdf_visual_caption`
- `modality`: `text`
- `source_kind`: `pdf`
- `extractor_profile`: local caption profile and prompt version
- `locality`: offline gate evidence

The caption is never merged into page text. It remains a separate evidence
unit so ranking, filtering, and failure handling can be evaluated independently.

## Offline Gate

A local caption candidate must pass this gate before its output can support
release evidence:

| Field | Required Value |
| --- | --- |
| `runtime_network_calls` | `0` |
| `automatic_model_downloads` | `0` |
| `external_provider_fallbacks` | `0` |
| `local_cache_or_install_path` | sanitized configured-local status |

Machine-specific absolute paths are not written to public evidence.

## Current Decision

The current adapter is an interface and POC harness. The measured POC attempted
50 visual regions in the 73-PDF fixture, produced 50 caption units, and reports
`hold_status: hold-quality`. The offline locality fields remained
network/download/fallback 0, but the expanded 14-query caption set reports
recall@5 0.929 and MRR@10 0.735 against the current promotion bars of
0.950 and 0.850.
Weak-slice analysis found top1 failure count 5 across receipt, scanned-like,
multilingual, and product-diagram cases. A benchmark-only IDF-style rerank
diagnostic improved MRR@10 by 0.018, but it remains below the quality bar and
is not a product ranking candidate.
OCR/table/layout baselines remain the active PDF evidence paths until a local
caption candidate clears recall@5, MRR@10, latency, and failure-budget gates on
the same fixture.

The adapter can recognize the configured local SmolVLM family candidates used
by the POC harness and a Florence-2 comparison candidate for isolated local
experiments. Candidate-specific processor behavior is isolated behind the
adapter contract, and any extra runtime dependency must be installed through an
explicit opt-in path such as the `local-vlm` optional dependency group. A new
candidate result does not change public release claims until the canonical
evidence artifact and release gate are refreshed together.

Florence-2 comparison support is not a promoted release capability. It remains
default-off and subject to the same offline gate, caption-unit, recall/MRR,
latency, failure-budget, and artifact-scan checks as every other local caption
candidate.

## Candidate Evaluation Policy

LocalLens evaluates local caption candidates with a lightweight-first ladder.
The first measured candidate should be small enough to prove whether local
visual captions add retrieval value without creating a heavy default runtime.
If a smaller candidate cannot produce useful caption units, evaluation can move
to stronger candidates and specialist caption/OCR baselines.

Candidate names, cache paths, and machine-specific setup details are not
release claims. A candidate becomes reportable only after the offline gate,
caption unit, recall/MRR, latency, failure-count, and artifact-scan checks
pass on the same PDF fixture.

## Hold Release Conditions

| Status | Meaning | Release Decision |
| --- | --- | --- |
| `hold-unconfigured` | no caption-capable local runtime/cache is configured | no caption claim |
| `hold-zero-captions` | offline gate passes but `pdf_visual_caption` units are 0 | no caption claim |
| `hold-no-golden` | caption units exist but no visual-caption golden set exists | evidence only, no quality claim |
| `hold-quality` | golden set exists but recall, MRR, empty/failure, or latency budget fails | keep OCR/table/layout baselines |
| `candidate-ready` | offline gate passes, caption units > 0, golden recall@5/MRR@10 and latency are measured, and failure budget passes | opt-in candidate only |

Hold can be lifted only when the same PDF fixture reports `caption_units > 0`,
runtime network calls 0, automatic downloads 0, external fallback 0, configured
local cache/install path, recall@5 and MRR@10, p50/p95 latency, empty/failure
counts, and a passing artifact scan.
