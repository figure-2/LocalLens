# Test Evidence: LL-GIT-002 staging 계획

날짜: 2026-06-15

## 범위

공개 repo push 전 staging 범위, commit 단위, 제외 파일, remote 상태를 확인했다.

## 확인 결과

| 항목 | 결과 | 근거 |
|---|---|---|
| git remote | PASS | `origin` = `https://github.com/figure-2/LocalLens.git` |
| table PDF fixture 처리 | HOLD | `benchmarks/fixtures/pdf_corpus/table_*.pdf` 7개 binary 수정분은 기본 staging 제외 |
| README 이미지 | PASS | `docs/assets/locallens-real-demo-ui.png` 존재 |
| local artifact ignore | PASS | `.locallens`, `runtime-cache`, `frontend/dist`, `*.log` ignore 확인 |
| local demo E2E | PASS | `scripts/ll_real_demo_e2e.ps1` 통과 |
| frontend build | PASS | `npm --prefix frontend run build` 통과 |
| frontend audit | PASS | `npm --prefix frontend audit --audit-level=moderate` 취약점 0개 |
| diff whitespace check | PASS | `git diff --check` 오류 없음. Windows CRLF 경고만 확인 |

## table PDF fixture 판단

수정된 파일:

```text
benchmarks/fixtures/pdf_corpus/table_budget_review_01.pdf
benchmarks/fixtures/pdf_corpus/table_dataset_slice_12.pdf
benchmarks/fixtures/pdf_corpus/table_index_delta_15.pdf
benchmarks/fixtures/pdf_corpus/table_ocr_queue_17.pdf
benchmarks/fixtures/pdf_corpus/table_quality_audit_03.pdf
benchmarks/fixtures/pdf_corpus/table_signal_score_18.pdf
benchmarks/fixtures/pdf_corpus/table_table_coverage_16.pdf
```

판단:

- 이 파일들은 benchmark corpus에 참조되지만 현재 LL-GIT-002 공개 릴리스 핵심 변경과 직접 연결된 설명이 부족하다.
- binary diff라 내용 검토가 어렵다.
- 기존 HEAD의 PDF는 텍스트 추출 결과가 있었지만, 수정된 working tree PDF는 extractable text가 비어 있는 것으로 확인했다.
- 수정된 working tree PDF 확인 중 MuPDF zlib warning이 발생했다.
- 기본 공개 commit에서는 제외하고, 필요하면 별도 fixture refresh commit으로 분리한다.

검증 기준:

- 이 7개 PDF를 포함하려면 PDF table/OCR benchmark 또는 관련 targeted test를 별도로 통과시켜야 한다.
- 의도적으로 image-only PDF fixture로 바꾼 것이라면 그 의도와 benchmark 결과를 별도 ADR/evidence에 남긴다.

## 권장 git add 명령

아래 명령은 staging 계획이다. 아직 실행하지 않았다.

### 1. 문서와 공개 릴리스 범위

```powershell
git add README.md .gitignore docs "LocalLens_AX_업그레이드_PRD.md"
git commit -m "docs: document public release scope"
```

### 2. PDF visual caption provider adapter

```powershell
git add pyproject.toml `
  locallens/core/config.py `
  locallens/extractors/pdf_extractor.py `
  locallens/extractors/pdf_vlm_adapter.py `
  tests/test_pdf_vlm_adapter.py
git commit -m "feat: add PDF visual caption provider adapter"
```

### 3. AX metadata/vector search extension

```powershell
git add docker-compose.ax.yml sql locallens/ax `
  locallens/retrieval/filters.py `
  locallens/retrieval/search_service.py `
  tests/test_ax_agent_contract.py `
  tests/test_ax_contracts.py `
  tests/test_ax_mock_e2e.py `
  tests/test_ax_ranking.py
git commit -m "feat: add AX metadata and vector search extension"
```

### 4. demo API와 frontend

```powershell
git add locallens/api frontend
git commit -m "feat: add LocalLens demo API and frontend"
```

### 5. demo corpus와 재현 스크립트

```powershell
git add benchmarks/fixtures/ax_pdf_corpus `
  benchmarks/fixtures/locallens_real_demo `
  scripts
git commit -m "test: add reproducible local demo smoke workflow"
```

## push 전 재검증 명령

```powershell
.\scripts\ll_real_demo_e2e.ps1
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=moderate
git status --short
```

## claim boundary

이 evidence로 주장 가능한 것:

- local demo folder 기준 text/image/PDF visual/Agent evidence packet E2E 재현 가능
- frontend build와 npm audit 통과
- 공개 repo staging 범위와 제외 대상 정리

주장하면 안 되는 것:

- production 운영 성공
- 실제 사내 문서 검색 정확도 검증
- table PDF fixture 갱신이 검증 완료되었다는 주장
