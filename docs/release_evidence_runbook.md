# Release Evidence Regeneration Runbook

This runbook gives the ordered steps for recreating LocalLens release evidence
in a fresh local environment. It does not enable optional remote services.

## Principles

- Generated reports are written under `.locallens/`.
- `.locallens/` is local working data and is not tracked by Git.
- Public documentation must use values from current generated reports listed in
  `generated_evidence_artifacts.txt`.
- Reports that use real model backends must run cache-only.
- Optional OCR/table/VLM candidates remain hold-status until their offline gate
  and quality gates pass.

## 1. Prepare Environment

```powershell
conda create -n locallens python=3.11 -y
conda activate locallens
python -m pip install -e ".[dev]"
python -m pytest -q
```

Create a publication term file before running publication scans:

```powershell
Set-Content -Path .locallens\publication-terms.txt -Value "<operator-defined-term>" -Encoding UTF8
```

The term file must contain the active release screening set. Empty,
comment-only, or placeholder-only files fail closed.

## 2. Set Cache-Only Model Environment

Use these variables only when producing release evidence with real model
backends:

```powershell
$env:LOCALLENS_RELEASE_EVIDENCE_MODE="1"
$env:LOCALLENS_MODEL_CACHE_DIR="<local-model-cache>"
$env:LOCALLENS_MODEL_LOCAL_FILES_ONLY="1"
$env:HF_HUB_OFFLINE="1"
$env:TRANSFORMERS_OFFLINE="1"
$env:LOCALLENS_QDRANT_TIMEOUT_SECONDS="60"
```

Do not run release evidence with automatic model downloads enabled.

## 3. Regenerate Core Reports

Run the command catalog in `docs/release_gate.md` in this order:

| Order | Report Group | Required Output |
| ---: | --- | --- |
| 1 | hash fixture | `.locallens/benchmark.json` |
| 2 | text semantic | `.locallens/live_text_benchmark_next.json` |
| 3 | local/server smoke | `.locallens/compare_repeated.json`, `.locallens/warm_query_benchmark.json`, `.locallens/server_warm_query_compare.json` |
| 4 | path prefix | `.locallens/path_prefix_benchmark.json` |
| 5 | vision model comparison | `.locallens/vision_model_compare_200.json`, `.locallens/vision_model_compare_non_filename.json` |
| 6 | vision diagnostic | `.locallens/vision_weak_slice_non_filename.json` |
| 7 | PDF table/OCR | `.locallens/pdf_table_73_benchmark.json`, `.locallens/pdf_ocr_english_73_benchmark.json`, `.locallens/pdf_ocr_korean_benchmark.json` |
| 8 | scanned-table | `.locallens/pdf_scanned_table_ocr_expanded_benchmark.json`, `.locallens/scanned_table_structure_poc.json` |
| 9 | warm PDF local/server | `.locallens/warm_pdf_table_73_benchmark.json`, `.locallens/warm_pdf_ocr_english_73_benchmark.json`, `.locallens/server_warm_pdf_table_73_loopback_compare.json`, `.locallens/server_warm_pdf_ocr_english_73_loopback_compare.json` |
| 10 | optional candidate preflight | `.locallens/optional_candidate_preflight_paddleocr.json`, `.locallens/optional_candidate_preflight_table_transformer.json`, `.locallens/local_vlm_candidate_poc.json` |
| 11 | scale smoke | `.locallens/qdrant_scale_benchmark.json` |

The Qdrant server rows require a loopback server at `http://127.0.0.1:6333`.
If the server is unavailable, do not update server-supported current claims.

## 4. Optional Candidate Checks

Run optional candidate preflight without installing heavy runtimes implicitly:

```powershell
python benchmarks\optional_candidate_preflight.py --candidate paddleocr-table --cache-path .locallens\optional-candidates\paddleocr --out .locallens\optional_candidate_preflight_paddleocr.json
python benchmarks\optional_candidate_preflight.py --candidate table-transformer --cache-path .locallens\optional-candidates\table-transformer --out .locallens\optional_candidate_preflight_table_transformer.json
```

Hold status is expected when modules, cache paths, or confirmed offline checks
are missing. These preflight reports are readiness checks only. Their
0 network/download/fallback fields are static until an isolated measured run
exists.

Local VLM captioning remains off unless explicitly enabled for the POC:

```powershell
$env:LOCALLENS_PDF_VLM_MODE="local-vlm"
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="hash"
$env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"
python benchmarks\local_vlm_candidate_poc.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_vlm_caption_queries.json --baseline-report .locallens\server_warm_pdf_table_73_loopback_compare.json --baseline-report .locallens\server_warm_pdf_ocr_english_73_loopback_compare.json --out .locallens\local_vlm_candidate_poc.json
```

Promotion remains blocked unless caption units are greater than zero, the
measured caption runtime records runtime network calls 0, automatic downloads
0, external fallback 0, and caption-specific recall@5/MRR@10/latency pass the
current gate.

## 5. Verify Current Evidence

After reports are regenerated, run:

```powershell
python -m locallens.app.cli check-evidence-consistency --claims-file release_evidence_claims.json
python -m locallens.app.cli scan-artifacts --publication-scan --manifest publication_artifacts.txt --manifest generated_evidence_artifacts.txt --blocked-terms-file .locallens\publication-terms.txt
python -m locallens.app.cli scan-artifacts --manifest repo_hygiene_artifacts.txt --blocked-terms-file .locallens\publication-terms.txt
python -m locallens.app.cli release-gate --blocked-terms-file .locallens\publication-terms.txt
```

The release gate must pass before publishing docs or creating a tag. It scans
publication artifacts, generated evidence, repository hygiene paths, git diff
check output, git history text, and dirty worktree state. Run it after all
intended source and document changes are committed.

## 6. Update Public Metrics

If any JSON value changes:

- update public metric tables only with values from current reports
- update `release_evidence_claims.json` so the same values are checked
- keep older reports out of `generated_evidence_artifacts.txt`
- label older rows as historical if they must remain in narrative text

Do not convert hold-status candidate reports into quality claims.

## 7. Final Repository Check

```powershell
git status --short
git diff --check
```

Expected final state before commit:

- code and docs changes are intentional
- `.locallens/` remains untracked
- scans have zero findings
- evidence consistency passes

After commit, run `release-gate` again. The clean worktree step should pass
with no file list in the generated gate report.
