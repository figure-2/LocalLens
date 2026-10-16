# LocalLens 공개 repo commit 계획

작성일: 2026-06-15

## 결론

공개 repo에는 현재 코드를 한 번에 올리지 말고, 기능 경계가 보이는 단위로 나누어 commit한다.

권장 commit 순서는 아래와 같다.

| 순서 | commit 메시지 후보 | 범위 | 포함 파일 예시 | 검증 기준 | 위험 |
|---:|---|---|---|---|---|
| 1 | `docs: document LocalLens release scope` | 공개 설명, claim boundary, 실행 방법 | `README.md`, `docs/adr/`, `docs/test_evidence/`, `docs/assets/` | README 이미지 경로 존재, 공개 claim이 mock/local 기준으로 제한됨 | 낮음 |
| 2 | `feat: add local demo API and frontend` | 브라우저 시연용 API/UI | `locallens/api/`, `frontend/` | Local Search, Image Search, PDF Visual Search UI 시연 가능 | 중간 |
| 3 | `feat: add PostgreSQL and Qdrant AX extension` | AX 확장 모드, 문서/권한/검색로그 구조 | `locallens/ax/`, `sql/`, `docker-compose.ax.yml` | Docker local smoke 통과 | 중간 |
| 4 | `feat: add PDF visual caption provider adapter` | PDF 시각 caption provider 분리 | `locallens/extractors/pdf_vlm_adapter.py`, `locallens/core/config.py`, 관련 테스트 | mock/local provider 테스트 통과 | 중간 |
| 5 | `test: add real demo corpus and smoke scripts` | 실제 demo folder, E2E 스크립트 | `benchmarks/fixtures/locallens_real_demo/`, `scripts/` | `scripts/ll_real_demo_e2e.ps1` 통과 | 중간 |
| 6 | `chore: prepare public repository hygiene` | 추적 제외, 보안 점검, release checklist | `.gitignore`, 공개 파일 manifest, 보안 checklist | local artifact ignore 확인, audit 0 vulnerabilities | 낮음 |

## commit 전 제외해야 할 항목

| 항목 | 처리 |
|---|---|
| `.locallens/` | gitignore 유지 |
| `runtime-cache/` | gitignore 유지 |
| `frontend/dist/` | gitignore 유지 |
| `*.log` | gitignore 유지 |
| 실제 `.env` 파일 | commit 금지 |
| 실제 API key, DB URL, token | commit 금지 |
| 개인 경로가 들어간 임시 로그 | commit 금지 |

## commit 전 사람이 확인할 항목

| 항목 | 현재 판단 |
|---|---|
| `benchmarks/fixtures/pdf_corpus/table_*.pdf` 수정분 | 현재 release 범위와 직접 관련이 있는지 확인 필요 |
| README screenshot | `docs/assets/locallens-real-demo-ui.png`로 로컬 참조됨 |
| local VLM 모델 cache | `runtime-cache/`에 있어 repo에는 올리지 않음 |
| AX Docker 데이터 | local runtime artifact로 repo에 올리지 않음 |

## 사용할 수 있는 표현

- Docker 기반 PostgreSQL/Qdrant local smoke를 구성했다.
- demo folder 기준 text/image/PDF 검색 흐름을 E2E 스크립트로 재현 가능하게 만들었다.
- PDF visual caption은 provider adapter로 분리했고, local VLM cache가 있을 때 실제 local caption 실행이 가능하다.
- 검색 결과를 Agent가 사용할 수 있는 evidence packet 형태로 정규화했다.

## 쓰면 위험한 표현

- 실제 사내 문서 검색 정확도를 검증했다.
- production 운영 검증을 완료했다.
- 유료/외부 VLM 없이 모든 PDF 시각 정보를 완전히 대체했다.
- 실제 사용자 데이터 기준 성능이 향상되었다.

## push 전 최소 검증

```powershell
.\scripts\ll_real_demo_e2e.ps1
npm run build
npm audit --audit-level=moderate
git status --short
git check-ignore -v .locallens runtime-cache frontend/dist
```

