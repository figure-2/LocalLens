# LocalLens Release Gate

This gate defines the minimum local checks before publishing LocalLens artifacts.
All paths in evidence must be relative paths or sanitized summaries.
Use `docs/release_evidence_runbook.md` when regenerating the full report set in
a fresh local environment.

## Conda Setup

```powershell
conda create -n locallens python=3.11 -y
conda activate locallens
python -m pip install -e ".[dev]"
python -m pytest -q
```

Default execution uses hash embeddings. Real model execution is opt-in:

```powershell
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"
$env:LOCALLENS_VISION_EMBEDDING_BACKEND="transformers"
$env:LOCALLENS_TEXT_MODEL_NAME="intfloat/multilingual-e5-small"
$env:LOCALLENS_VISION_MODEL_NAME="google/siglip-base-patch16-224"
$env:LOCALLENS_QDRANT_TIMEOUT_SECONDS="60"
```

Release evidence that uses real model backends must run cache-only:

```powershell
$env:LOCALLENS_RELEASE_EVIDENCE_MODE="1"
$env:LOCALLENS_MODEL_CACHE_DIR="<local-model-cache>"
$env:LOCALLENS_MODEL_LOCAL_FILES_ONLY="1"
$env:HF_HUB_OFFLINE="1"
$env:TRANSFORMERS_OFFLINE="1"
```

Use a fresh `LOCALLENS_DATA_DIR` for each model profile check, or run `purge`
before switching vector dimensions.

## Command Catalog

The block below is a command catalog, not the regeneration order. Use
`docs/release_evidence_runbook.md` for fresh-environment regeneration. Run
`release-gate` only after current generated reports and public metric text have
been reconciled.

```powershell
python -m pytest -q
python -m locallens.app.cli release-gate --blocked-terms-file <publication-terms.txt>
python -m locallens.app.cli check-evidence-consistency --claims-file release_evidence_claims.json
python -m locallens.app.cli benchmark benchmarks\fixtures\corpus --golden benchmarks\fixtures\golden_queries.json --out .locallens\benchmark.json
python -m locallens.app.cli scan-artifacts --publication-scan --manifest publication_artifacts.txt --blocked-terms-file <publication-terms.txt>
python -m locallens.app.cli scan-artifacts --manifest repo_hygiene_artifacts.txt --blocked-terms-file <publication-terms.txt>
git diff --check
python -m locallens.app.cli scan-artifacts --publication-scan --manifest publication_artifacts.txt .locallens\benchmark.json --blocked-terms-file <publication-terms.txt>
python -m locallens.app.cli compare-stores benchmarks\fixtures\corpus --golden benchmarks\fixtures\golden_queries.json --server-url http://127.0.0.1:6333 --runs 3 --warmup-runs 1 --out .locallens\compare_repeated.json
python benchmarks\warm_query_benchmark.py benchmarks\fixtures\corpus --golden benchmarks\fixtures\golden_queries.json --runs 3 --warmup-runs 1 --out .locallens\warm_query_benchmark.json
python benchmarks\server_warm_query_compare.py benchmarks\fixtures\corpus --golden benchmarks\fixtures\golden_queries.json --server-url http://127.0.0.1:6333 --runs 3 --warmup-runs 1 --out .locallens\server_warm_query_compare.json
python benchmarks\path_prefix_benchmark.py --files 600 --target-files 60 --queries 20 --runs 3 --out .locallens\path_prefix_benchmark.json
python benchmarks\vision_model_compare.py --model google/siglip-base-patch16-224 --model openai/clip-vit-base-patch32 --out .locallens\vision_model_compare_200.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_TABLE_MODE="local-table"; python -m locallens.app.cli benchmark benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_table_queries.json --out .locallens\pdf_table_rerank_benchmark.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_TABLE_MODE="local-table"; python -m locallens.app.cli benchmark benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_table_queries.json --out .locallens\pdf_table_73_benchmark.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_OCR_MODE="local-ocr"; $env:LOCALLENS_PDF_OCR_LANG="eng"; $env:LOCALLENS_TESSERACT_CMD="<local-tesseract-command>"; $env:LOCALLENS_TESSERACT_PSM="6"; python -m locallens.app.cli benchmark benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_ocr_queries.json --out .locallens\pdf_ocr_stress_benchmark.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_OCR_MODE="local-ocr"; $env:LOCALLENS_PDF_OCR_LANG="eng"; $env:LOCALLENS_TESSERACT_CMD="<local-tesseract-command>"; $env:LOCALLENS_TESSERACT_PSM="6"; python -m locallens.app.cli benchmark benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_ocr_queries.json --out .locallens\pdf_ocr_english_73_benchmark.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_OCR_MODE="local-ocr"; $env:LOCALLENS_PDF_OCR_LANG="kor"; $env:LOCALLENS_TESSERACT_CMD="<local-tesseract-command>"; $env:LOCALLENS_TESSDATA_DIR="<local-tessdata-dir>"; $env:LOCALLENS_TESSERACT_PSM="6"; python -m locallens.app.cli benchmark benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_ocr_korean_queries.json --out .locallens\pdf_ocr_korean_benchmark.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_OCR_MODE="local-ocr"; $env:LOCALLENS_PDF_OCR_LANG="eng"; $env:LOCALLENS_TESSERACT_CMD="<local-tesseract-command>"; $env:LOCALLENS_TESSERACT_PSM="4"; python -m locallens.app.cli benchmark benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_scanned_table_queries.json --out .locallens\pdf_scanned_table_ocr_expanded_benchmark.json
python benchmarks\scanned_table_structure_poc.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_scanned_table_queries.json --tesseract-cmd "<local-tesseract-command>" --lang eng --psm 4 --out .locallens\scanned_table_structure_poc.json
python benchmarks\optional_candidate_preflight.py --candidate paddleocr-table --cache-path .locallens\optional-candidates\paddleocr --out .locallens\optional_candidate_preflight_paddleocr.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_TABLE_MODE="local-table"; python benchmarks\server_warm_query_compare.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_table_queries.json --server-url http://127.0.0.1:6333 --runs 3 --warmup-runs 1 --out .locallens\server_warm_pdf_table_73_loopback_compare.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_OCR_MODE="local-ocr"; $env:LOCALLENS_PDF_OCR_LANG="eng"; $env:LOCALLENS_TESSERACT_CMD="<local-tesseract-command>"; $env:LOCALLENS_TESSERACT_PSM="6"; python benchmarks\server_warm_query_compare.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_ocr_queries.json --server-url http://127.0.0.1:6333 --runs 3 --warmup-runs 1 --out .locallens\server_warm_pdf_ocr_english_73_loopback_compare.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_TABLE_MODE="local-table"; python benchmarks\warm_query_benchmark.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_table_queries.json --runs 3 --warmup-runs 1 --out .locallens\warm_pdf_table_73_benchmark.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_PDF_OCR_MODE="local-ocr"; $env:LOCALLENS_PDF_OCR_LANG="eng"; $env:LOCALLENS_TESSERACT_CMD="<local-tesseract-command>"; $env:LOCALLENS_TESSERACT_PSM="6"; python benchmarks\warm_query_benchmark.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_ocr_queries.json --runs 3 --warmup-runs 1 --out .locallens\warm_pdf_ocr_english_73_benchmark.json
$env:LOCALLENS_PDF_VLM_MODE="local-vlm"; $env:LOCALLENS_TEXT_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; python benchmarks\local_vlm_candidate_poc.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_vlm_caption_queries.json --baseline-report .locallens\server_warm_pdf_table_73_loopback_compare.json --baseline-report .locallens\server_warm_pdf_ocr_english_73_loopback_compare.json --out .locallens\local_vlm_candidate_poc.json
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"; $env:LOCALLENS_QDRANT_TIMEOUT_SECONDS="60"; python benchmarks\qdrant_scale_benchmark.py --sizes 1000 5000 10000 --queries 20 --runs 1 --warmup-runs 1 --server-url http://127.0.0.1:6333 --out .locallens\qdrant_scale_benchmark.json
python -m locallens.app.cli scan-artifacts --publication-scan --manifest publication_artifacts.txt --manifest generated_evidence_artifacts.txt --blocked-terms-file <publication-terms.txt>
python -m locallens.app.cli scan-artifacts --manifest repo_hygiene_artifacts.txt --blocked-terms-file <publication-terms.txt>
```

Live model smoke tests are explicit because cache-fill runs can download
models. Release evidence runs must use the cache-only settings above.

```powershell
$env:LOCALLENS_RUN_LIVE_MODEL_TESTS="1"
python -m pytest tests\test_live_models.py -q
$env:LOCALLENS_RUN_LIVE_MODEL_TESTS=""
```

## Required Checks

| Area | Gate |
| --- | --- |
| Unit and contract tests | `python -m pytest -q` exits 0 |
| Sync | `SyncReport.failed == 0` |
| Store integrity | stale vectors = 0, duplicate vectors = 0 |
| Publication artifacts | publication manifest scan findings = 0 |
| Repository hygiene | repository hygiene manifest scan findings = 0 with the same blocked term file used for publication scans |
| Git diff check | release gate fails on whitespace conflict markers or diff-check errors; output is redacted |
| Git history scan | release gate scans commit messages and historical patch text for blocked or sensitive content; output is redacted |
| Worktree status | release gate fails when tracked or untracked source changes are present |
| Binary artifact scan | PDF text/metadata and image metadata are included in artifact scan |
| Text model | dimension = 384 for `intfloat/multilingual-e5-small` |
| Vision model | dimension = 768 for `google/siglip-base-patch16-224` |
| Release model loading | `LOCALLENS_RELEASE_EVIDENCE_MODE=1`, `LOCALLENS_MODEL_LOCAL_FILES_ONLY=1`, `LOCALLENS_MODEL_CACHE_DIR`, `HF_HUB_OFFLINE=1`, and `TRANSFORMERS_OFFLINE=1` when real model rows support release evidence |
| Evidence consistency | `release_evidence_claims.json` must match generated evidence values; historical reports must not support current claims |
| Public metric tables | `release_evidence_claims.json` table assertions must match public markdown table row and column values |
| Semantic claim guards | `release_evidence_claims.json` text guards must block broad wording when the supporting claim-class gate is hold |
| Hash benchmark fixture | recall@5 >= 0.80, recall@10 >= 0.90, MRR@10 >= 0.70 |
| Live semantic smoke | dimensions, latency, and retrieval metrics recorded; promotion follows the quality threshold table below |
| Search latency | record p50, p95, p99 for text-only and image-only paths |
| Store comparison | local/server reports use the same corpus, profile, and golden file; current command is cold-start smoke |
| Warm query benchmark | query-only passes reuse one indexed collection and record cold/warm latency separately |
| Server warm query benchmark | local path and loopback server runs use the same corpus, profile, golden file, runs, and warmup count |
| Benchmark server target | warm benchmark scripts reject non-loopback URLs unless explicitly overridden |
| Path prefix smoke | scoped result check passes and latency is recorded |
| Vision model comparison | required candidate rows finish with `status: ok` when model downloads are available |
| Vision model selection | selected/fallback/hold decisions record quality, latency, offline reproducibility, and candidate role |
| PDF local layout | default remains `off`; opt-in `local-layout` test verifies visual units, bbox, cache source, and stale cleanup |
| PDF local OCR | default remains `off`; unit tests cover OCR unit creation and missing local binary behavior |
| PDF local table | default remains `off`; opt-in `local-table` report records table-unit quality, table-intent reranking, and integrity |
| Scanned-table structure POC | default remains off; candidate report records local baseline status and dependency status |
| Local VLM caption candidate | default remains `off`; `pdf_visual_caption` units require offline gate, locality payload, and separate promotion decision |
| Optional candidate offline gate | runtime network calls 0, automatic model downloads 0, explicit local cache or install path, external provider fallback 0 |
| Optional table candidate acceptance | dependency/cache preflight plus confirmed offline fields pass before isolated POC; unified structured-output recall, row/cell F1, cell text F1, slice coverage, p95 latency <= 1500 ms, and failure artifacts are recorded |
| Public evidence consistency | README, release notes, benchmark docs, and opt-in docs use the same latest corpus/query/metric source or label older rows as historical |
| Snippet safety | snippets are bounded, redacted, and contain no absolute source paths |
| OCR/table observability | benchmark sync report records attempted, succeeded, and empty counters |
| Qdrant scale smoke | 1k/5k/10k local/server warm-query report records sync failures as 0 before performance interpretation |

Publication scanning uses `publication_artifacts.txt` for shareable docs and
generated evidence reports. Repository hygiene scanning uses
`repo_hygiene_artifacts.txt` for source, tests, fixtures, and docs. Generated
benchmark and comparison JSON is listed in `generated_evidence_artifacts.txt`.
Publication scans are fail-closed: pass an operator-controlled
`--blocked-terms-file` or explicit `--blocked-term` whenever
`publication_artifacts.txt` or `generated_evidence_artifacts.txt` is scanned.
The scan must load active blocked terms; empty or comment-only term files fail
before scanning. The full `release-gate` also rejects underspecified term sets,
so a single placeholder term cannot approve a release. Use
`--publication-scan` for any renamed manifest or direct path list that is
intended for release evidence. Finding output must not print matched
blocked-expression text.
`release-gate` runs pytest, publication scan, generated evidence scan,
canonical evidence consistency, repository hygiene scan, git diff check, git
history scan, and clean worktree status in sequence and stops on the first
failing step. Dirty worktree, git diff, and git history failures are summarized
without listing file names or matched expressions.

If `git_history_scan` fails while current publication and hygiene scans pass,
classify the finding without printing matched blocked terms or raw patch text.
Do not rewrite history, force-push, or publish a release until the operator
explicitly chooses a remediation path. The safe default is to keep the release
blocked and document the blocker. A sanitized public history or controlled
rewrite is a separate high-risk operation.

## Optional Candidate Offline Gate

Optional OCR, table, VLM, or layout candidates can be described in release
evidence only when the measured run records:

- runtime network calls: 0
- automatic model downloads during the measured run: 0
- external provider fallback: 0
- explicit local binary, model cache, or install path
- dependency-missing status when a candidate cannot run locally

Preflight-only reports are readiness checks, not runtime quality measurements.
Their 0 network/download/fallback fields are static until an isolated measured
run exists.

If any item is unknown, the candidate remains exploratory and must not be used
for release claims. This applies to local VLM captioning candidates as well as
heavier OCR/table structure candidates: caption unit creation alone is not
enough for promotion when caption-specific MRR remains below the release bar.

## Quality Promotion Thresholds

These thresholds decide whether a measured row can be promoted from
record-only smoke evidence to release-supporting quality evidence.

| Area | Promote | Hold |
| --- | --- | --- |
| Text semantic retrieval | recall@5 >= 0.85 and MRR@10 >= 0.70 on at least 30 text queries | below either threshold or fewer than 30 text queries |
| Vision image retrieval | top1 >= 0.90, recall@5 >= 0.95, and MRR@10 >= 0.90 on at least 90 image queries | below any threshold |
| Korean OCR retrieval | recall@5 >= 0.95 and MRR@10 >= 0.85 on at least 10 Korean OCR queries | below either threshold or fewer than 10 queries |
| Scanned-table OCR text retrieval | recall@5 >= 0.95 and MRR@10 >= 0.90 on at least 10 raster-table queries | below either threshold |
| Scanned-table structure extraction | structured-output term recall >= 0.85, row F1 >= 0.70, cell F1 >= 0.70, p95 latency <= 1500 ms, offline gate passed, primary term source is structured output, and split claim-class gate allows broad structured-table retrieval | any mixed-source score, missing structure metric, missing offline gate, p95 latency above 1500 ms, structured-output term recall below 0.85, or cell-only/context-only success being used as a broad claim |

Rows in hold status may remain in documentation as measured limitations, but
they must not be summarized as product-quality support.

## Current Evidence

Latest local gate measured on 2026-06-01. Live model rows use opt-in model
execution against the expanded fixture catalog. Image rows are small synthetic
whole-image text-to-image smoke evidence.

| Check | Result |
| --- | --- |
| Python | 3.13.13 |
| OS | Windows 10 build 19045 |
| torch | 2.11.0+cu126, CUDA available |
| qdrant-client | 1.18.0 |
| pdfplumber | 0.11.9 |
| Tesseract command | 5.4.0.20240606 available through configured command |
| Qdrant server | refreshed against Qdrant 1.18.0 bound to `127.0.0.1`; generated reports store the sanitized target label `http://localhost` |
| pytest | 246 passed, 2 skipped, 1 local Qdrant warning |
| live model smoke | 2 passed, 3 local warnings |
| benchmark fixture | 22 files, 46 units, 12 hash smoke queries, recall@5 1.00, recall@10 1.00, MRR@10 1.00 |
| PDF fixture catalog | 73 PDFs available; local-layout smoke remains scoped to existing visual cases |
| semantic fixture catalog | 234 quality queries, 34 text, 200 image |
| benchmark integrity | stale vectors 0, duplicate vectors 0, failed files 0 |
| benchmark speed | local indexing 0.376 s, local p50 search 20.042 ms, local p95 search 24.464 ms |
| repeated store comparison | cold-start smoke not refreshed in this cycle; server warm comparison refreshed separately |
| warm query benchmark | indexed once, 3 warm runs, cold p50 15.740 ms, warm p50 16.563 ms, warm p95 19.159 ms |
| server warm query comparison | text fixture: local warm p50/p95/p99 13.961/17.856/18.753 ms; server warm p50/p95/p99 53.236/72.494/87.772 ms |
| 73-PDF table server warm benchmark | 73 PDFs, 18 queries; local warm p50/p95/p99 31.950/33.947/34.111 ms; server warm p50/p95/p99 39.626/61.807/83.082 ms; sync_failed 0 |
| 73-PDF English OCR server warm benchmark | 73 PDFs, 13 queries; local warm p50/p95/p99 34.703/36.742/36.898 ms; server warm p50/p95/p99 35.620/48.083/53.333 ms; sync_failed 0 |
| repeated local mean | historical pre-refresh value; do not use for current performance claims |
| repeated server mean | historical pre-refresh value; do not use for current performance claims |
| publication manifest scan | 18 shareable docs/files, findings 0 |
| repository hygiene manifest scan | 518 files including source, tests, fixtures, docs, and manifests, findings 0 |
| release evidence scan | publication manifest plus current generated reports, 43 files, findings 0 |
| evidence consistency | `release_evidence_claims.json` matches current generated reports; 125 claims, 100 covered public metric table cells, 14 public text assertions, 156 public table assertions, and 1 semantic text guard checked; historical report references are blocked from current evidence |
| text dimension | 384 |
| text semantic run | 22 files, 46 units, 34 evaluated queries, 90 skipped |
| text semantic quality | recall@5 0.941, recall@10 0.956, MRR@10 0.902 |
| text semantic speed | indexing 0.679 s, p50 search 16.007 ms, p95 search 17.058 ms |
| vision dimension | 768 |
| vision semantic run | 200 files, 200 units, 200 evaluated queries, 34 skipped |
| vision semantic quality | SigLIP top1 accuracy 0.970, recall@5 0.995, MRR@10 0.983 |
| vision hard-negative slice | 176 queries, SigLIP top1 accuracy 0.972, recall@5 1.000, MRR@10 0.986 |
| vision semantic speed | SigLIP indexing 3.211 s, p50 search 17.460 ms, p95 search 19.938 ms |
| vision model comparison | SigLIP top1 0.970, recall@5 0.995, MRR@10 0.983; CLIP top1 0.690, recall@5 0.890, MRR@10 0.778 |
| vision hard-negative slice report | SigLIP top1 failure examples are recorded with sanitized fixture paths, object/color/context confusion labels, slice definition, synthetic-overlap counts, failure-mode counts, null-hit counts, repair targets, and diagnostic oracle repair upper-bound; CLIP weak object slices include printer, tablet, receipt, vial, and workstation |
| PDF local table POC | 73 PDFs, 86 units, table counters 20/20/0, 18 evaluated table queries, recall@1 1.000, recall@5 1.000, MRR@10 1.000 |
| PDF local OCR POC | 73 PDFs, 116 units, OCR counters 50/50/0, 13 English OCR queries, recall@1 1.000, recall@5 1.000, MRR@10 1.000 |
| Korean OCR POC | 73 PDFs, 116 units, OCR counters 50/50/0, 20 Korean OCR queries, recall@1 1.000, recall@5 1.000, MRR@10 1.000 |
| scanned-table OCR POC | 60 PDFs, 102 units, OCR counters 37/36/1, 10 raster-table OCR queries, recall@1 1.000, recall@5 1.000, MRR@10 1.000 |
| scanned-table structure POC | 10 scanned-table PDFs; Tesseract TSV row/cell F1 0.681/0.655, structured term recall 0.764, p95 484.754 ms; Tesseract line-filter postprocess row/cell F1 0.797/0.770, structured term recall 0.513, p95 172.181 ms; Tesseract multipass context-structure tables 9/10, row/cell F1 0.817/0.805, context term recall 0.832, structured term recall 0.555, p95 865.011 ms; raster projection OCR pairing row/cell F1 0.617/0.596, structured term recall 0.371, p95 259.161 ms; raster deskew projection OCR pairing row/cell F1 0.717/0.668, structured term recall 0.413, context term recall 0.731, p95 548.097 ms; all measured candidates remain hold under the structured-output promotion gate; PaddleOCR/PaddlePaddle dependency missing, table-transformer adapter pending |
| optional PaddleOCR preflight | PaddleOCR/PaddlePaddle modules unavailable in the current optional candidate environment, configured cache path missing, version fields present when available, offline fields are static preflight only, decision hold |
| optional Table Transformer preflight | detector dependencies are partly present, configured cache path missing, offline verification missing, offline fields are static preflight only, decision hold |
| local VLM caption candidate POC | 73 PDFs, 50 visual regions attempted, 50 caption units, 14 caption queries, recall@5 0.929, MRR@10 0.735, p50/p95 0.148/0.163 ms, top1 failure count 5, benchmark-only rerank MRR@10 delta 0.018, locality fields network/download/fallback 0; hold_status `hold-quality`, promotion decision hold |
| Qdrant scale smoke | 1k/5k/10k files, local/server sync_failed 0; 10k warm p50 local 667.690 ms, server 82.017 ms |
| path prefix smoke 600 files | scoped 60, runs 3, full p50 34.929 ms, prefix p50 34.480 ms, scope check pass |
| path prefix smoke 3000 files | scoped 300, runs 3, full p50 177.565 ms, prefix p50 160.069 ms, scope check pass |

Live model smoke validates model loading, vector dimensions, fixture indexing,
and retrieval wiring. It is not a large-corpus quality claim and does not
validate OCR, object localization, counting, or broad image generalization.

The warning about local Qdrant payload indexes is expected in local mode and
does not affect correctness checks. Server-mode performance must be measured
separately.

The 73-PDF catalog is the current available fixture set for table and English
OCR local/server warm evidence. Generated reports store the sanitized target
label `http://localhost`. The same cycle added a local VLM caption adapter POC
report; it remains hold-status because no configured local caption candidate
produced `pdf_visual_caption` units.

## Stop Conditions

- Any release artifact scan finding.
- Any indexing failure hidden inside a zero process exit.
- A vector dimension mismatch in an existing data directory.
- Any benchmark report that cannot be written because the artifact scan fails.
- Any UI action that leaves progress active after an error.
- Any warm-cache performance claim without a query-only benchmark report that
  reuses one indexed collection.
- Any PDF visual claim when `LOCALLENS_PDF_VISUAL_MODE` is not explicit or PDF
  visual tests fail.
- Any structured scanned-table claim without a candidate POC report.
- Any broad scanned-table wording when the broad claim-class gate is hold.
- Any server-mode performance claim when the server endpoint was unavailable or
  only cold-start smoke evidence exists.
- Any optional OCR/table/VLM candidate release claim without offline-gate
  evidence for network calls, automatic downloads, cache/install path, and
  fallback behavior.
- Any public evidence page that reports stale corpus/query/metric numbers
  without labeling them historical.
- Any historical generated report listed as current evidence or referenced by
  the shareable documentation surface.
- Any dirty worktree state before release tagging or publication.
