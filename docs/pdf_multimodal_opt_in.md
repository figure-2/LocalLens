# PDF Multimodal Opt-In

LocalLens v0.1 indexes PDF text by default. PDF internal images, tables,
figures, and scanned pages are not part of the default workflow.

## Goal

Add PDF visual evidence only through explicit opt-in modes while preserving the
local-first privacy boundary.

## Modes

| Mode | Default | Behavior | Release Claim |
| --- | --- | --- | --- |
| `off` | yes | Extract page text only | PDF text retrieval |
| `local-layout` | no | Extract embedded visual placements as local `pdf_region` units without OCR or VLM calls | PDF visual unit discovery |
| `local-ocr` | no | Add local OCR text to PDF image/region units | PDF OCR retrieval |
| `local-vlm` | no | Caption selected PDF visual regions with a local model adapter after offline-gate checks | Future opt-in candidate only |

External VLM provider workflows are out of v0.1 scope and are not part of the
public release mode set.

Enable the local layout POC explicitly:

```powershell
$env:LOCALLENS_PDF_VISUAL_MODE="local-layout"
python -m locallens.app.cli index .\benchmarks\fixtures\pdf_corpus
```

## Unit Contract

PDF visual units should use the same indexing surface as other search units:

- `unit_type`: `pdf_region` for page-bounded visual placements, `pdf_image`
  only when no placement box is available, `pdf_ocr_text` for OCR text, or
  `pdf_visual_caption` for opt-in local caption text
- `modality`: `image` for visual embeddings, `text` for OCR/caption text
- `relative_path`, `page_no`, `image_no`
- `bbox`: page-relative bounding box when available
- `source_kind`: `pdf`
- `extractor_profile`: extractor name and version
- `text_preview`: OCR or caption preview when explicitly enabled
- `locality`: required for optional caption candidates and must record runtime
  network calls, automatic model downloads, local cache/install status, and
  external fallback count

Absolute paths, raw provider payloads, and secret-like text must not be stored in
payloads or public evidence.

## Current Local Layout Behavior

- Uses PyMuPDF to locate embedded visual placements.
- Writes temporary cropped region images under `.locallens/cache/pdf_images/`.
- Embeds cached region images through the configured vision backend.
- Stores only relative PDF paths, page numbers, bbox metadata, and compact
  previews in Qdrant payloads.
- Tracks the PDF visual mode in the manifest so `off` and `local-layout`
  transitions trigger reindex and stale vector removal.

## Local VLM Caption Contract

`local-vlm` is separate from `local-layout`, OCR, and table extraction. It
creates `pdf_visual_caption` text units only when the configured adapter returns
caption text. It remains off by default.

Release evidence for a local caption candidate must show:

- runtime network calls: 0
- automatic model downloads: 0
- external provider fallback: 0
- sanitized local cache/install status
- recall@5, MRR@10, and latency measured on the same PDF fixture used for
  OCR/table/layout baselines

The current adapter surface is implemented, but no caption model is promoted.
The current candidate POC is hold-status because no configured local caption
candidate produced `pdf_visual_caption` units.

Local caption model evaluation follows a lightweight-first policy. Smaller
caption-capable candidates are tested before stronger quality baselines so the
project can measure whether low-footprint local captions are sufficient for
retrieval. No candidate name or model family supports a release claim until the
same-fixture offline gate, caption-unit, recall/MRR, latency, and artifact-scan
checks pass.

## Recommended Implementation Order

1. Keep `local-layout` behind `LOCALLENS_PDF_VISUAL_MODE`.
2. Maintain deterministic fixture tests for visual mode transitions and payload
   metadata.
3. Expand `benchmarks/fixtures/pdf_corpus/` with born-digital PDFs,
   scanned pages, table-heavy pages, diagram-heavy pages, and mixed Korean/English
   pages.
4. Add golden queries for page text, embedded image, table/diagram region, and
   no-result negative cases.
5. Add `local-ocr` only after local OCR dependency and quality gates are fixed.
6. Design any local VLM captioning as a separate opt-in adapter with no remote
   fallback and no automatic model download during measured release runs.
7. Evaluate local caption candidates from smaller-footprint models toward
   stronger quality baselines, using the same visual-caption fixture and
   promotion thresholds.
8. Keep any external-provider workflow out of v0.1 public release claims.

## Non-Goals For v0.1

- Default OCR or default VLM calls.
- Default local VLM captioning.
- Claims about PDF chart understanding.
- Claims about scanned document quality.
- Storage of raw OCR/VLM payloads in public reports.
