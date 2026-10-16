# LocalLens AX Upgrade - Portfolio Notes

## 1. One-line summary

LocalLens AX Upgrade는 로컬 파일 검색 MVP를 사내 문서 검색 AX 시나리오로 확장하기 위해 PostgreSQL metadata, Qdrant vector store, hybrid retrieval, permission filtering, Agent evidence packet 흐름을 추가한 개선 버전이다.

## 2. Before / After

| 관점 | Before | After |
|---|---|---|
| Metadata | SQLite 중심 파일/상태 관리 | PostgreSQL 기반 사용자, 부서, 문서, 버전, chunk, ACL, search log, feedback 분리 |
| Vector search | 로컬 벡터 검색 중심 | Qdrant collection과 payload schema로 chunk 단위 semantic search 구성 |
| Retrieval | 단일 검색 결과 반환 | PostgreSQL keyword 후보와 Qdrant semantic 후보를 fusion |
| Permission | 로컬 사용자 기준 단순 흐름 | `acl_tags`, `department_id`, `document_type` 기반 권한 필터 |
| Agent | 검색 결과 중심 | Agent tool이 사용할 evidence packet contract 구성 |
| Verification | 단위 기능 중심 | Docker local smoke로 schema, seed, vector upsert, pytest, API smoke 재현 |

## 3. Implemented technical points

### PostgreSQL metadata layer

- `departments`, `users`, `documents`, `document_versions`, `document_chunks`, `access_policies`, `search_logs`, `feedback` schema를 구성했다.
- 문서 본문, 버전, chunk, 권한, 검색 로그를 분리해 사내 문서 검색에 필요한 관리 단위를 명확히 했다.
- mock repository를 유지하면서 PostgreSQL repository로 전환할 수 있게 adapter 구조를 뒀다.

### Qdrant vector layer

- chunk vector와 payload를 Qdrant collection에 upsert하는 adapter를 구성했다.
- payload에는 `document_id`, `chunk_id`, `page`, `modality`, `department_id`, `document_type`, `acl_tags`를 포함했다.
- 검색 시 `acl_tags`와 metadata filter를 Qdrant payload filter로 전달하도록 했다.

### Hybrid retrieval

- PostgreSQL keyword 후보와 Qdrant semantic 후보를 같은 `RetrievalCandidate` 형태로 normalize했다.
- keyword score, semantic score, overlap bonus를 조합해 최종 score를 계산했다.
- Qdrant 실패 시 keyword fallback을 유지해 local smoke 시연 안정성을 높였다.

### Korean chunk ranking

- PostgreSQL `simple` full-text search만으로는 한국어 질의 정밀도가 낮아 앱 계층 token overlap을 추가했다.
- `신청`, `작성`, `대응`, `조치`, `기록`, `확인` 같은 행위 의도와 `절차`, `순서` 질의의 진행 단서를 ranking에 반영했다.
- 이 보강은 mock/local smoke용이며 운영 수준 한국어 검색 품질 검증을 의미하지 않는다.

### Agent evidence packet

- 검색 결과를 Agent tool에서 바로 사용할 수 있는 evidence packet 형태로 전달했다.
- packet에는 title, snippet, source_ref, score, keyword_score, semantic_score, match_type을 포함했다.
- 이 구조는 답변 생성 전 근거 후보를 안정적으로 전달하기 위한 contract다.
- `tool_input`, `evidence_packets`, `answer_ready_context`, `mock_answer`를 분리해 Agent가 검색 근거를 답변 준비 맥락으로 바꾸는 흐름을 명확히 했다.

## 4. Local verification

Reproducible command:

```powershell
.\scripts\ax_local_smoke.ps1
```

The script performs:

1. Docker PostgreSQL/Qdrant startup
2. PostgreSQL schema/seed apply
3. Qdrant collection creation and mock vector upsert
4. pytest execution
5. API smoke for health, search, Agent tool
6. Result summary output

Verified local smoke status:

- `pytest`: 15 passed
- `search`: returns `doc_hr_leave_policy` and `chunk_hr_leave_001` for `휴가 신청 절차`
- `agent tool`: returns evidence packets with source references
- Browser UI smoke: search result and Agent evidence packet displayed without browser errors

## 5. Safe resume wording

Use:

- PostgreSQL metadata와 Qdrant vector store를 분리해 사내 문서 검색 AX 구조로 확장
- PostgreSQL keyword search와 Qdrant semantic search를 결합한 hybrid retrieval 구성
- ACL payload filter와 source_ref 기반 evidence packet으로 Agent tool 연결 흐름 설계
- Docker 기반 mock dataset local smoke로 schema, vector upsert, API, UI 흐름 검증

Avoid:

- 실제 사내 문서 검색 검증 완료
- 운영 환경 검색 정확도 향상 검증
- production 운영 성공
- 실제 사용자/실데이터 benchmark 통과
- 한국어 검색 품질 보장

## 6. Interview explanation

### Why PostgreSQL?

SQLite는 로컬 MVP에서는 충분하지만, 사내 문서 검색 AX 시나리오에서는 사용자, 부서, 문서 버전, chunk, 권한, 검색 로그, 피드백처럼 관계형으로 관리해야 할 정보가 많다. PostgreSQL을 사용하면 metadata와 권한, 로그를 명확히 분리하고, 이후 운영형 구조로 확장하기 쉽다.

### Why Qdrant?

FAISS는 임베딩 검색 자체에는 강하지만, 서비스형 검색에서는 payload filter, collection 관리, API 기반 운용성이 중요하다. Qdrant는 chunk vector와 metadata payload를 함께 관리하고, ACL이나 document type 필터를 검색 조건에 넣기 쉽다.

### Why hybrid retrieval?

keyword search는 정확한 용어와 문서 제목에 강하고, semantic search는 표현이 달라도 의미가 비슷한 chunk를 찾는 데 강하다. 사내 문서 검색에서는 둘 중 하나만 쓰면 누락이 생기기 쉬워 keyword 후보와 semantic 후보를 normalize한 뒤 fusion하는 구조를 선택했다.

### What is the evidence packet?

Agent가 답변을 만들기 전에 사용할 근거 단위다. 단순 텍스트만 넘기지 않고 `source_ref`, `snippet`, `score`, `match_type`, `department_id`, `document_type`을 함께 전달해 어떤 문서의 어떤 chunk를 근거로 쓰는지 추적할 수 있게 했다.

### What is the limitation?

현재 검증은 mock dataset 기반 local smoke다. 실제 사내 문서, 실제 임베딩 모델, 운영 트래픽, 검색 정확도 benchmark는 검증 범위가 아니다. 운영 수준으로 확장하려면 한국어 형태소 분석, BM25/trigram, reranker, 실제 평가셋이 필요하다.

## 7. Claim boundary

| Claim | Status | Note |
|---|---|---|
| PostgreSQL/Qdrant local smoke 통과 | Safe | mock dataset 기준 |
| 권한 필터와 source_ref 표시 | Safe | API/UI smoke 기준 |
| Agent evidence packet 흐름 구성 | Safe | tool endpoint 기준 |
| Answer-ready context 구성 | Safe | mock answer composer 기준 |
| 검색 정확도 향상 | Unsafe | 정량 평가셋 없음 |
| 실사용 사내 문서 검증 | Unsafe | mock dataset만 사용 |
| production 운영 성공 | Unsafe | 운영 배포 검증 아님 |
