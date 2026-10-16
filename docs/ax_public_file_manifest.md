# LocalLens AX 공개 파일 목록 점검

## 공개 대상

- `README.md`
- `pyproject.toml`
- `docker-compose.ax.yml`
- `.env.example`
- `locallens/`
- `frontend/` 소스 파일과 lockfile
- `sql/`
- `scripts/ax_local_smoke.ps1`
- `scripts/ll_real_demo_e2e.ps1`
- `tests/`
- `docs/`
- `benchmarks/fixtures/`의 mock fixture
- `benchmarks/fixtures/ax_pdf_corpus/`의 AX 시나리오용 mock PDF

## 공개 가능하지만 설명이 필요한 항목

- `docker-compose.ax.yml`의 `locallens_local_only`

  Docker local smoke용 예시 비밀번호다. 실제 credential이 아니다.

- 테스트 fixture의 가짜 secret 문자열

  secret scan 동작을 검증하기 위한 synthetic fixture다. 실제 secret이 아니다.

- `docs/assets/locallens-ax-demo.png`
- `docs/assets/locallens-real-demo-ui.png`

  mock dataset과 local smoke 기반 시연 화면이다. 실제 사내 문서 검색 화면이 아니다.

- `docs/assets/locallens-real-demo-ui.png`

  `benchmarks/fixtures/locallens_real_demo`와 local VLM 기반 E2E 시연 화면이다. 실제 기업 문서 검색 화면이 아니다.

- `benchmarks/fixtures/ax_pdf_corpus/*`

  AX 시나리오 seed와 대응되는 공개용 mock PDF다. `mock_export_preview_pdf`는 markdown/pptx seed 문서를 설명하기 위한 PDF preview이며, 원본 document type을 PDF로 주장하지 않는다.

## 공개 제외 대상

- `.env`, `.env.*`
- `.locallens/`, `.local/`
- `*.db`, `*.sqlite`, `*.sqlite3`
- `node_modules/`, `frontend/node_modules/`
- `dist/`, `frontend/dist/`
- Qdrant local storage와 snapshot
- PostgreSQL local volume dump
- `*.log`
- `*.pem`, `*.key`, `*token*`, `*secret*`, `*password*`, `credentials*`

## 최종 점검 기준

- `npm audit` 0건
- `npm run build` 성공
- `.\scripts\ax_local_smoke.ps1 -SkipDocker` 성공
- `.\scripts\ll_real_demo_e2e.ps1` 성공
- secret scan 결과가 local-only 예시, placeholder, test fixture로만 설명 가능
- README에 mock/local smoke claim boundary가 명시됨
- AX PDF corpus가 mock source/export preview로 구분됨
