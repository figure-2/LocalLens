# LocalLens AX 공개 repo commit 단위 제안

## 목적

공개 repo에 한 번에 올리기보다 변경 의도가 보이도록 기능 단위로 commit을 나눈다.

## 권장 commit 순서

1. `feat: add ax document search api scaffold`

   FastAPI 엔드포인트, mock 시나리오, 기본 search/agent tool API를 추가한다.

2. `feat: add postgres metadata schema for ax search`

   PostgreSQL 스키마, mock seed, metadata repository, 권한 필터 구조를 추가한다.

3. `feat: add qdrant vector payload contract`

   Qdrant payload schema, vector upsert/search adapter, deterministic mock embedding을 추가한다.

4. `feat: implement hybrid retrieval and evidence packet`

   PostgreSQL keyword search와 Qdrant semantic search를 결합하고, source reference와 evidence packet 포맷으로 정규화한다.

5. `feat: add ax search demo frontend`

   React 기반 AX 문서 검색 UI, 권한별 시나리오, source reference, Agent evidence packet 표시 화면을 추가한다.

6. `test: add ax local smoke workflow`

   Docker local smoke script, pytest, API smoke, mock E2E 검증 흐름을 추가한다.

7. `docs: document ax upgrade boundaries and release checks`

   README, PRD, runbook, claim boundary, 공개 repo 보안 체크리스트, 시연 스크린샷을 정리한다.

## commit 메시지 원칙

- 실제 검증 범위는 `local smoke`, `mock dataset`, `API smoke`로 제한한다.
- `production`, `real-data benchmark`, `accuracy improvement` 같은 표현은 commit 메시지에 쓰지 않는다.
- 공개 repo에는 개인 로컬 경로, 실제 credential, 비공개 데이터, 기존 사용자 정보가 들어가지 않게 한다.

