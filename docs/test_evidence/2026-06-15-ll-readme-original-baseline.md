# Test Evidence: LL-README-001 original-baseline cleanup

날짜: 2026-06-15

## 범위

README를 원본 LocalLens 구조 기준으로 정리하고, 업그레이드로 바뀐 기술스택, 라이브러리, 아키텍처, 실행 방법만 반영했다.

## 변경 요약

| 항목 | 결과 |
|---|---|
| 기준 | 원본 `LocalLens` README 구조 |
| 제거 | 과도하게 길던 AX 설명과 중복 runbook 설명 |
| 유지 | local-first multimodal retrieval 정체성 |
| 추가 | demo screenshot, upgrade summary, architecture diagram, real demo quick start |
| 수정 | PDF VLM provider mode, PostgreSQL/Qdrant extension, Agent evidence packet 설명 |

## 검증 결과

| 검증 | 결과 |
|---|---|
| README image path check | PASS |
| README relative doc link check | PASS |
| `git diff --check` | PASS |
| `scripts/ll_real_demo_e2e.ps1` | PASS |
| `npm --prefix frontend run build` | PASS |
| `npm --prefix frontend audit --audit-level=moderate` | PASS, vulnerabilities 0 |

## claim boundary

이 문서로 주장 가능한 것:

- README를 원본 프로젝트 정체성 중심으로 정리했다.
- 변경된 기술스택, 라이브러리, 아키텍처만 공개 README에 반영했다.
- README 수정 후 local demo E2E와 frontend build/audit를 재검증했다.

주장하면 안 되는 것:

- GitHub README 렌더링이 아직 확인되기 전의 렌더링 성공
- production 운영 성공
- 실제 회사 문서 검증

