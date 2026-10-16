# LocalLens v0.1 Release Notes

## Summary

LocalLens v0.1 is a local-first retrieval engine for selected folders. It
indexes text, PDF page text, and standalone images into Qdrant local mode and
returns evidence units with relative paths, snippets, page/chunk numbers, and
scores.

## Included

- CLI commands for scan, index, search, purge, benchmark, artifact scan, and
  store comparison.
- Tkinter desktop adapter with folder selection, indexing, search, Top-K,
  modality/extension filters, path-prefix filtering, progress state, and file
  open handling.
- Qdrant named vectors for text and vision profiles.
- Manifest-backed sync with added, updated, deleted, skipped, excluded, failed,
  stale, and duplicate-vector checks.
- Default secret-like file exclusions, publication scanning, and repository
  hygiene scanning.
- Opt-in live semantic checks for text and image embedding profiles.
- Opt-in PDF `local-layout` mode that creates local visual region units with
  page number and bbox metadata without OCR or VLM calls.
- Opt-in PDF `local-ocr` and `local-table` POC modes for local Tesseract OCR
  and born-digital pdfplumber table units.
- OCR/table observability counters in sync and benchmark reports.
- Qdrant local/server scale warm-query smoke script for 1k/5k/10k synthetic
  corpora.
- A separate structured scanned-table POC harness for local candidate
  comparison.

## Verified Scope

### Corpus

| Area | Files | Units | Images | Queries |
| --- | ---: | ---: | ---: | ---: |
| Text fixture | 22 | 46 |  | 34 |
| Image fixture |  |  | 200 | 200 |
| PDF fixture | 73 |  |  |  |

### Retrieval Quality

| Area | Top1 | Recall@5 | Recall@10 | MRR@10 | Queries |
| --- | ---: | ---: | ---: | ---: | ---: |
| Text model smoke |  | 0.941 | 0.956 | 0.902 | 34 |
| SigLIP vision smoke | 0.970 | 0.995 |  | 0.983 | 200 |
| Hard-negative image slice | 0.972 | 1.000 |  | 0.986 | 176 |
| CLIP fallback smoke | 0.690 | 0.890 |  | 0.778 | 200 |

### PDF Table And OCR POC

| Area | Files | Units | Attempts | Indexed | Empty | Queries | Recall@1 | Recall@5 | MRR@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PDF table POC | 73 | 86 | 20 | 20 | 0 | 18 | 1.000 | 1.000 | 1.000 |
| English OCR POC | 73 | 116 | 50 | 50 | 0 | 13 | 1.000 | 1.000 | 1.000 |
| Korean OCR POC | 73 | 116 | 50 | 50 | 0 | 20 | 1.000 | 1.000 | 1.000 |
| Scanned-table OCR POC | 60 | 102 | 37 | 36 | 1 | 10 | 1.000 | 1.000 | 1.000 |

### Warm Query Smoke

| Area | Local p50 ms | Local p95 ms | Local p99 ms | Server p50 ms | Server p95 ms | Server p99 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Server warm query smoke | 13.961 | 17.856 | 18.753 | 53.236 | 72.494 | 87.772 |
| 73-PDF table server warm smoke | 31.950 | 33.947 | 34.111 | 39.626 | 61.807 | 83.082 |
| 73-PDF English OCR server warm smoke | 34.703 | 36.742 | 36.898 | 35.620 | 48.083 | 53.333 |

### Optional Candidate Status

| Area | Attempts | Units | Queries | Recall@5 | MRR@10 | Network | Downloads | Fallback | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Optional PaddleOCR preflight | 0 | 0 | 0 | 0.000 | 0.000 | 0 | 0 | 0 | hold |
| Optional Table Transformer preflight | 0 | 0 | 0 | 0.000 | 0.000 | 0 | 0 | 0 | hold |
| Local VLM caption candidate POC | 50 | 50 | 14 | 0.929 | 0.735 | 0 | 0 | 0 | `hold-quality` |

Structured scanned-table extraction remains hold status. Its candidate-level
metrics are documented in `docs/benchmark_eval.md` because context text,
structured output, row/cell scoring, and latency are separate measurements.
Release claims are split into structured-cell extraction, table-context
retrieval, and broad structured-table retrieval classes. A cell-only or
context-only pass must not be summarized as broad structured-table retrieval.
PaddleOCR/PaddlePaddle dependency and cache path are not ready in the current
optional candidate environment. Version fields are present when available.
The offline fields are static preflight only. Optional PaddleOCR preflight does not support a release claim.
Table Transformer style detection is also a hold-only optional preflight: the
detector dependencies are partly present, but the configured cache path and
offline readiness verification are missing.
The Qdrant scale smoke covers 1k/5k/10k synthetic files with sync failures 0;
the 10k warm p50 row is local 667.690 ms and server 82.017 ms.

These are small fixture measurements. They validate wiring and curated retrieval
behavior, not broad production quality.

## Limitations

- PDF visual region extraction is not enabled by default.
- PDF OCR and table extraction remain explicit opt-in modes.
- VLM captioning, chart understanding, handwriting, severe scan degradation,
  broad language-pack quality, and structured scanned-table extraction are not
  validated.
- The current image evaluation uses standalone synthetic fixture images. The
  results are not broad image understanding claims.
- Qdrant server comparison is loopback-only smoke evidence, not throughput,
  concurrency, or multi-user performance evidence.
- PDF OCR/table POC modes need larger real-world-style corpora before product
  quality claims.
- Text semantic retrieval and Korean OCR clear the current controlled-fixture
  bars. This does not support broad production search or broad OCR language
  quality claims.
- Optional OCR/table/VLM candidates require offline-gate evidence: runtime
  network calls 0, automatic model downloads 0, explicit local cache or install
  path, and external provider fallback 0.
- PaddleOCR-style scanned-table structure candidates are not validated until
  dependency/cache preflight and unified structured-output quality gates pass.
- Local VLM captioning produced `pdf_visual_caption` units in the controlled
  PDF fixture, but remains hold status because caption-specific recall@5 and
  MRR@10 did not clear the promotion bar. No local caption model is promoted.
- Access control, enterprise policy enforcement, and RAG answer generation are
  outside v0.1.

## Publication Checklist

- Run `python -m pytest -q`.
- Regenerate benchmark reports.
- Scan publication artifacts and generated reports with publication blocked
  terms.
- Scan repository hygiene artifacts before publishing source changes.
- Refresh this file only with measured LocalLens results.
