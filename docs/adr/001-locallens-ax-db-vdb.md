# ADR-001: LocalLens AX DB/VDB 선택

## Status

Accepted for mock E2E implementation.

## Context

기존 LocalLens는 선택한 로컬 폴더를 색인하고 Qdrant local mode와 manifest DB로 검색하는 local-first retrieval engine이다.

AX 업그레이드에서는 임직원 문서 검색 시나리오를 다룬다. 이 경우 문서 검색 자체보다 사용자, 부서, 문서 권한, 색인 상태, 검색 로그, 피드백 같은 운영 metadata가 중요해진다.

## Decision

LocalLens AX는 다음 구조를 사용한다.

| 계층 | 선택 | 책임 |
|---|---|---|
| Metadata DB | PostgreSQL | 사용자, 부서, 문서, 권한, 색인 상태, 검색 로그 |
| Vector DB | Qdrant | 문서 chunk embedding 검색과 payload filter |
| Retrieval | Hybrid Retrieval | keyword search와 semantic search 결합 |
| API | FastAPI | 검색, 문서, 색인, Agent tool endpoint |
| UI | React | 임직원 문서 검색 화면 |

## Why not SQLite + FAISS

SQLite + FAISS는 개인 로컬 검색기에는 충분하다. 그러나 AX 문서 검색에서는 권한 정책, 검색 로그, 문서 버전, 색인 job 상태를 명확히 다뤄야 한다.

FAISS는 고속 벡터 검색에는 적합하지만 AX 시나리오의 payload filtering, 운영형 vector store 설명력, server/local mode 전환 측면에서 Qdrant보다 약하다.

## Why not PostgreSQL + pgvector only

pgvector는 PostgreSQL 안에서 vector similarity search를 수행할 수 있다. 그러나 이번 프로젝트는 vector store 계층과 metadata 계층을 분리하는 설계를 보여주는 것이 목표다.

Qdrant는 dense vector, payload filter, local/server mode 전환을 설명하기 좋다. PostgreSQL은 문서 metadata와 권한 경계를 담당한다.

## Consequences

장점:

- AX 문서 검색에 필요한 권한/로그/문서상태를 PostgreSQL로 설명할 수 있다.
- Qdrant payload filter로 검색 후보 단계에서 권한 범위를 줄일 수 있다.
- FastAPI와 React를 붙여 서비스형 포트폴리오로 보여줄 수 있다.
- Agent tool endpoint로 AI Agent 직무 연결이 가능하다.

리스크:

- 기존 local-first 단순성이 줄어든다.
- PostgreSQL, Qdrant, FastAPI, React를 한 번에 넣으면 과설계로 보일 수 있다.
- mock E2E 결과를 production 성공으로 표현하면 안 된다.

## Claim Boundary

안전한 표현:

```text
사내 문서 탐색 AX 시나리오를 기준으로 PostgreSQL metadata와 Qdrant vector store를 분리했습니다.
mock dataset 기준으로 권한 필터와 evidence packet 반환 흐름을 검증할 수 있게 구성했습니다.
```

피해야 할 표현:

```text
사내 운영 검증 완료
production 성공
권한 누출 완전 방지
실사용 정확도 보장
```

