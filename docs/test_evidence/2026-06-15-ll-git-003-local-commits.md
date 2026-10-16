# Test Evidence: LL-GIT-003 local commit 결과

날짜: 2026-06-15

## 범위

LL-GIT-003 단계에서 공개 repo push 전 local commit을 기능 단위로 생성하고, push 전 검증을 다시 수행했다.

## local commit 결과

| 순서 | commit | 메시지 |
|---:|---|---|
| 1 | `8f1533a` | `docs: document public release scope` |
| 2 | `9979510` | `feat: add PDF visual caption provider adapter` |
| 3 | `6f72161` | `feat: add AX metadata and vector search extension` |
| 4 | `26aea89` | `feat: add LocalLens demo API and frontend` |
| 5 | `bf75e87` | `test: add reproducible local demo smoke workflow` |

## push 전 재검증

| 검증 | 결과 | 요약 |
|---|---|---|
| `scripts/ll_real_demo_e2e.ps1` | PASS | sync 8 files, 17 units, local VLM 2/2 succeeded, text/image/PDF/Agent packet 통과 |
| `npm --prefix frontend run build` | PASS | Vite build 통과 |
| `npm --prefix frontend audit --audit-level=moderate` | PASS | 취약점 0개 |

## 남은 uncommitted 변경

현재 의도적으로 commit하지 않은 파일:

```text
benchmarks/fixtures/pdf_corpus/table_budget_review_01.pdf
benchmarks/fixtures/pdf_corpus/table_dataset_slice_12.pdf
benchmarks/fixtures/pdf_corpus/table_index_delta_15.pdf
benchmarks/fixtures/pdf_corpus/table_ocr_queue_17.pdf
benchmarks/fixtures/pdf_corpus/table_quality_audit_03.pdf
benchmarks/fixtures/pdf_corpus/table_signal_score_18.pdf
benchmarks/fixtures/pdf_corpus/table_table_coverage_16.pdf
```

제외 이유:

- binary PDF diff라 내용 검토가 어렵다.
- 수정된 working tree PDF에서 extractable text가 비어 있는 것으로 확인했다.
- MuPDF zlib warning이 발생했다.
- 이번 공개 release 핵심인 Local Search, Image Search, PDF Visual Search, AX extension, Agent evidence packet과 분리해서 검증해야 한다.

## push 상태

아직 `git push origin main`은 실행하지 않았다.

push 전 남은 결정:

- 위 `table_*.pdf` 7개를 그대로 남긴 dirty worktree 상태에서 push할지
- 아니면 별도 branch/별도 commit/원복 중 하나를 선택할지

## claim boundary

이번 evidence로 주장 가능한 것:

- 기능 단위 local commit 생성 완료
- local demo E2E, frontend build, frontend audit 통과
- push 전 제외 파일과 남은 dirty state를 명확히 기록

주장하면 안 되는 것:

- GitHub push 완료
- GitHub README 렌더링 확인 완료
- `table_*.pdf` fixture refresh 검증 완료

