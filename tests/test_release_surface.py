from __future__ import annotations

import json
from pathlib import Path
import re

from locallens.app.cli import _artifact_paths, _blocked_terms, _manifest_artifact_paths
from locallens.security.artifact_scan import scan_artifacts


def _paths_from_manifest(root: Path, manifest_name: str) -> list[Path]:
    manifest_paths = _manifest_artifact_paths([str(root / manifest_name)])
    return _artifact_paths(manifest_paths)


def _manifest_entries(root: Path, manifest_name: str) -> set[str]:
    entries = set()
    for line in (root / manifest_name).read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            entries.add(entry.replace("\\", "/"))
    return entries


def test_publication_surface_has_no_artifact_findings():
    root = Path(__file__).resolve().parents[1]

    findings = scan_artifacts(
        _paths_from_manifest(root, "publication_artifacts.txt"),
        banned_terms=_blocked_terms([], None),
    )

    assert findings == []


def test_repo_hygiene_surface_has_no_artifact_findings():
    root = Path(__file__).resolve().parents[1]

    findings = scan_artifacts(
        _paths_from_manifest(root, "repo_hygiene_artifacts.txt"),
        banned_terms=_blocked_terms([], None),
    )

    assert findings == []


def test_default_publication_terms_block_internal_markers(tmp_path: Path):
    marker = "release-hold-marker"
    terms = tmp_path / "terms.txt"
    terms.write_text(f"{marker}\n", encoding="utf-8")
    artifact = tmp_path / "report.md"
    artifact.write_text(f"contains {marker}", encoding="utf-8")

    findings = scan_artifacts(
        [artifact],
        banned_terms=_blocked_terms([], str(terms)),
    )

    assert findings
    assert {finding.reason for finding in findings} == {"blocked expression"}
    assert all(marker not in finding.reason for finding in findings)


def test_publication_terms_are_external_inputs_only(tmp_path: Path):
    terms = tmp_path / "terms.txt"
    marker = "release-boundary-marker"
    terms.write_text(f"{marker}\n", encoding="utf-8")

    assert _blocked_terms([], None) == []
    assert _blocked_terms([], str(terms)) == [marker]


def test_publication_surface_supports_injected_publication_terms(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    terms = tmp_path / "publication_terms.txt"
    absent_term = "neutral-absent-marker"
    terms.write_text(f"{absent_term}\n", encoding="utf-8")

    findings = scan_artifacts(
        _paths_from_manifest(root, "publication_artifacts.txt"),
        banned_terms=_blocked_terms(
            [
                line.strip()
                for line in terms.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ],
            None,
        ),
    )

    assert findings == []


def test_publication_surface_excludes_code_and_fixtures():
    root = Path(__file__).resolve().parents[1]
    artifact_paths = _paths_from_manifest(root, "publication_artifacts.txt")
    relative_paths = {path.relative_to(root).as_posix() for path in artifact_paths}

    assert not any(path.startswith("locallens/") for path in relative_paths)
    assert not any(path.startswith("tests/") for path in relative_paths)
    assert not any(path.startswith("benchmarks/fixtures/") for path in relative_paths)


def test_repo_hygiene_surface_includes_binary_fixture_paths():
    root = Path(__file__).resolve().parents[1]
    artifact_paths = _paths_from_manifest(root, "repo_hygiene_artifacts.txt")

    assert root / "benchmarks" / "fixtures" / "image_corpus" / "red_square.png" in artifact_paths


def test_generated_evidence_manifest_matches_release_gate_json_outputs():
    root = Path(__file__).resolve().parents[1]
    manifest_entries = _manifest_entries(root, "generated_evidence_artifacts.txt")
    public_text = (root / "README.md").read_text(encoding="utf-8")
    for doc in (root / "docs").rglob("*.md"):
        public_text += "\n" + doc.read_text(encoding="utf-8")
    release_gate_outputs = {
        path.replace("\\", "/")
        for path in re.findall(r"\.locallens[\\/][A-Za-z0-9_.-]+\.json", public_text)
    }

    assert release_gate_outputs <= manifest_entries


def test_release_gate_uses_generated_evidence_manifest():
    root = Path(__file__).resolve().parents[1]
    gate = (root / "docs" / "release_gate.md").read_text(encoding="utf-8")

    assert "python -m locallens.app.cli release-gate" in gate
    assert "--publication-scan --manifest publication_artifacts.txt" in gate
    assert "--manifest generated_evidence_artifacts.txt" in gate
    assert ".locallens\\benchmark.json .locallens\\live_text_benchmark.json" not in gate


def test_generated_evidence_manifest_entries_are_json_reports():
    root = Path(__file__).resolve().parents[1]
    entries = _manifest_entries(root, "generated_evidence_artifacts.txt")

    assert entries
    assert all(entry.startswith(".locallens/") for entry in entries)
    assert all(entry.endswith(".json") for entry in entries)


def test_generated_evidence_manifest_uses_canonical_current_reports():
    root = Path(__file__).resolve().parents[1]
    entries = _manifest_entries(root, "generated_evidence_artifacts.txt")

    assert ".locallens/live_text_benchmark_next.json" in entries
    assert ".locallens/vision_model_compare_200.json" in entries
    assert ".locallens/pdf_scanned_table_ocr_expanded_benchmark.json" in entries
    assert ".locallens/live_text_benchmark.json" not in entries
    assert ".locallens/live_vision_benchmark.json" not in entries
    assert ".locallens/pdf_scanned_table_ocr_benchmark.json" not in entries


def test_release_gate_documents_optional_candidate_offline_gate():
    root = Path(__file__).resolve().parents[1]
    gate = (root / "docs" / "release_gate.md").read_text(encoding="utf-8")
    ocr_table = (root / "docs" / "pdf_ocr_table_opt_in.md").read_text(
        encoding="utf-8"
    )
    structure = (root / "docs" / "scanned_table_structure_poc.md").read_text(
        encoding="utf-8"
    )

    required_terms = [
        "runtime network calls 0",
        "automatic model downloads 0",
        "explicit local cache or install path",
        "external provider fallback 0",
    ]

    for text in (gate, ocr_table, structure):
        for term in required_terms:
            assert term in text

    for term in (
        "LOCALLENS_RELEASE_EVIDENCE_MODE=1",
        "LOCALLENS_MODEL_LOCAL_FILES_ONLY=1",
        "LOCALLENS_MODEL_CACHE_DIR",
        "HF_HUB_OFFLINE=1",
        "TRANSFORMERS_OFFLINE=1",
    ):
        assert term in gate


def test_release_gate_documents_quality_promotion_thresholds():
    root = Path(__file__).resolve().parents[1]
    gate = (root / "docs" / "release_gate.md").read_text(encoding="utf-8")
    benchmark = (root / "docs" / "benchmark_eval.md").read_text(encoding="utf-8")

    for text in (gate, benchmark):
        assert "Text semantic retrieval" in text
        assert "Korean OCR retrieval" in text
        assert "Scanned-table structure extraction" in text
        assert "p95 latency <= 1500 ms" in text
        assert "Hold" in text


def test_text_model_profile_is_claim_bound_to_public_benchmark_doc():
    root = Path(__file__).resolve().parents[1]
    claims = json.loads((root / "release_evidence_claims.json").read_text(encoding="utf-8"))
    benchmark = (root / "docs" / "benchmark_eval.md").read_text(encoding="utf-8")

    text_profile_claims = [
        item for item in claims["checks"] if item["id"] == "text-current-model-profile"
    ]

    assert len(text_profile_claims) == 1
    assert (
        text_profile_claims[0]["equals"]
        == "sentence-transformers:intfloat/multilingual-e5-small"
    )
    assert "| text | `sentence-transformers:intfloat/multilingual-e5-small` |" in benchmark
    assert "Keep as v0.1 semantic text profile for the controlled fixture scope" in benchmark


def test_table_transformer_hold_is_visible_in_public_release_docs():
    root = Path(__file__).resolve().parents[1]
    release_notes = (root / "docs" / "release_notes_v0.1.md").read_text(encoding="utf-8")
    release_gate = (root / "docs" / "release_gate.md").read_text(encoding="utf-8")
    structure = (root / "docs" / "scanned_table_structure_poc.md").read_text(
        encoding="utf-8"
    )

    assert (
        "| Optional Table Transformer preflight | 0 | 0 | 0 | 0.000 | 0.000 | 0 | 0 | 0 | hold |"
        in release_notes
    )
    assert "| optional Table Transformer preflight |" in release_gate
    assert "| Table Transformer style detector |" in structure
    assert "Hold behind a separate adapter and OCR pairing gate" in structure
    assert "It does not support a release claim" in structure


def test_scanned_table_claim_classes_block_cell_only_broad_claims():
    root = Path(__file__).resolve().parents[1]
    benchmark = (root / "docs" / "benchmark_eval.md").read_text(encoding="utf-8")
    release_gate = (root / "docs" / "release_gate.md").read_text(encoding="utf-8")
    release_notes = (root / "docs" / "release_notes_v0.1.md").read_text(
        encoding="utf-8"
    )
    structure = (root / "docs" / "scanned_table_structure_poc.md").read_text(
        encoding="utf-8"
    )

    assert "cell-extraction-only result cannot support a broad" in benchmark
    assert "split claim-class gate allows broad structured-table retrieval" in release_gate
    assert "Release claims are split into structured-cell extraction" in release_notes
    assert "must not be summarized as broad structured-table retrieval" in release_notes
    assert "Cell-only success must" in structure
    assert "not automatically become a broad structured-table release claim" in structure


def test_scanned_table_semantic_guard_is_claim_bound():
    root = Path(__file__).resolve().parents[1]
    claims = json.loads((root / "release_evidence_claims.json").read_text(encoding="utf-8"))
    gate = (root / "docs" / "release_gate.md").read_text(encoding="utf-8")

    guard_ids = {item["id"] for item in claims.get("semantic_text_guards", [])}

    assert "scanned-table-broad-claim-semantic-guard" in guard_ids
    assert "Any broad scanned-table wording when the broad claim-class gate is hold" in gate


def test_paddleocr_preflight_hold_is_visible_in_public_release_docs():
    root = Path(__file__).resolve().parents[1]
    release_notes = (root / "docs" / "release_notes_v0.1.md").read_text(encoding="utf-8")

    assert (
        "| Optional PaddleOCR preflight | 0 | 0 | 0 | 0.000 | 0.000 | 0 | 0 | 0 | hold |"
        in release_notes
    )
    assert "Optional PaddleOCR preflight does not support a release claim" in release_notes
    assert "offline fields are static preflight only" in release_notes


def test_optional_preflight_runtime_guard_contract_is_claim_bound():
    root = Path(__file__).resolve().parents[1]
    claims = json.loads((root / "release_evidence_claims.json").read_text(encoding="utf-8"))
    claim_ids = {item["id"] for item in claims["checks"]}

    assert "optional-paddleocr-isolated-poc-not-ready" in claim_ids
    assert "optional-paddleocr-runtime-guard-required" in claim_ids
    assert "optional-table-transformer-isolated-poc-not-ready" in claim_ids
    assert "optional-table-transformer-runtime-guard-required" in claim_ids


def test_pdf_ocr_table_doc_uses_expanded_hard_case_counts():
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs" / "pdf_ocr_table_opt_in.md").read_text(encoding="utf-8")

    assert "Expanded OCR corpus | 73 PDFs" in text
    assert "Korean OCR retrieval | `kor` PSM 6, 20 queries" in text
    assert "Scanned-table OCR retrieval | `eng` PSM 4, 10 queries" in text
    assert "Korean OCR retrieval | `kor` PSM 6, 2 queries" not in text


def test_release_notes_do_not_overstate_image_fixture_style():
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs" / "release_notes_v0.1.md").read_text(encoding="utf-8")

    assert "| Image fixture |  |  | 200 | 200 |" in text
    assert "120 standalone sanitized-style images" not in text


def test_public_docs_do_not_present_remote_vlm_as_release_mode():
    root = Path(__file__).resolve().parents[1]
    for doc_name in ("pdf_multimodal_opt_in.md", "pdf_ocr_table_opt_in.md"):
        text = (root / "docs" / doc_name).read_text(encoding="utf-8")
        mode_table = text.split("## Unit Contract", maxsplit=1)[0]

        assert "| `remote-vlm` |" not in mode_table
        assert "out of v0.1 scope" in mode_table


def test_public_docs_avoid_optional_debug_detail_switches():
    root = Path(__file__).resolve().parents[1]
    public_text = ""
    for doc in (root / "docs").rglob("*.md"):
        public_text += "\n" + doc.read_text(encoding="utf-8")

    assert "--include-document-details" not in public_text
    assert "operator-confirmed" not in public_text
    assert "operator-verified" not in public_text
