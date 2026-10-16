# Scanned Table Structure POC

Structured scanned-table extraction is not part of the default LocalLens
runtime. The default remains OCR/table modes off.

## Candidate Scope

| Candidate | Role | Current Decision |
| --- | --- | --- |
| Tesseract TSV | Local baseline for OCR word boxes and row grouping | Use as the first POC harness |
| Tesseract multipass context plus structure | Reuses local OCR across multiple PSM profiles, keeps raw OCR context for term recall, and selects the best table-like row structure | Keep as the strongest mixed context-plus-structure POC candidate, still below promotion bar |
| Raster projection plus Tesseract TSV | Local detector/OCR pairing smoke using projected grid lines | Keep as measured hold candidate below baseline |
| Raster deskew projection plus Tesseract TSV | Local detector/OCR pairing smoke with small-angle rotation search | Keep as measured hold candidate; improves projection recall but remains below multipass |
| PaddleOCR structure pipeline | Candidate for OCR plus table structure recovery | Keep behind a separate adapter, PaddlePaddle runtime setup, offline gate, and unified row/cell/text quality gate |
| Table Transformer style detector | Candidate for table detection and structure regions | Hold behind a separate adapter and OCR pairing gate |
| pdfplumber | Born-digital table extraction | Keep for `local-table`; not used for scanned images |

## Acceptance Gate

- The feature remains opt-in and local-only.
- Candidate adapters must not become required dependencies until selected.
- Reports must include candidate status, documents tested, tables detected,
  primary/context/structured-output term recall, row/cell structure metrics,
  p95 latency, promotion-gate decision, missing dependencies, and errors.
- Optional candidates must record runtime network calls 0, automatic model downloads 0, explicit local cache or install path, and external provider fallback 0 before they can support release claims.
- PaddleOCR-style candidates must pass a preflight report before isolated POC
  execution and must report unified row/cell/text metrics from the same
  structured output path. Dependency-missing rows are hold evidence, not
  quality evidence.
- Publication docs can claim only measured POC behavior.
- Broad table recovery, handwriting, severe scan degradation, and multi-page
  table stitching remain out of scope until separate evidence exists.

## PaddleOCR-Style Candidate Acceptance

| Metric | Minimum |
| --- | --- |
| Offline gate | runtime network 0, automatic downloads 0, fallback 0, configured local cache/install path |
| Dependency packaging | optional environment only; no default dependency promotion |
| Tables detected | >= 0.90 overall and no zero-detection rotated/skewed/merged-cell slice |
| Structured output term recall | >= 0.85 from the same structured output used for row/cell scoring |
| Row F1 / Cell F1 | row F1 >= 0.75 and cell F1 >= 0.75 |
| Cell text F1 | >= 0.70 |
| p95 latency | <= 1500 ms per first-page table document on the current fixture |
| Failure artifact | sanitized per-query failure records for empty, exception, low-structure, and low-text cases |

## Promotion Criteria

The current Tesseract TSV row is a local baseline, not a product-quality table
structure feature. Promotion requires structured output term recall >= 0.85,
row F1 >= 0.70, cell F1 >= 0.70, p95 latency <= 1500 ms, offline-gate evidence, primary
term source set to `structured-output`, and a passing artifact scan. The
current multipass candidate improves row/cell metrics but remains below the
structured-output term-recall bar and has higher latency. Its primary
term-recall score comes from raw multipass OCR context while row/cell scores
come from the selected structure rows, so it must not be described as one
unified structured-table output.

The release tooling separates scanned-table claim classes. A
`structured_cell_extraction` result can become eligible only for the narrow
cell extraction claim; it does not imply title, caption, or surrounding context
retrieval. A `table_context_retrieval` result can become eligible only for the
context retrieval claim; it does not imply row/cell structure quality. The
broad `broad_structured_table_retrieval` claim is allowed only when the
`structure_promotion_gate` promotes the same candidate. Cell-only success must
not automatically become a broad structured-table release claim.
All claim classes require measured offline locality and p95 latency <= 1500 ms
on the current fixture before they can become eligible.

## POC Command

```powershell
python benchmarks\scanned_table_structure_poc.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_scanned_table_queries.json --tesseract-cmd "<local-tesseract-command>" --lang eng --psm 4 --out .locallens\scanned_table_structure_poc.json
```

The script records Tesseract TSV baseline results and dependency status rows for
heavier structure candidates. It does not enable any candidate in the product
runtime. Per-document details are omitted by default from public reports.

The measured table below is diagnostic, not a direct ranking table. Mixed-source
candidates are not directly rank-comparable to future unified structured-output
candidates because context term recall and row/cell structure can come from
separate candidate paths.

Run optional candidate preflight before any PaddleOCR-style isolated POC:

```powershell
python benchmarks\optional_candidate_preflight.py --candidate paddleocr-table --cache-path .locallens\optional-candidates\paddleocr --out .locallens\optional_candidate_preflight_paddleocr.json
```

The current PaddleOCR preflight is hold-status because the optional modules and
configured cache path are not available in this environment. This does not
measure table quality and does not support a release claim. The report records
module availability, dependency versions when installed, cache readiness, and
whether the offline fields are verified before any isolated POC can
start.

The current Table Transformer preflight is also hold-status because the
configured detector cache path is missing and offline verification is not
confirmed. It does not support a release claim until an isolated
detector/OCR pairing POC passes the same offline and structured-output gates.

Current Tesseract TSV baseline evidence on the 10-document scanned-table
fixture records tables detected 10/10, mean term recall 0.764, mean row F1
0.681, mean cell F1 0.655, p50 165.518 ms, and p95 484.754 ms.

The local Tesseract line-filter postprocess candidate records tables detected
9/10, mean term recall 0.513, mean row F1 0.797, mean cell F1 0.770, p50
163.279 ms, and p95 172.181 ms. It is derived from the same Tesseract TSV OCR
backend and only changes row postprocessing. It improves row/cell structure
metrics but drops text term recall, so it is a structure candidate only and not
a replacement for OCR text retrieval.

The Tesseract multipass context-plus-structure candidate records tables
detected 9/10, mean term recall 0.832, mean row F1 0.817, mean cell F1 0.805,
p50 773.467 ms, and p95 865.011 ms. Its structured-output term recall is
0.555. It is the strongest current mixed context-plus-structure candidate, but
it remains hold because structured-output term recall is still below 0.85,
latency is substantially higher than the single PSM baselines, and term recall
and structure metrics come from separate candidate sources.

The raster projection OCR pairing candidate records tables detected 7/10, mean
term recall 0.371, mean row F1 0.617, mean cell F1 0.596, p50 181.783 ms, and
p95 259.161 ms. The raster deskew projection variant records tables detected
8/10, mean structured-output term recall 0.413, context term recall 0.731,
mean row F1 0.717, mean cell F1 0.668, p50 500.003 ms, and p95 548.097 ms.
These are true local detector/OCR pairing
smokes, but they remain hold status because they do not exceed the stronger
Tesseract candidates on the current fixture. All rows remain below the
structure promotion bar.
