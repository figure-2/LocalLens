# Test Evidence: LL real demo E2E

Date: 2026-06-15

## Scope

This record captures local demo release evidence for LocalLens.

This test does not claim production operation, real company document validation, or search accuracy improvement.

## Environment

Project:

```text
F:\File\02_Project\LocalLens_AX_Upgrade
```

Demo folder:

```text
benchmarks/fixtures/locallens_real_demo
```

Local VLM cache:

```text
runtime-cache\smolvlm-256m-instruct
```

Required flags:

```text
LOCALLENS_MODEL_LOCAL_FILES_ONLY=1
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

## Commands

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ll_real_demo_e2e.ps1
```

```powershell
cd frontend
npm run build
```

## Result

`scripts/ll_real_demo_e2e.ps1`:

```text
passed
```

Observed summary:

```text
sync_status: 200
added: 8
units: 17
vlm_attempted: 2
vlm_succeeded: 2
vlm_empty: 0
vlm_failed: 0

text_document_first: local_sync_policy.md
image_description_first: blue_security_badge.png
pdf_text_page_first: leave_approval_guide.pdf
pdf_visual_caption_first: leave_approval_guide.pdf
local_agent_tool: locallens.local_search
```

Frontend build:

```text
passed
```

Frontend audit:

```text
npm audit --audit-level=moderate
found 0 vulnerabilities
```

Secret-like scan:

```text
rg -n --hidden --glob '!node_modules/**' --glob '!frontend/node_modules/**' --glob '!dist/**' --glob '!frontend/dist/**' --glob '!.git/**' --glob '!.locallens/**' --glob '!runtime-cache/**' --glob '!*.log' "(API[_-]?KEY|SECRET|TOKEN|PASSWORD|DATABASE_URL|Bearer |sk-[A-Za-z0-9])" .
```

Review result:

```text
No real credential was identified in the scan output.
Matches are local-only Docker examples, placeholders, environment variable names, or synthetic test fixtures.
```

Examples that are allowed with context:

```text
POSTGRES_PASSWORD: locallens_local_only
LOCALLENS_AX_DATABASE_URL placeholder/local smoke DSN
CLOVA_STUDIO_API_KEY environment variable name
test fixture strings such as TOKEN=value and Bearer test-key
```

## Known Warning

```text
Payload indexes have no effect in the local Qdrant.
```

Interpretation:

```text
This is a local embedded Qdrant warning. It does not fail the local demo E2E.
Use Qdrant server mode when payload indexes are required.
```

## Claim Boundary

Allowed:

```text
local demo corpus 기준으로 folder sync, text/image/PDF search, local VLM PDF visual caption, local Agent evidence packet 흐름을 재현 가능하게 구성했다.
```

Not allowed:

```text
production success
real company document validation
real-data benchmark pass
search accuracy improvement
local VLM superiority over Clova Studio
```
