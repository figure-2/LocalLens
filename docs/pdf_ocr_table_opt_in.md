# PDF OCR And Table Opt-In

LocalLens keeps PDF OCR and table extraction outside the default workflow.
`local-layout` can create visual region units, but it does not read scanned text
or infer table structure.

## Scope

| Mode | Default | Purpose | Output |
| --- | --- | --- | --- |
| `off` | yes | PDF page text only | `document`, `page`, `chunk` |
| `local-layout` | no | Embedded visual placement discovery | `pdf_region` |
| `local-ocr` | no | Local OCR text from selected visual regions | `pdf_ocr_text` |
| `local-table` | no | Born-digital text-layer table unit extraction | `pdf_table` |

## Candidate Selection

| Area | Candidate | Strength | Risk | Decision |
| --- | --- | --- | --- | --- |
| OCR | Tesseract | Mature local command-line OCR, language data model is explicit | Requires native install and language-pack setup | Keep as first local OCR smoke candidate |
| OCR | EasyOCR | Simple Python API and multilingual model coverage | Heavier model runtime and GPU/CPU variance | Keep as calibration candidate |
| OCR/table/layout | PaddleOCR | OCR plus table/layout modules in one ecosystem | Larger dependency footprint, PaddlePaddle runtime setup, and more setup complexity | Candidate for table/layout POC, not default |
| Table | pdfplumber | Strong born-digital table exploration | Does not solve scanned tables alone | Candidate for text-layer table extraction |
| Table | Camelot/Tabula class tools | Useful for ruled or lattice tables | Java/native/tooling constraints vary by machine | Defer until PDF table corpus is larger |
| Local VLM captioning | local VLM adapter | Can caption selected PDF visual regions without an external provider | Heavy model setup, latency, hallucinated captions, and hidden download risk | Future opt-in candidate only |

External VLM captioning and document reasoning are out of v0.1 scope and are
not part of the public release mode set.

## Post-v0.1 Candidate Path

1. `local-ocr-tesseract`
   - Input: cached `pdf_region` image.
   - Output: `pdf_ocr_text` unit with page, bbox, source occurrence, and text
     preview.
   - Gate: OCR disabled by default; missing binary produces no OCR units and no
     indexing failure.

2. `local-table-pdfplumber`
   - Input: born-digital PDF page.
   - Output: `pdf_table` unit with page, bbox when available, normalized table
     preview, row/column counts, and extractor profile.
   - Gate: table extraction claims are limited to born-digital fixture results.

3. `paddleocr-structure-candidate`
   - Input: visual regions or page images.
   - Output: candidate layout/table units.
   - Gate: separate dependency setup, latency, memory, and quality report before
     promotion.

4. `local-vlm-caption-candidate`
   - Input: cached `pdf_region` image.
   - Output: visual-caption text unit with model/profile metadata.
   - Gate: default off, local-only, no remote fallback, no automatic model
     download during measured runs, separate quality and latency report before
     promotion.

## Data Contract

OCR/table units must follow the existing evidence-unit pattern:

- `unit_type`: `pdf_ocr_text`, `pdf_table`, or `pdf_visual_caption`
- `modality`: `text`
- `relative_path`, `page_no`, `bbox`
- `image_no` for OCR/caption units and `table_no` for table units
- `source_kind`: `pdf`
- `extractor_profile`: mode and library profile
- `text_preview`: sanitized OCR text or table preview
- `locality`: required for optional caption candidates and heavier local
  candidates

Payloads must not store absolute source paths, raw OCR engine output, raw
provider payloads, or unredacted secret-like text.

## Release Gate

- Default environment keeps OCR/table modes off.
- Missing optional dependencies must not be treated as successful OCR/table
  extraction.
- OCR quality reports must include fixture count, evaluated query count,
  recall@k/MRR, latency p50/p95/p99, and skipped dependency status.
- Table reports must separate born-digital table extraction from scanned table
  extraction.
- OCR/table reports must include attempted, succeeded, and empty counters.
- Optional OCR/table/VLM candidates must record runtime network calls 0,
  automatic model downloads 0, explicit local cache or install path, and
  external provider fallback 0 before they can support release claims.
- Any external provider mode requires a separate explicit opt-in gate and is
  outside v0.1 default scope.

## Current Status

Current LocalLens evidence supports PDF page text, opt-in local visual region
units, Tesseract-backed local OCR text units, and pdfplumber-backed
born-digital table units. Local VLM captioning has an adapter and
`pdf_visual_caption` contract, but no promoted caption model.

The PDF fixture catalog currently contains 73 synthetic PDFs.

Current measured table POC:

| Area | Result |
| --- | --- |
| Corpus | 73 PDFs |
| Mode | `LOCALLENS_PDF_TABLE_MODE=local-table` |
| Backend | `intfloat/multilingual-e5-small` text, hash vision |
| Units | 86 total units |
| Table counters | attempted 20, indexed 20, empty 0 |
| Evaluated table queries | 18 |
| Table-unit retrieval | recall@1 1.000, recall@5 1.000, recall@10 1.000, MRR@10 1.000 |
| Latency | p50 16.555 ms, p95 17.809 ms, p99 18.535 ms |
| Integrity | failed files 0, stale vectors 0, duplicate vectors 0 |
| Ranking note | table units include page context and receive a small table-intent score adjustment |

Current OCR POC status:

| Area | Result |
| --- | --- |
| Mode | `LOCALLENS_PDF_OCR_MODE=local-ocr` |
| Runtime | Tesseract 5.4.0.20240606, local language data |
| English OCR corpus | latest measured English report uses the 73-PDF fixture |
| Expanded OCR corpus | 73 PDFs with English, Korean, and scanned-table OCR fixtures |
| OCR fixture variants | clean, noisy, rotated, low contrast, bilingual visual |
| English OCR counters | attempted 50, indexed 50, empty 0 |
| Expanded OCR counters | attempted 50, indexed 50 for Korean OCR; attempted 37, indexed 36, empty 1 for scanned-table OCR |
| English OCR retrieval | `eng` PSM 6, 13 queries, recall@1 1.000, recall@5 1.000, MRR@10 1.000 |
| Korean OCR retrieval | `kor` PSM 6, 20 queries, recall@1 1.000, recall@5 1.000, MRR@10 1.000 |
| Scanned-table OCR retrieval | `eng` PSM 4, 10 queries, recall@1 1.000, recall@5 1.000, MRR@10 1.000 |
| Latency | English p50 19.002 ms, Korean p50 16.579 ms, scanned-table p50 44.561 ms |
| Integrity | failed files 0, stale vectors 0, duplicate vectors 0 |
| Test gate | OCR unit creation and missing-binary path are covered by tests |

The scanned-table OCR row is text retrieval from rasterized table images, not
structured table extraction. Handwriting, severe scan degradation, arbitrary
table recovery, chart understanding, and VLM behavior remain outside the
default workflow.

Korean OCR clears the current controlled-fixture promotion bar with 20 queries,
recall@5 1.000, and MRR@10 1.000. This supports only the measured fixture
scope, not broad OCR language-pack quality.

The KOCR query normalization POC is separate from OCR engine quality:
alias-backfill remains off by default and on the 120-PDF / 75 harder-query fixture it measured recall@5 1.000, MRR@10 1.000, top1 1.000, p95 41.294 ms.
Broad OCR quality claim remains blocked.
