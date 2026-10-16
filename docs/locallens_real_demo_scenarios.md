# LocalLens 실제 demo folder 검색 시나리오

작성일: 2026-06-15

## 1. 목적

이 문서는 LocalLens 업그레이드본의 실제 시연용 demo folder와 검색 시나리오를 고정한다.

목표는 AX 전용 mock 문서 검색이 아니라, LocalLens의 로컬 텍스트, 이미지, PDF 멀티모달 검색 흐름을 보여주는 것이다.

## 2. Demo folder

경로:

```text
benchmarks/fixtures/locallens_real_demo
```

구성:

| 유형 | 파일 | 목적 |
|---|---|---|
| 문서 | `local_sync_policy.md` | 선택적 인덱스 갱신, content hash, skipped 파일 설명 |
| 문서 | `qdrant_metadata_design.md` | Qdrant payload, source reference, metadata 분리 설명 |
| 문서 | `agent_evidence_notes.txt` | Agent evidence packet, answer-ready context 설명 |
| 이미지 | `blue_security_badge.png` | 보안 badge 이미지 검색 |
| 이미지 | `green_architecture_diagram.png` | 아키텍처/흐름도 이미지 검색 |
| 이미지 | `orange_invoice_chart.png` | 차트/금액/인보이스 이미지 검색 |
| PDF | `locallens_architecture_report.pdf` | PostgreSQL/Qdrant/Agent evidence PDF 텍스트 검색 |
| PDF | `leave_approval_guide.pdf` | 휴가 승인 흐름 PDF 텍스트 및 표 visual caption 검색 |

## 3. Local VLM 실행 조건

환경 변수:

```powershell
$env:LOCALLENS_MODEL_CACHE_DIR="runtime-cache/smolvlm-256m-instruct"
$env:LOCALLENS_MODEL_LOCAL_FILES_ONLY="1"
$env:HF_HUB_OFFLINE="1"
$env:TRANSFORMERS_OFFLINE="1"
```

Sync 요청 핵심 설정:

```json
{
  "root_path": "benchmarks/fixtures/locallens_real_demo",
  "workspace_id": "real-demo-v2",
  "data_dir": ".locallens/real-demo-local-vlm-v2",
  "pdf_vlm_mode": "local-vlm",
  "pdf_vlm_model_name": "HuggingFaceTB/SmolVLM-256M-Instruct"
}
```

검증된 sync 결과:

```text
added: 8
units: 17
vlm_attempted: 2
vlm_succeeded: 2
vlm_empty: 0
vlm_failed: 0
```

해석:

```text
PDF 2개에서 visual region을 추출했고,
local VLM이 각각 pdf_visual_caption unit을 생성했다.
```

주의:

```text
이 결과는 local demo corpus 기준 실행 검증이다.
무료/local VLM이 Clova Studio보다 성능이 좋다는 의미가 아니다.
실제 기업 문서 또는 production 환경 검증도 아니다.
```

## 4. 고정 검색 시나리오

### 시나리오 1. 문서 내용으로 문서 찾기

목적:

```text
파일명이 아니라 문서 내부 내용으로 관련 문서를 찾는다.
```

질문:

```text
selective indexing content hash skipped files
```

권장 API filter:

```text
modality=text
unit_type=document
ext=.md
```

검증된 1위 결과:

```text
local_sync_policy.md
source_ref: local_sync_policy.md#type=document
```

### 시나리오 2. Agent 근거 문서 찾기

질문:

```text
evidence packet answer ready context source references
```

권장 API filter:

```text
modality=text
unit_type=document
ext=.txt
```

검증된 1위 결과:

```text
agent_evidence_notes.txt
source_ref: agent_evidence_notes.txt#type=document
```

### 시나리오 3. 이미지 설명으로 이미지 찾기

질문:

```text
blue security badge shield
```

권장 API filter:

```text
modality=image
```

검증된 1위 결과:

```text
blue_security_badge.png
source_ref: blue_security_badge.png#image=0&type=image
```

추가 질문:

```text
green architecture diagram flow
```

검증된 1위 결과:

```text
green_architecture_diagram.png
source_ref: green_architecture_diagram.png#image=0&type=image
```

### 시나리오 4. PDF 텍스트 내용으로 PDF 찾기

질문:

```text
annual leave request approval flow
```

권장 API filter:

```text
modality=text
ext=.pdf
unit_type=page
```

검증된 1위 결과:

```text
leave_approval_guide.pdf
source_ref: leave_approval_guide.pdf#page=1&type=page
```

### 시나리오 5. PDF 내부 표 설명으로 PDF 찾기

질문:

```text
leave approval table manager approval HR confirmation
```

권장 API filter:

```text
modality=text
ext=.pdf
unit_type=pdf_visual_caption
```

검증된 1위 결과:

```text
leave_approval_guide.pdf
source_ref: leave_approval_guide.pdf#page=1&image=0&type=pdf_visual_caption
```

## 5. 검증 결과

실행한 검증:

```text
.\scripts\ll_real_demo_e2e.ps1
결과: passed

python -m pytest tests\test_pdf_vlm_adapter.py -q
결과: 15 passed

python -m pytest tests\test_sync_search.py tests\test_non_filename_image_fixture.py tests\test_rerank_service.py tests\test_path_prefix_benchmark.py -q
결과: 35 passed

frontend npm run build
결과: passed
```

브라우저 smoke:

```text
URL:
http://127.0.0.1:5178/?api=http%3A%2F%2F127.0.0.1%3A8021

Scan / Index:
로컬 동기화 완료: added 0, updated 0, deleted 0, skipped 8

Local Search:
query = selective indexing content hash skipped files
first result = local_sync_policy.md

Image Search:
query = blue security badge shield
first result = blue_security_badge.png

PDF Visual Search:
query = leave approval table manager approval HR confirmation
first result = leave_approval_guide.pdf

Local Agent Evidence Packet:
button = 근거 패킷 생성
tool = locallens.local_search
mode = pdf
source_refs include leave_approval_guide.pdf#page=1&image=0&type=pdf_visual_caption
```

API smoke 결과:

| 검색 | 상태 | 결과 수 | 검증된 1위 |
|---|---:|---:|---|
| 문서 검색 | 200 | 2 | `local_sync_policy.md` |
| Agent 근거 문서 검색 | 200 | 1 | `agent_evidence_notes.txt` |
| 이미지 검색 1 | 200 | 3 | `blue_security_badge.png` |
| 이미지 검색 2 | 200 | 3 | `green_architecture_diagram.png` |
| PDF 텍스트 검색 | 200 | 2 | `leave_approval_guide.pdf` |
| PDF visual caption 검색 | 200 | 2 | `leave_approval_guide.pdf` |
| Local Agent evidence packet | UI | 2 | `locallens.local_search` |
| real demo E2E script | CLI | passed | `ll_real_demo_e2e.ps1` |

## 6. 이 시연으로 주장 가능한 것

```text
로컬 demo corpus 기준으로 텍스트, 이미지, PDF 검색과 파일 동기화 흐름을 시연 가능하게 구성했다.
```

```text
Clova Studio 의존 PDF visual caption 흐름을 local VLM provider로 대체해,
외부 유료 API 없이 PDF 내부 표/이미지 설명 검색 흐름을 구성했다.
```

## 7. 주장하면 위험한 것

```text
무료/local VLM이 Clova Studio보다 성능이 좋다.
실제 기업 문서에서 검증했다.
검색 정확도가 향상되었다.
운영 환경에서 검증했다.
```
