# ADR 0008: 공개 repo staging 범위와 table PDF fixture 처리

날짜: 2026-06-15

## 상태

Accepted

## 배경

LL-GIT-002 단계에서는 공개 repo push 전 commit 단위와 staging 범위를 확정해야 한다.

현재 working tree에는 LocalLens AX Upgrade 핵심 변경 외에 `benchmarks/fixtures/pdf_corpus/table_*.pdf` 7개 파일의 binary 수정이 남아 있다. 이 파일들은 기존 PDF benchmark corpus에 포함되어 있고 여러 테스트/manifest에서 참조되지만, 이번 공개 릴리스의 주요 작업인 Local Search, Image Search, PDF Visual Search, PostgreSQL/Qdrant AX extension, local Agent evidence packet과 직접 연결된 변경 설명은 아직 확인되지 않았다.

추가 확인 결과, 수정된 PDF는 기존 HEAD 대비 extractable text가 비어 있고 MuPDF에서 zlib warning이 발생했다. 의도적으로 image-only OCR fixture로 바꾼 것일 수는 있지만, 그 경우에도 PDF table/OCR benchmark 검증과 함께 별도 commit으로 분리해야 한다.

## 결정

`benchmarks/fixtures/pdf_corpus/table_*.pdf` 수정분은 이번 공개 repo 기본 staging 범위에서 제외한다.

이유:

- binary PDF diff는 내용 검토가 어렵다.
- 수정된 파일에서 extractable text가 비어 있어 기존 PDF text/table benchmark에 회귀를 만들 수 있다.
- MuPDF zlib warning이 발생해 fixture 정상성 검증이 필요하다.
- 현재 수정분은 크기 변경과 text extraction 차이가 확인되며, 어떤 기능 변경을 위해 재생성됐는지 commit 설명으로 방어하기 어렵다.
- 공개 repo 첫 릴리스는 기능 경계가 명확한 변경만 포함하는 편이 안전하다.
- 기존 benchmark corpus는 이후 “PDF table benchmark fixture refresh” 같은 별도 commit으로 분리할 수 있다.

## staging 원칙

| 원칙 | 내용 |
|---|---|
| 기능 단위 commit | 문서, API/UI, AX backend, VLM adapter, demo/E2E를 분리 |
| local artifact 제외 | `.locallens`, `runtime-cache`, `frontend/dist`, `*.log` 제외 |
| evidence 포함 | 각 검증 결과는 `docs/test_evidence/`에 남김 |
| claim boundary 유지 | local demo/mock/fixture 결과를 production 성공으로 표현하지 않음 |

## 권장 commit 단위

| 순서 | 메시지 후보 | 포함 범위 |
|---:|---|---|
| 1 | `docs: document public release scope` | README, ADR, release docs, evidence, screenshot |
| 2 | `feat: add PDF visual caption provider adapter` | PDF VLM provider adapter, config, extractor integration, tests |
| 3 | `feat: add AX metadata and vector search extension` | PostgreSQL/Qdrant AX backend, schema, Docker local services |
| 4 | `feat: add LocalLens demo API and frontend` | FastAPI demo API, React UI, local search modes |
| 5 | `test: add reproducible local demo smoke workflow` | demo corpus, E2E scripts, AX/mock tests |

## table PDF fixture 추후 처리

추후 포함하려면 별도 확인 후 아래 조건을 만족해야 한다.

- 어떤 생성 스크립트가 어떤 이유로 PDF를 갱신했는지 설명 가능
- 관련 manifest/golden query와 정합성 확인
- 관련 PDF benchmark 또는 smoke test 통과
- 별도 commit 메시지로 범위가 설명 가능

## 검증

LL-GIT-002 기준으로 다음을 확인했다.

- `origin`은 `https://github.com/figure-2/LocalLens.git`
- README 이미지 파일은 repo 내부에 존재
- local artifact ignore 확인
- frontend build/audit 통과
- local demo E2E 통과
