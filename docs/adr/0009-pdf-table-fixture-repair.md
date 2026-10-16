# ADR 0009: PDF table fixture repair and validation

날짜: 2026-06-15

## 상태

Accepted

## 배경

공개 repo push 준비 중 `benchmarks/fixtures/pdf_corpus/table_*.pdf` 7개 파일이 modified 상태로 남아 있었다. 초기 확인에서는 해당 working tree PDF에서 `Page.get_text("text")` 결과가 비어 있었고, MuPDF zlib warning이 발생했다.

PDF 문서는 LocalLens의 핵심 검색 대상 중 하나이므로, 이 변경을 단순 보류하지 않고 fixture를 복구하고 검증한 뒤 별도 commit으로 분리한다.

참고한 공식 문서:

- PyMuPDF text extraction: `https://pymupdf.readthedocs.io/en/latest/recipes-text.html`
- PyMuPDF Page API: `https://pymupdf.readthedocs.io/en/latest/page.html`
- PyMuPDF TextWriter / insert text alternatives: `https://pymupdf.readthedocs.io/en/latest/textwriter.html`

## 판단

PyMuPDF 공식 문서 기준으로 `Page.get_text("text")`는 PDF의 추출 가능한 텍스트를 확인하는 기본 경로다. 따라서 `pdf_table` fixture는 시각적으로 표처럼 보이는 것뿐 아니라 검색/benchmark를 위해 텍스트 추출 결과가 살아 있어야 한다.

기존 생성 스크립트 `benchmarks/generate_pdf_expansion.py`의 `_write_table_pdf()`는 `page.insert_text()`로 title과 cell text를 PDF에 삽입한다. 이 경로로 재생성하면 text extraction이 정상 동작한다.

## 결정

문제가 확인된 7개 table PDF만 생성 스크립트의 `_write_table_pdf()` 경로로 재생성한다.

대상:

```text
benchmarks/fixtures/pdf_corpus/table_budget_review_01.pdf
benchmarks/fixtures/pdf_corpus/table_dataset_slice_12.pdf
benchmarks/fixtures/pdf_corpus/table_index_delta_15.pdf
benchmarks/fixtures/pdf_corpus/table_ocr_queue_17.pdf
benchmarks/fixtures/pdf_corpus/table_quality_audit_03.pdf
benchmarks/fixtures/pdf_corpus/table_signal_score_18.pdf
benchmarks/fixtures/pdf_corpus/table_table_coverage_16.pdf
```

이 변경은 기능 구현 commit과 섞지 않고 별도 fixture repair commit으로 분리한다.

## 검증 기준

- 각 PDF가 1 page로 열려야 한다.
- `Page.get_text("text")` 결과가 비어 있으면 안 된다.
- target keyword가 추출 텍스트에 포함되어야 한다.
- PDF table benchmark 관련 테스트가 통과해야 한다.
- LocalLens real demo E2E가 회귀 없이 통과해야 한다.

## 검증 결과

2026-06-15 기준:

- 7개 PDF 모두 text extraction 정상
- `tests/test_benchmark.py::test_pdf_expansion_fixture_has_table_and_ocr_queries` 통과
- `tests/test_pdf_ocr_table.py::test_pdf_table_mode_change_forces_reindex_and_stale_removal` 통과
- `tests/test_pdf_ocr_table.py::test_pdf_table_readthrough_corrupt_blob_falls_back_to_cold_extract` 통과
- `scripts/ll_real_demo_e2e.ps1` 통과

## claim boundary

사용 가능한 표현:

- PDF table fixture의 추출 가능한 텍스트 레이어를 복구하고 targeted test를 통과시켰다.
- Local demo E2E 기준으로 text/image/PDF visual/Agent packet 흐름이 유지됐다.

사용하지 않을 표현:

- 모든 PDF 문서에 대한 OCR/표 추출 정확도를 검증했다.
- 실제 사내 PDF 데이터 기준 검색 정확도를 검증했다.
- production PDF 검색 품질을 보장한다.

