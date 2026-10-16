# Test Evidence: LL-PDF-FIX-001 PDF table fixture repair

날짜: 2026-06-15

## 범위

`benchmarks/fixtures/pdf_corpus/table_*.pdf` 중 문제가 확인된 7개 table fixture를 재생성하고, PDF text extraction과 관련 테스트를 검증했다.

## 원인 판단

초기 modified PDF 상태에서는 다음 문제가 있었다.

| 항목 | 결과 |
|---|---|
| PyMuPDF open | 열리기는 함 |
| `Page.get_text("text")` | 빈 문자열 |
| MuPDF warning | zlib warning 발생 |
| 리스크 | PDF table/text benchmark 회귀 가능 |

## 복구 방식

`benchmarks/generate_pdf_expansion.py`의 `_write_table_pdf()` 경로로 대상 7개 PDF만 재생성했다.

이 함수는 `page.insert_text()`를 사용해 title과 table cell text를 PDF에 삽입한다.

## 복구 대상

| 파일 | text length | 확인 preview |
|---|---:|---|
| `table_budget_review_01.pdf` | 139 | `budget review owner variance ... finance-alpha ...` |
| `table_dataset_slice_12.pdf` | 126 | `dataset slice tag count ... eval-alpha ...` |
| `table_index_delta_15.pdf` | 126 | `index delta file action ... sync-alpha ...` |
| `table_ocr_queue_17.pdf` | 124 | `ocr queue batch language ... ocr-alpha ...` |
| `table_quality_audit_03.pdf` | 122 | `quality audit check result ... qa-alpha ...` |
| `table_signal_score_18.pdf` | 138 | `signal score signal weight ... ranking-alpha ...` |
| `table_table_coverage_16.pdf` | 140 | `table coverage pdf tables ... document-alpha ...` |

## 실행한 검증

```powershell
python -m pytest tests/test_benchmark.py::test_pdf_expansion_fixture_has_table_and_ocr_queries `
  tests/test_pdf_ocr_table.py::test_pdf_table_mode_change_forces_reindex_and_stale_removal `
  tests/test_pdf_ocr_table.py::test_pdf_table_readthrough_corrupt_blob_falls_back_to_cold_extract
```

결과:

```text
3 passed, 1 warning
```

warning:

```text
Payload indexes have no effect in the local Qdrant.
```

판단: local Qdrant 사용 시 payload index가 효과 없다는 경고이며, 이번 PDF fixture repair 실패는 아니다.

추가 검증:

```powershell
.\scripts\ll_real_demo_e2e.ps1
```

결과:

```text
LL real demo E2E passed.
text/image/PDF search passed.
local VLM PDF visual caption passed.
local Agent evidence packet passed.
```

## 결론

PDF table fixture는 검색 가능한 텍스트 레이어가 복구됐다.

이 변경은 기능 코드 commit과 섞지 않고 별도 fixture repair commit으로 관리한다.

