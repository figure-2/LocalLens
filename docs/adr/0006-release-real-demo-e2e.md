# ADR 0006: Release evidence must include the real local demo E2E

Date: 2026-06-15

## Status

Accepted

## Context

The LocalLens upgrade has two demo surfaces.

- AX workspace smoke with PostgreSQL/Qdrant mock workplace documents.
- LocalLens core folder sync and multimodal local file search.

For portfolio release, the primary identity must remain the LocalLens local multimodal retrieval identity:

```text
local-first multimodal search for text, image, and PDF files
```

Release evidence therefore cannot rely only on AX mock smoke. It needs a reproducible local demo E2E that exercises the real demo folder, file sync, local index, local VLM PDF visual captioning, and Agent evidence packet construction.

## Decision

Use `scripts/ll_real_demo_e2e.ps1` as the release evidence script for the LocalLens real demo path.

The script verifies:

- demo folder sync
- text document search
- image description search
- PDF text page search
- PDF visual caption search
- local Agent evidence packet generation

The script uses:

- `benchmarks/fixtures/locallens_real_demo`
- cached `HuggingFaceTB/SmolVLM-256M-Instruct`
- `LOCALLENS_MODEL_LOCAL_FILES_ONLY=1`
- `HF_HUB_OFFLINE=1`
- `TRANSFORMERS_OFFLINE=1`

## Consequences

Allowed claim:

```text
local demo corpus 기준으로 demo folder sync, text/image/PDF search, local VLM PDF visual caption, Agent evidence packet 흐름을 스크립트로 재현 가능하게 구성했다.
```

Disallowed claims:

```text
production 운영 검증
실제 기업 문서 검증
검색 정확도 향상 검증
무료/local VLM이 Clova Studio보다 성능 우수
```

## Verification Record

See:

```text
docs/test_evidence/2026-06-15-ll-real-demo-e2e.md
```
