# ADR 0007: 공개 repo 릴리스 단위와 claim boundary

날짜: 2026-06-15

## 상태

Accepted

## 배경

LocalLens AX Upgrade는 기존 로컬 멀티모달 검색 흐름을 유지하면서, PostgreSQL/Qdrant 기반 AX 확장 모드와 Agent evidence packet 흐름을 추가했다.

공개 repo에 올릴 때 한 번에 모든 변경을 올리면 변경 의도가 흐려지고, mock/local 검증 결과가 production 검증처럼 오해될 수 있다. 따라서 commit 단위를 기능 경계별로 나누고, README와 evidence 문서에는 주장 가능한 범위를 명시한다.

## 결정

공개 repo push 전 commit 단위는 다음 기준으로 나눈다.

| 단위 | 목적 |
|---|---|
| 문서/릴리스 범위 | README, ADR, test evidence, claim boundary |
| local demo API/UI | 브라우저 시연 가능한 Local Search, Image Search, PDF Visual Search |
| AX extension | PostgreSQL/Qdrant metadata, ACL, hybrid retrieval, Agent tool |
| PDF visual caption adapter | Clova/local/mock provider 경계 분리 |
| real demo/E2E | demo folder와 재현 가능한 smoke script |
| repo hygiene | gitignore, 공개 파일 점검, 보안 checklist |

## 검증 기준

릴리스 준비 상태는 다음을 만족해야 한다.

- README 이미지 참조가 로컬 repo 파일에 존재한다.
- `.locallens`, `runtime-cache`, `frontend/dist`, `*.log`가 git 추적 대상에서 제외된다.
- local demo E2E 스크립트가 text/image/PDF/Agent evidence packet 흐름을 확인한다.
- npm build와 audit가 통과한다.
- secret-like scan 결과가 실제 credential이 아닌 placeholder/env name/test fixture로 분류된다.

## claim boundary

사용 가능한 표현:

- local demo dataset 기준 E2E 재현 가능
- Docker 기반 PostgreSQL/Qdrant local smoke 구성
- Agent evidence packet schema 정규화
- PDF visual caption provider adapter 분리

사용하지 않을 표현:

- 실제 사내 문서 검색 검증 완료
- production 운영 성공
- 실제 사용자 데이터 기준 검색 정확도 향상
- local VLM이 모든 유료 VLM을 성능상 대체한다고 검증

## 결과

공개 repo는 포트폴리오에서 “실행 가능한 로컬 멀티모달 검색 확장 프로젝트”로 설명한다. 다만 모든 성과 표현은 local demo, mock, fixture, Docker smoke 기준으로 제한한다.
