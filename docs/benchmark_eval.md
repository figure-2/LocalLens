# Benchmark Evaluation

LocalLens uses two benchmark layers.

## Hash Smoke Layer

The default `hash` backend is for fast local regression checks. It verifies:

- scanner and extractor flow
- Qdrant upsert/search/delete behavior
- report writing and artifact scanning
- integrity counters such as stale and duplicate vectors

Do not interpret hash backend retrieval scores as semantic quality.

## Semantic Quality Layer

Semantic quality checks use backend-specific golden queries:

- `backend_profile: "sentence-transformers"` for text quality
- `backend_profile: "transformers"` for vision quality
- `backend_profile: "transformers:<model-name>"` for model-specific vision checks
- `modality: "text"` or `modality: "image"` to avoid mixed-score ambiguity

Golden query entries can define `relevant` units with gain values:

```json
{
  "id": "image-red-square-en-001",
  "query": "a red square on a light background",
  "modality": "image",
  "backend_profile": "transformers",
  "top_k": 10,
  "relevant": [
    {
      "relative_path": "red_square.png",
      "unit_type": "image",
      "image_no": 0,
      "gain": 3,
      "max_rank": 1
    }
  ],
  "tags": ["image", "english", "color", "shape"]
}
```

## Metrics

Benchmark reports include:

- recall@1, recall@5, recall@10
- hit@1 and top1 accuracy
- MRR@10 and nDCG@10
- optional per-tag and per-modality quality slices
- p50, p95, p99 search latency
- stale vector count and duplicate vector count
- skipped query count when a golden query targets a different backend profile

Structured `relevant` entries are evaluated at the search-unit level when
`unit_type`, `page_no`, `chunk_no`, `image_no`, `table_no`, `unit_id`, or
`max_rank` are provided. Path-only `relevant_paths` entries remain path-level
smoke checks.

## Current Fixture Sets

| Fixture | Purpose | Queries |
| --- | --- | ---: |
| `golden_queries.json` | hash smoke and integrity gate | 12 |
| `golden_quality_queries.json` | opt-in semantic text and vision quality | 234 |
| `golden_image_non_filename_queries.json` | opt-in image quality check with semantic-free alias filenames | 110 |
| `golden_pdf_queries.json` | opt-in PDF text, visual, and table unit checks | 13 |
| `golden_pdf_table_queries.json` | opt-in born-digital table-unit checks | 18 |
| `golden_pdf_ocr_queries.json` | opt-in local OCR text-unit checks | 13 |
| `golden_pdf_ocr_korean_queries.json` | opt-in Korean local OCR text-unit checks | 20 |
| `golden_pdf_scanned_table_queries.json` | opt-in scanned-table OCR text-unit checks | 10 |
| `corpus/` | text corpus | 22 files |
| `image_corpus/` | vision corpus | 200 images |
| `image_corpus_non_filename/` | alias vision corpus whose filenames do not encode object, color, or context | 110 images |
| `pdf_corpus/` | PDF text, scanned-like, table, OCR, diagram, Korean OCR, and scanned-table cases | 73 PDFs |

Current opt-in semantic measurements:

| Path | Backend | Scope | Key Result |
| --- | --- | --- | --- |
| text | `sentence-transformers:intfloat/multilingual-e5-small` | 34 evaluated text queries, 22 files, 46 units | recall@5 0.941, recall@10 0.956, MRR@10 0.902 |
| vision | `google/siglip-base-patch16-224` | 200 evaluated image queries, 200 image units | top1 0.970, recall@5 0.995, MRR@10 0.983 |
| vision-non-filename | `google/siglip-base-patch16-224` | 110 alias image queries, 110 image units | top1 1.000, recall@5 1.000, MRR@10 1.000, semantic filename matches 0 |

Text backend selection uses the following current rule:

| Candidate | Role | Current Evidence | Decision |
| --- | --- | --- | --- |
| `hash` | deterministic regression backend | no model download, stable dimensions, fast scan/index/search tests | Keep as default for unit, smoke, and release-gate wiring checks |
| `intfloat/multilingual-e5-small` | opt-in semantic text backend | 384-dimensional vectors, 34 evaluated text queries, recall@5 0.941, recall@10 0.956, MRR@10 0.902, search p50 16.007 ms | Keep as v0.1 semantic text profile for the controlled fixture scope |
| Larger multilingual embedding models | future quality candidates | not measured through the current cache-only fixture and release evidence gate | Hold until same-corpus metrics, latency, artifact scan, and offline loading evidence exist |

The selected text profile is a compact multilingual semantic smoke path. It is
not a broad production search claim, and the `hash` backend remains the default
for deterministic local regression tests.

The vision fixture is a small synthetic whole-image text-to-image smoke check.
It does not validate OCR, object localization, counting, or large-corpus
generalization.

## Promotion Criteria

Measured rows are promoted only when they clear both metric and corpus-size
requirements. Otherwise they remain record-only smoke or limitation evidence.

| Area | Current Status | Promotion Bar | Decision |
| --- | --- | --- | --- |
| Text semantic retrieval | recall@5 0.941, MRR@10 0.902, 34 queries | recall@5 >= 0.85 and MRR@10 >= 0.70 on at least 30 text queries | Promote only for the controlled text fixture scope |
| Vision image retrieval | top1 0.970, recall@5 0.995, MRR@10 0.983, 200 queries | top1 >= 0.90, recall@5 >= 0.95, MRR@10 >= 0.90 on at least 90 image queries | Promote for small curated image fixture scope |
| Filename-independent image retrieval | top1 1.000, recall@5 1.000, MRR@10 1.000, 110 alias queries, semantic filename matches 0 | top1 >= 0.90, recall@5 >= 0.95, MRR@10 >= 0.90, semantic filename matches 0 | Record as alias-fixture non-regression evidence; not broad image understanding |
| Korean OCR retrieval | recall@5 1.000, MRR@10 1.000, 20 queries | recall@5 >= 0.95 and MRR@10 >= 0.85 on at least 10 Korean OCR queries | Promote only for the controlled Korean OCR fixture scope |
| Scanned-table OCR text retrieval | recall@5 1.000, MRR@10 1.000, 10 queries | recall@5 >= 0.95 and MRR@10 >= 0.90 on at least 10 raster-table queries | Promote only for OCR text retrieval from controlled raster tables |
| Scanned-table structure extraction | best mixed POC context term recall 0.832, structured output term recall 0.555, row/cell F1 0.817/0.805, 10 documents | structured output term recall >= 0.85, row F1 >= 0.70, cell F1 >= 0.70, p95 latency <= 1500 ms, offline gate, and primary source structured-output | Hold as improved structure POC candidate |
| Local VLM visual captioning | 50 visual regions attempted, 50 caption units, recall@5 0.929, MRR@10 0.735, 14 visual-caption queries | recall@5 >= 0.95 and MRR@10 >= 0.85 on the same PDF fixture with offline gate passed | Hold as caption quality is below the promotion bar |

## Vision Model Candidate Smoke

The same fixture and harness currently show:

| Model | Dimension | Top1 | Recall@5 | MRR@10 | Search p50 ms | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `google/siglip-base-patch16-224` | 768 | 0.970 | 0.995 | 0.983 | 17.460 | Keep as v1 opt-in default |
| `openai/clip-vit-base-patch32` | 512 | 0.690 | 0.890 | 0.778 | 21.853 | Keep as fallback candidate |

These numbers are small curated fixture results. They do not show broad model
quality or real-world image understanding. SigLIP requires max-length text
padding in the Transformers processor path; without that preprocessing, its
image-text scores are invalid for this harness.

Vision model selection uses this order:

| Criterion | Priority | Current Decision |
| --- | ---: | --- |
| Hard-negative quality | 1 | SigLIP is selected for the controlled fixture because top1, recall@5, and MRR@10 exceed the promotion bar |
| Offline reproducibility | 2 | Both candidates can run cache-only in the current release evidence path |
| Latency | 3 | SigLIP remains within the current small-fixture latency budget despite a larger vector dimension |
| Compatibility fallback | 4 | CLIP remains a fallback candidate because it is common and lightweight, but current quality is below the selected backend |
| Untested candidates | hold | Other vision models are not release candidates until they run through the same fixture, cache-only settings, and artifact scan |

Hard-negative slice details are recorded in
`.locallens/vision_model_compare_200.json`. The report derives object, color,
and context keys from sanitized fixture names and records top1 failure examples
with `hard_negative_type`, `contrast_pair_id`, `confusable_attribute`,
slice definition, synthetic-overlap counts, failure-mode counts, null-hit
counts, repair targets for weak slices, and a diagnostic oracle repair
upper-bound. The oracle experiment uses only existing top-k outputs to separate
rank-order weakness from missing-candidate weakness; it is not a product
ranking change. File stem parsing is part of the report schema:
`<object>_<color>_<context>.png`. Hard-negative and synthetic tags can overlap;
the overlap is reported and does not make the slice a real-world quality
claim.
SigLIP keeps hard-negative recall@5 at 1.000. CLIP's weakest object slices in
the current report include printer, tablet, receipt, vial, and workstation, so
CLIP remains a fallback candidate rather than the selected vision backend for
this fixture. The diagnostic oracle repair upper-bound shows CLIP baseline
hard-negative top1 0.682 could reach 0.938 if all existing top-k repairable
hits were ranked first, while 11 hard-negative queries remain missing from
top-5. This means the next CLIP experiment should separate reranking from
corpus/query expansion.

The alias image fixture in
`.locallens/vision_model_compare_non_filename.json` stores object, color, and
context keys only in the golden query metadata while the image filenames remain
opaque. This checks whether the vision benchmark still passes when filenames
do not carry semantic labels.
Current cache-only SigLIP results on this alias fixture are 110 evaluated
queries, top1 1.000, recall@5 1.000, MRR@10 1.000, and 0 semantic filename
matches. CLIP on the same alias fixture reports top1 0.736, recall@5 0.936,
and MRR@10 0.829. Treat this as filename-independence evidence for the
controlled fixture, not a broader image-understanding claim.

The alias rerank diagnostic remains benchmark-only and does not change product
runtime ordering:

| Experiment | Scope | Baseline | Diagnostic | Decision |
| --- | --- | --- | --- | --- |
| Alias fixture rerank diagnostic | 110 alias queries, 29 targeted weak-slice queries, semantic filename matches 0 | CLIP targeted top1 0.207, recall@5 0.793, MRR@10 0.477 | CLIP targeted top1 0.931, recall@5 0.931, MRR@10 0.931 | SigLIP non-regression passed; product runtime unchanged |

## PDF Table POC

Born-digital table extraction is off by default and uses `local-table` mode:

```powershell
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"
$env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"
$env:LOCALLENS_PDF_TABLE_MODE="local-table"
python -m locallens.app.cli benchmark benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_table_queries.json --out .locallens\pdf_table_73_benchmark.json
```

Current measured table POC with table-aware page context, table-intent score
adjustment, and table extraction counters:

| Files | Units | Table Attempts | Tables Indexed | Evaluated Table Queries | Recall@5 | MRR@10 | Search p50 ms | Integrity |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 73 | 86 | 20 | 20 | 18 | 1.000 | 1.000 | 16.555 | failed 0, stale 0, duplicate 0 |

The table-unit benchmark validates curated born-digital table evidence
retrieval. It does not validate scanned-table extraction, arbitrary spreadsheet
layout recovery, or broad table-ranking quality.

## PDF OCR POC

Local OCR is off by default and uses `local-ocr` mode with a local Tesseract
command:

```powershell
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="sentence-transformers"
$env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"
$env:LOCALLENS_PDF_OCR_MODE="local-ocr"
$env:LOCALLENS_PDF_OCR_LANG="eng"
$env:LOCALLENS_TESSERACT_CMD="<local-tesseract-command>"
$env:LOCALLENS_TESSERACT_PSM="6"
python -m locallens.app.cli benchmark benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_ocr_queries.json --out .locallens\pdf_ocr_english_73_benchmark.json
```

Current measured OCR POC with clean, noisy, rotated, low-contrast, and
bilingual-visual fixtures:

| Scope | Lang/PSM | Files | Units | OCR Attempts | OCR Indexed | Evaluated Queries | Recall@5 | MRR@10 | Search p50 ms | Integrity |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| English OCR stress | `eng` / PSM 6 | 73 | 116 | 50 | 50 | 13 | 1.000 | 1.000 | 19.002 | failed 0, stale 0, duplicate 0 |
| Korean OCR hard cases | `kor` / PSM 6 | 73 | 116 | 50 | 50 | 20 | 1.000 | 1.000 | 16.579 | failed 0, stale 0, duplicate 0 |
| Scanned-table OCR hard cases | `eng` / PSM 4 | 60 | 102 | 37 | 36 | 10 | 1.000 | 1.000 | 44.561 | failed 0, stale 0, duplicate 0 |

Korean OCR query normalization is tracked as a separate default-off candidate.
The measured POC uses the same product search path with a controlled 120-PDF corpus and 75 harder Korean OCR query variants.
This is a query-normalization candidate only; it does not broaden the OCR engine quality claim.

| Candidate | Default | Fixture | Queries | Recall@5 | MRR@10 | Top1 | Miss@5 | Search p50 ms | Search p95 ms | Decision |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Product off | current default | 120 PDFs / 75 harder KOCR queries | 75 | 0.827 | 0.820 | 0.813 | 13 | 23.531 | 29.729 | Baseline |
| Alias-backfill | off by default | 120 PDFs / 75 harder KOCR queries | 75 | 1.000 | 1.000 | 1.000 | 0 | 29.474 | 41.294 | Default-off candidate; broad OCR claim blocked |

Korean OCR hard-case top1 accuracy is 1.000 after adding noisy and bilingual
cases and applying Korean syllable-aware text-unit reranking. The scanned-table hard-case run
had one empty OCR output among 37 attempts but all 10 evaluated table-image
queries were recovered at rank 1.

## Scanned Table Structure POC

Structured scanned-table extraction is tracked separately from text OCR:

```powershell
python benchmarks\scanned_table_structure_poc.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_scanned_table_queries.json --tesseract-cmd "<local-tesseract-command>" --lang eng --psm 4 --out .locallens\scanned_table_structure_poc.json
```

Current measured POC:

| Candidate | Status | Documents | Tables Detected | Primary Term Recall | Context Term Recall | Structured Output Term Recall | Mean Row F1 | Mean Cell F1 | p50 ms | p95 ms | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Tesseract TSV | ok | 10 | 10 | 0.764 | 0.764 | 0.764 | 0.681 | 0.655 | 165.518 | 484.754 | Keep as local OCR-box baseline |
| Tesseract line-filter postprocess | ok | 10 | 9 | 0.513 | 0.764 | 0.513 | 0.797 | 0.770 | 163.279 | 172.181 | Same OCR backend as Tesseract TSV; useful structure candidate, not a text-retrieval replacement |
| Tesseract multipass context-structure | ok | 10 | 9 | 0.832 | 0.832 | 0.555 | 0.817 | 0.805 | 773.467 | 865.011 | Strongest mixed context-plus-structure POC candidate; hold below term-recall bar and high latency |
| Raster projection OCR pairing | ok | 10 | 7 | 0.371 | 0.764 | 0.371 | 0.617 | 0.596 | 181.783 | 259.161 | True detector/OCR pairing smoke; hold below baseline |
| Raster deskew projection OCR pairing | ok | 10 | 8 | 0.413 | 0.731 | 0.413 | 0.717 | 0.668 | 500.003 | 548.097 | Rotation-search detector/OCR pairing smoke; improves projection but remains hold |
| PaddleOCR structure | dependency missing | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | Requires PaddleOCR plus PaddlePaddle runtime; evaluate only in a separate optional adapter |
| Table Transformer | adapter pending | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | Evaluate only with detector plus OCR pairing |

These candidates are not enabled in the product runtime.
The table above is a diagnostic view, not a ranking table. Mixed-source
candidates such as multipass are not directly rank-comparable to unified
structured-output candidates because their context term recall and structure
metrics can come from separate candidate paths.
Primary term recall uses the candidate's declared primary source. The
multipass row uses raw multipass OCR context for primary term recall and a
separately selected table-like row structure for row/cell metrics, so it is not
a claim that one unified structured-table output achieved every metric. For
structured extraction promotion, use `Structured Output Term Recall`. The
report also includes a `structure_promotion_gate` object per candidate. The
gate requires structured-output term recall >= 0.85, row F1 >= 0.70, cell F1
>= 0.70, p95 latency <= 1500 ms, offline gate evidence, and `primary_term_recall_source`
equal to `structured-output`.
Release tooling also records split scanned-table claim classes so a
cell-extraction-only result cannot support a broad structured-table retrieval
claim. `structured_cell_extraction`, `table_context_retrieval`, and
`broad_structured_table_retrieval` are evaluated separately; only the broad
class follows the `structure_promotion_gate` promotion decision.
All scanned-table claim classes require measured offline locality and p95
latency <= 1500 ms on the current fixture before they can become eligible.

PaddleOCR-style candidates must pass a separate preflight before isolated POC
execution:

```powershell
python benchmarks\optional_candidate_preflight.py --candidate paddleocr-table --cache-path .locallens\optional-candidates\paddleocr --out .locallens\optional_candidate_preflight_paddleocr.json
```

Current preflight result is hold: PaddleOCR and PaddlePaddle modules are not
available in the current optional environment, the configured cache path is
missing, and offline verification is not confirmed. The report records
dependency versions when available. This is environment readiness evidence, not
table quality evidence.

PaddleOCR-style isolated POC acceptance:

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

This validates OCR wiring on controlled raster-text fixtures and selected
language/segmentation settings. Korean OCR used local `kor` language data from
a local tessdata directory. The scanned-table row validates OCR text retrieval
from rasterized table images; it does not validate structured table extraction.
Handwriting, severe scan degradation, arbitrary table recovery, and broad OCR
language quality remain unvalidated.

## Local VLM Caption POC

Local VLM captioning is off by default. The adapter interface and
`pdf_visual_caption` unit contract are implemented, but no caption model is
promoted.

```powershell
$env:LOCALLENS_PDF_VLM_MODE="local-vlm"
python benchmarks\local_vlm_candidate_poc.py benchmarks\fixtures\pdf_corpus --golden benchmarks\fixtures\golden_pdf_vlm_caption_queries.json --baseline-report .locallens\server_warm_pdf_table_73_loopback_compare.json --baseline-report .locallens\server_warm_pdf_ocr_english_73_loopback_compare.json --out .locallens\local_vlm_candidate_poc.json
```

Current measured POC:

| Fixture | Visual Attempts | Caption Units | Evaluated Queries | Recall@5 | MRR@10 | Search p50 ms | Search p95 ms | Locality | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 73 PDF catalog | 50 | 50 | 14 | 0.929 | 0.735 | 0.148 | 0.163 | network 0, downloads 0, fallback 0, configured local cache | `hold-quality` |

The POC compares against OCR/table baseline reports on the same PDF fixture.
Table and English OCR baselines both remain at recall@5 1.000 and MRR@10
1.000. Local VLM captioning is not promoted because caption-specific recall@5
and MRR@10 are below the current gate.

Weak-slice analysis records top1 failure count 5. The failing cases include
receipt, scanned-like, multilingual notice, and product-diagram queries. The
weakest slices are receipt, scanned-like, and multilingual/English/Korean
wording.

The benchmark-only caption rerank diagnostic uses query text and generated
caption text only; golden labels are used only for scoring. The current
IDF-style diagnostic keeps top1 at 0.643 and improves MRR@10 from 0.735 to 0.752,
but it remains benchmark-only and product ranking remains unchanged.

Additional local caption candidates may be evaluated with the same harness, but
they are not public release claims until the canonical generated evidence,
public tables, and release-gate assertions are updated in the same change.

## Path Prefix Smoke

`benchmarks/path_prefix_benchmark.py` creates a synthetic corpus with scoped and
decoy folders to verify prefix correctness and local-mode latency.

| Files | Scoped Files | Runs | Full Search p50 ms | Prefix Search p50 ms | Scope Check |
| ---: | ---: | ---: | ---: | ---: | --- |
| 600 | 60 | 3 | 34.929 | 34.480 | pass |
| 3000 | 300 | 3 | 177.565 | 160.069 | pass |

This is a local smoke benchmark. It does not prove large-corpus performance.

## Server Mode Comparison

Use the same corpus and golden file for both stores:

```powershell
python -m locallens.app.cli compare-stores benchmarks\fixtures\corpus --golden benchmarks\fixtures\golden_queries.json --server-url http://127.0.0.1:6333 --runs 3 --warmup-runs 1 --out .locallens\compare_repeated.json
```

Comparison reports store a sanitized server target label. They do not write the
raw server URL.

Current local fixture measurement:

| Store | Files | Units | Indexing Seconds | Search p50 ms | Search p95 ms | Recall@10 | MRR@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| local path | 22 | 46 | 0.378 | 16.897 | 20.588 | 1.00 | 1.00 |

The current `compare-stores` command creates fresh isolated data directories
and fresh collection names for each measured pair. Treat its repeated output as
cold-start functional smoke, not warm-cache performance evidence.

| Store | Runs | Mean Indexing Seconds | Mean Search p50 ms | Mean Search p95 ms | Recall@10 | MRR@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| local path | 3 | 0.235 | 4.203 | 5.533 | 1.00 | 1.00 |
| server HTTP | 3 | 2.059 | 35.421 | 63.828 | 1.00 | 1.00 |

This small fixture is a functional comparison, not a throughput benchmark.
Use larger corpora and repeated warm runs before drawing performance conclusions.

## Warm Query Benchmark

Use the warm query benchmark when the goal is query-only latency after one
indexing pass:

```powershell
python benchmarks\warm_query_benchmark.py benchmarks\fixtures\corpus --golden benchmarks\fixtures\golden_queries.json --runs 3 --warmup-runs 1 --out .locallens\warm_query_benchmark.json
```

The report separates:

- `cold_pass`: first measured query pass after indexing
- `warmup_runs`: unreported query-only passes
- `warm_passes`: measured query-only passes against the same collection
- `warm_aggregate`: p50/p95/p99 summaries across measured warm passes

Do not use cold-start store comparison rows as warm-cache evidence.

Current local warm-query smoke:

| Files | Units | Runs | Cold p50 ms | Warm p50 ms | Warm p95 ms | Recall@10 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 22 | 46 | 3 | 15.740 | 16.563 | 19.159 | 1.00 |

Current local/server warm-query comparison used a loopback Qdrant server and the
same corpus, profile, and golden file:

| Store | Files | Units | Indexing Seconds | Cold p50 ms | Warm p50 ms | Warm p95 ms | Warm p99 ms | Recall@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| local path | 22 | 46 | 0.380 | 13.751 | 13.961 | 17.856 | 18.753 | 1.00 |
| server HTTP | 22 | 46 | 2.280 | 54.447 | 53.236 | 72.494 | 87.772 | 1.00 |

This small fixture shows server overhead in the current local environment. It is
not a large-corpus throughput result.

Current expanded PDF table warm-query comparison used the 73-PDF corpus,
`local-table` mode, and the same 18 table queries for local path and loopback
server query-only runs:

| Store | Files | Units | Indexing Seconds | Cold p50 ms | Warm p50 ms | Warm p95 ms | Warm p99 ms | Recall@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| local path | 73 | 86 | 3.079 | 31.498 | 31.950 | 33.947 | 34.111 | 1.00 |
| server HTTP | 73 | 86 | 4.364 | 38.164 | 39.626 | 61.807 | 83.082 | 1.00 |

Current 73-PDF English OCR warm-query comparison used `local-ocr` mode and the
same 13 OCR queries for local path and loopback server query-only runs:

| Store | Files | Units | Indexing Seconds | Cold p50 ms | Warm p50 ms | Warm p95 ms | Warm p99 ms | Recall@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| local path | 73 | 116 | 8.910 | 36.087 | 34.703 | 36.742 | 36.898 | 1.00 |
| server HTTP | 73 | 116 | 11.424 | 35.878 | 35.620 | 48.083 | 53.333 | 1.00 |

## Qdrant Scale Warm-Query Smoke

The scale benchmark creates synthetic markdown corpora and measures query-only
latency after one indexing pass. It uses hash embeddings and does not evaluate
retrieval quality:

```powershell
$env:LOCALLENS_TEXT_EMBEDDING_BACKEND="hash"
$env:LOCALLENS_VISION_EMBEDDING_BACKEND="hash"
$env:LOCALLENS_QDRANT_TIMEOUT_SECONDS="60"
python benchmarks\qdrant_scale_benchmark.py --sizes 1000 5000 10000 --queries 20 --runs 1 --warmup-runs 1 --server-url http://127.0.0.1:6333 --out .locallens\qdrant_scale_benchmark.json
```

| Files | Store | Units | Indexing Seconds | Cold p50 ms | Warm p50 ms | Warm p95 ms | Sync Failed |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | local path | 2000 | 22.997 | 79.047 | 77.138 | 90.413 | 0 |
| 1000 | server HTTP | 2000 | 35.827 | 74.300 | 65.467 | 100.525 | 0 |
| 5000 | local path | 10000 | 79.788 | 330.193 | 343.429 | 396.784 | 0 |
| 5000 | server HTTP | 10000 | 171.037 | 77.660 | 73.851 | 95.709 | 0 |
| 10000 | local path | 20000 | 165.546 | 663.289 | 667.690 | 751.766 | 0 |
| 10000 | server HTTP | 20000 | 368.099 | 83.214 | 82.017 | 106.102 | 0 |

This is a single-machine loopback benchmark with synthetic files and hash
vectors. It is suitable for regression comparison, not production throughput
claims.
