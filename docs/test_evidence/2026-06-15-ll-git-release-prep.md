# Test Evidence: LL-GIT-001 공개 repo push 준비

날짜: 2026-06-15

## 범위

공개 repo에 올리기 전 commit 단위, 제외 파일, README 렌더링, 보안 노출 위험, local demo 검증 상태를 확인했다.

## 확인 결과

| 항목 | 결과 | 근거 |
|---|---|---|
| README 이미지 참조 | PASS | `docs/assets/locallens-real-demo-ui.png` 존재 |
| README 문서 링크 | PASS | 현재 README 내 상대 문서 링크 누락 없음 |
| local artifact ignore | PASS | `.locallens`, `runtime-cache`, `frontend/dist`, `*.log` ignore 확인 |
| secret-like scan | CONDITIONAL PASS | 실제 credential은 발견하지 못했고, env var name, placeholder, synthetic fixture만 확인 |
| local demo E2E | PASS | text/image/PDF visual/Agent packet 흐름 통과 |
| frontend build | PASS | `npm --prefix frontend run build` 통과 |
| npm audit | PASS | `npm --prefix frontend audit --audit-level=moderate` 기준 취약점 0개 |

## LL-E2E-001 재확인 요약

`scripts/ll_real_demo_e2e.ps1` 기준 확인된 흐름:

| 단계 | 확인 |
|---|---|
| demo folder sync | 8 files, 17 units |
| local VLM caption | attempted 2, succeeded 2, failed 0 |
| text search | `local_sync_policy.md` 반환 |
| image search | `blue_security_badge.png` 반환 |
| PDF text page search | `leave_approval_guide.pdf` 반환 |
| PDF visual caption search | `leave_approval_guide.pdf` 반환 |
| Agent evidence packet | `locallens.local_search` tool packet 생성 |

## git hygiene 확인

`git check-ignore` 기준:

| 경로 | 결과 |
|---|---|
| `.locallens` | ignored |
| `runtime-cache` | ignored |
| `frontend/dist` | ignored |
| `.tmp_backend_8021.out.log` | ignored |
| `docs/assets/locallens-real-demo-ui.png` | not ignored, 공개 screenshot으로 commit 가능 |

## 남은 사람 검토 항목

| 항목 | 이유 |
|---|---|
| `benchmarks/fixtures/pdf_corpus/table_*.pdf` 수정분 | 이번 release 범위와 직접 관련 있는지 확인 필요 |
| commit 단위 staging | 실제 commit/push 전 사용자가 원하는 순서로 `git add` 범위를 확정해야 함 |
| GitHub README 렌더링 | push 이후 GitHub 웹에서 screenshot 렌더링 확인 필요 |

## secret-like scan 해석

검출된 항목은 다음 유형으로 분류했다.

| 유형 | 판단 |
|---|---|
| `.gitignore`, README, docs의 secret/token 단어 | 제외 규칙과 설명 문구 |
| local-only Docker DB URL 예시 | 로컬 개발용 예시이며 외부 credential 아님 |
| env var name | secret 값이 아니라 환경변수 이름 |
| 테스트 fixture의 가짜 secret 문자열 | redaction/scan 테스트용 synthetic fixture |
| `frontend/package-lock.json`의 `js-tokens` | npm package 이름 |

실제 credential 값은 확인되지 않았다. 단, push 전에는 staged 파일 기준으로 한 번 더 확인해야 한다.

## claim boundary

이 문서로 주장 가능한 것은 “local demo와 Docker/local smoke 기준 재현 가능성”이다.

이 문서만으로 주장하면 안 되는 것:

- 실제 사내 문서 검색 정확도 검증
- production 운영 성공
- 실제 사용자 데이터 기반 성능 향상
- local VLM의 상용 VLM 대비 성능 우위
