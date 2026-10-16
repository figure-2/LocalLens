from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from locallens.benchmarks.runner import run_benchmark
import locallens.benchmarks.runner as runner
from locallens.core.config import Settings
from locallens.benchmarks.runner import write_report
from locallens.core.types import BenchmarkReport, SearchResult, SyncReport


pytest.importorskip("qdrant_client")


def test_benchmark_reports_retrieval_quality_metrics(tmp_path: Path):
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "one.md").write_text("exact retrieval target")
    golden = tmp_path / "golden.json"
    golden.write_text(
        '{"queries":[{"query":"exact retrieval target","relevant_paths":["one.md"]}]}',
        encoding="utf-8",
    )
    settings = Settings(data_dir=tmp_path / "data")

    report = run_benchmark(source, queries=[], settings=settings, golden_path=golden)

    assert report.evaluated_queries == 1
    assert report.recall_at_5 == 1.0
    assert report.recall_at_10 == 1.0
    assert report.mrr_at_10 == 1.0
    assert report.recall_at_1 == 1.0
    assert report.hit_at_1 == 1.0
    assert report.ndcg_at_10 == 1.0
    assert report.stale_vector_count == 0
    assert report.duplicate_vector_count == 0
    assert report.qdrant_disk_bytes >= 0
    assert report.query_results[0]["expected_paths"] == ["one.md"]
    assert report.query_results[0]["first_hit_rank"] == 1
    assert report.query_results[0]["top_results"][0]["relative_path"] == "one.md"


def test_benchmark_is_isolated_between_runs(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "first.md").write_text("first benchmark target")
    (second / "second.md").write_text("second benchmark target")
    first_golden = tmp_path / "first.json"
    second_golden = tmp_path / "second.json"
    first_golden.write_text(
        '{"queries":[{"query":"first benchmark target","relevant_paths":["first.md"]}]}',
        encoding="utf-8",
    )
    second_golden.write_text(
        '{"queries":[{"query":"second benchmark target","relevant_paths":["second.md"]}]}',
        encoding="utf-8",
    )

    first_report = run_benchmark(first, [], settings, golden_path=first_golden)
    second_report = run_benchmark(second, [], settings, golden_path=second_golden)

    assert first_report.files == 1
    assert second_report.files == 1
    assert first_report.units == 2
    assert second_report.units == 2


def test_benchmark_filters_golden_queries_by_backend_profile(tmp_path: Path):
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "one.md").write_text("exact retrieval target", encoding="utf-8")
    golden = tmp_path / "golden.json"
    golden.write_text(
        """
        {
              "queries": [
                {
                  "query": "exact retrieval target",
                  "backend_profile": "hash",
                  "relevant_paths": ["one.md"]
                },
                {
                  "query": "semantic paraphrase target",
                  "backend_profile": "sentence-transformers",
                  "relevant_paths": ["one.md"]
                }
              ]
            }
        """,
        encoding="utf-8",
    )
    settings = Settings(data_dir=tmp_path / "data")

    report = run_benchmark(source, queries=[], settings=settings, golden_path=golden)

    assert report.evaluated_queries == 1
    assert report.skipped_queries == 1
    assert report.recall_at_1 == 1.0
    assert report.ndcg_at_10 == 1.0


def test_benchmark_filters_golden_queries_by_model_specific_backend_profile(tmp_path: Path):
    source = tmp_path / "images"
    source.mkdir()
    (source / "one.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
        b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
        b"\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA"
        b"\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    golden = tmp_path / "golden.json"
    golden.write_text(
        """
        {
          "queries": [
            {
              "query": "one image",
              "modality": "image",
              "backend_profile": "transformers:clip-model",
              "relevant_paths": ["one.png"]
            },
            {
              "query": "one image",
              "modality": "image",
              "backend_profile": "transformers:siglip-model",
              "relevant_paths": ["one.png"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        vision_embedding_backend="hash",
        vision_model_name="clip-model",
    )

    items = runner._effective_query_items(
        runner._load_golden_queries(golden),
        [],
        settings,
    )

    assert items == []

    settings = Settings(
        data_dir=tmp_path / "data",
        vision_embedding_backend="transformers",
        vision_model_name="clip-model",
    )
    items = runner._effective_query_items(
        runner._load_golden_queries(golden),
        [],
        settings,
    )

    assert [item["backend_profile"] for item in items] == ["transformers:clip-model"]


def test_quality_fixture_has_multilingual_text_and_image_coverage():
    root = Path(__file__).resolve().parents[1]
    quality = json.loads(
        (root / "benchmarks" / "fixtures" / "golden_quality_queries.json").read_text(
            encoding="utf-8"
        )
    )
    queries = quality["queries"]
    ids = [item["id"] for item in queries]
    tags = {tag for item in queries for tag in item.get("tags", [])}
    text_queries = [item for item in queries if item.get("modality") == "text"]
    image_queries = [item for item in queries if item.get("modality") == "image"]
    image_paths = {
        target["relative_path"]
        for item in image_queries
        for target in item.get("relevant", [])
    }
    image_dir = Path(__file__).resolve().parents[1] / "benchmarks" / "fixtures" / "image_corpus"

    assert len(ids) == len(set(ids))
    assert {"korean", "english", "image"} <= tags
    assert len(text_queries) >= 30
    assert len(image_queries) >= 200
    assert len(image_paths) >= 200
    assert all((image_dir / path).exists() for path in image_paths)
    assert "synthetic" in tags
    assert "hard-negative" in tags
    assert "realworld-style" in tags
    assert "sanitized-style" in tags


def test_pdf_fixture_catalog_has_text_and_visual_cases():
    root = Path(__file__).resolve().parents[1]
    pdf_dir = root / "benchmarks" / "fixtures" / "pdf_corpus"
    golden = json.loads(
        (root / "benchmarks" / "fixtures" / "golden_pdf_queries.json").read_text(
            encoding="utf-8"
        )
    )
    queries = golden["queries"]
    pdf_names = {path.name for path in pdf_dir.glob("*.pdf")}
    relevant_paths = {
        target["relative_path"]
        for item in queries
        for target in item.get("relevant", [])
    }
    unit_types = {
        target["unit_type"]
        for item in queries
        for target in item.get("relevant", [])
    }

    assert {
        "born_digital_notes.pdf",
        "contract_summary.pdf",
        "scanned_like_page.pdf",
        "scanned_receipt_like.pdf",
        "table_report.pdf",
        "invoice_like_table.pdf",
        "diagram_layout.pdf",
        "product_diagram.pdf",
        "process_flow.pdf",
        "mixed_language_notes.pdf",
        "multilingual_visual_notice.pdf",
        "report_appendix.pdf",
    } <= pdf_names
    assert relevant_paths <= pdf_names
    assert {"document", "pdf_region", "pdf_table"} <= unit_types
    assert {item["modality"] for item in queries} == {"text", "image"}
    assert len(pdf_names) >= 30
    assert len(queries) >= 13


def test_pdf_expansion_fixture_has_table_and_ocr_queries():
    root = Path(__file__).resolve().parents[1]
    pdf_dir = root / "benchmarks" / "fixtures" / "pdf_corpus"
    manifest = json.loads(
        (root / "benchmarks" / "fixtures" / "pdf_corpus_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    base_golden = json.loads(
        (root / "benchmarks" / "fixtures" / "golden_pdf_queries.json").read_text(
            encoding="utf-8"
        )
    )
    table_golden = json.loads(
        (root / "benchmarks" / "fixtures" / "golden_pdf_table_queries.json").read_text(
            encoding="utf-8"
        )
    )
    ocr_golden = json.loads(
        (root / "benchmarks" / "fixtures" / "golden_pdf_ocr_queries.json").read_text(
            encoding="utf-8"
        )
    )
    korean_ocr_golden = json.loads(
        (
            root
            / "benchmarks"
            / "fixtures"
            / "golden_pdf_ocr_korean_queries.json"
        ).read_text(encoding="utf-8")
    )
    scanned_table_golden = json.loads(
        (
            root
            / "benchmarks"
            / "fixtures"
            / "golden_pdf_scanned_table_queries.json"
        ).read_text(encoding="utf-8")
    )
    cache_safety_golden = json.loads(
        (
            root
            / "benchmarks"
            / "fixtures"
            / "golden_pdf_cache_safety_queries.json"
        ).read_text(encoding="utf-8")
    )
    pdf_names = {path.name for path in pdf_dir.glob("*.pdf")}
    base_queries = base_golden["queries"]
    table_queries = table_golden["queries"]
    ocr_queries = ocr_golden["queries"]
    korean_ocr_queries = korean_ocr_golden["queries"]
    scanned_table_queries = scanned_table_golden["queries"]
    cache_safety_queries = cache_safety_golden["queries"]
    all_expansion_queries = [
        *table_queries,
        *ocr_queries,
        *korean_ocr_queries,
        *scanned_table_queries,
        *cache_safety_queries,
    ]
    all_contract_queries = [*base_queries, *all_expansion_queries]
    base_targets = [
        target
        for item in base_queries
        for target in item.get("relevant", [])
    ]
    table_targets = [
        target
        for item in table_queries
        for target in item.get("relevant", [])
    ]
    ocr_targets = [
        target
        for item in ocr_queries
        for target in item.get("relevant", [])
    ]
    korean_ocr_targets = [
        target
        for item in korean_ocr_queries
        for target in item.get("relevant", [])
    ]
    scanned_table_targets = [
        target
        for item in scanned_table_queries
        for target in item.get("relevant", [])
    ]
    cache_safety_targets = [
        target
        for item in cache_safety_queries
        for target in item.get("relevant", [])
    ]
    cache_negative_paths = {
        negative_path
        for item in cache_safety_queries
        for negative_path in item.get("negative_paths", [])
    }
    manifest_cases = manifest["cases"]
    manifest_case_ids = {item["case_id"] for item in manifest_cases}
    manifest_paths = {item["relative_path"] for item in manifest_cases}
    target_case_ids = {
        target["case_id"]
        for target in [
            *base_targets,
            *table_targets,
            *ocr_targets,
            *korean_ocr_targets,
            *scanned_table_targets,
            *cache_safety_targets,
        ]
    }
    target_paths = {
        target["relative_path"]
        for target in [
            *base_targets,
            *table_targets,
            *ocr_targets,
            *korean_ocr_targets,
            *scanned_table_targets,
            *cache_safety_targets,
        ]
    }
    query_ids = [item["query_id"] for item in all_expansion_queries]
    contract_query_ids = [item["query_id"] for item in all_contract_queries]
    scenario_counts = {
        scenario: sum(item["scenario"] == scenario for item in cache_safety_queries)
        for scenario in {item["scenario"] for item in cache_safety_queries}
    }

    assert manifest["schema_version"] == "pdf-corpus-manifest-v1"
    assert manifest["corpus_id"] == "pdf-ocrtable-synthetic"
    assert manifest["corpus_version"] == "2026-06-02-120"
    assert manifest["doc_count"] == 120
    assert len(manifest_cases) == 120
    assert manifest_paths == pdf_names
    assert len(manifest_case_ids) == len(manifest_cases)
    assert target_case_ids <= manifest_case_ids
    assert target_paths <= manifest_paths
    assert len(base_queries) == 13
    assert len(table_queries) == 30
    assert len(ocr_queries) == 20
    assert len(korean_ocr_queries) == 25
    assert len(scanned_table_queries) == 15
    assert len(cache_safety_queries) == 30
    assert len(all_expansion_queries) == 120
    assert len(query_ids) == len(set(query_ids))
    assert len(contract_query_ids) == len(set(contract_query_ids))
    assert len(pdf_names) == 120
    assert {target["relative_path"] for target in base_targets} <= pdf_names
    assert {target["relative_path"] for target in table_targets} <= pdf_names
    assert {target["relative_path"] for target in ocr_targets} <= pdf_names
    assert {target["relative_path"] for target in korean_ocr_targets} <= pdf_names
    assert {target["relative_path"] for target in scanned_table_targets} <= pdf_names
    assert {target["relative_path"] for target in cache_safety_targets} <= pdf_names
    assert cache_negative_paths == {
        f"distractor_notes_{index:02}.pdf" for index in range(1, 19)
    }
    assert cache_negative_paths <= manifest_paths
    assert {target["unit_type"] for target in base_targets} == {
        "document",
        "pdf_region",
        "pdf_table",
    }
    assert {target["unit_type"] for target in table_targets} == {"pdf_table"}
    assert {target["unit_type"] for target in ocr_targets} == {"pdf_ocr_text"}
    assert {target["unit_type"] for target in korean_ocr_targets} == {"pdf_ocr_text"}
    assert {target["unit_type"] for target in scanned_table_targets} == {
        "pdf_ocr_text"
    }
    assert {target["unit_type"] for target in cache_safety_targets} == {
        "pdf_ocr_text",
        "pdf_table",
    }
    assert all(target.get("table_no") == 0 for target in table_targets)
    assert all(target.get("image_no") == 0 for target in ocr_targets)
    assert all(target.get("image_no") == 0 for target in korean_ocr_targets)
    assert all(target.get("image_no") == 0 for target in scanned_table_targets)
    assert all("expected_table" in item for item in scanned_table_queries)
    assert all(
        len(item["expected_table"].get("rows", [])) >= 2
        for item in scanned_table_queries
    )
    assert all(item["corpus_id"] == manifest["corpus_id"] for item in all_contract_queries)
    assert all(
        item["corpus_version"] == manifest["corpus_version"]
        for item in all_contract_queries
    )
    assert all(
        "claim_class" in item
        and "slice_tags" in item
        and "query_set_id" in item
        for item in all_contract_queries
    )
    assert all(
        len(item["slice_tags"]) == len(set(item["slice_tags"]))
        for item in all_contract_queries
    )
    assert "golden-pdf-cache-safety-v1" in manifest["query_set_ids"]
    assert "golden-pdf-base-v1" in manifest["query_set_ids"]
    assert "golden_pdf_cache_safety_queries.json" in manifest["artifact_hashes"]
    assert _artifact_hashes_match(root, manifest["artifact_hashes"])
    assert sum(
        item["claim_class"] == "hard-negative-safety"
        for item in cache_safety_queries
    ) == 18
    assert sum(
        item["claim_class"] == "cache-lifecycle-safety"
        for item in cache_safety_queries
    ) == 12
    assert scenario_counts == {
        "hard-negative": 18,
        "warm-reuse": 2,
        "stale-content": 2,
        "corrupt-blob": 2,
        "search-source-negative": 3,
        "manifest-removed": 3,
    }
    loaded_cache_queries = runner._load_golden_queries(
        root / "benchmarks" / "fixtures" / "golden_pdf_cache_safety_queries.json"
    )
    assert loaded_cache_queries[0]["negative_paths"] == ["distractor_notes_01.pdf"]
    assert loaded_cache_queries[0]["scenario"] == "hard-negative"
    assert loaded_cache_queries[0]["claim_class"] == "hard-negative-safety"
    assert all(
        "task:cache-safety" in item["slice_tags"]
        for item in cache_safety_queries
    )
    assert all(
        not Path(item["relative_path"]).is_absolute()
        for item in manifest_cases
    )
    _assert_no_corpus_boundary_keys(
        manifest,
        base_golden,
        table_golden,
        ocr_golden,
        korean_ocr_golden,
        scanned_table_golden,
        cache_safety_golden,
    )
    assert {"noisy", "rotated", "low_contrast", "bilingual"} <= {
        tag for item in ocr_queries for tag in item.get("tags", [])
    }
    assert {
        "korean",
        "korean_noisy",
        "korean_low_contrast",
        "korean_rotated",
        "korean_bilingual",
        "korean_small",
        "scanned-table",
        "low-contrast",
        "dense-numeric",
        "small-font",
        "merged-cell",
    } <= {
        tag
        for item in [*korean_ocr_queries, *scanned_table_queries]
        for tag in item.get("tags", [])
    }


def _artifact_hashes_match(root: Path, artifact_hashes: dict[str, str]) -> bool:
    fixture_dir = root / "benchmarks" / "fixtures"
    return all(
        hashlib.sha256((fixture_dir / name).read_bytes()).hexdigest() == digest
        for name, digest in artifact_hashes.items()
    )


def _assert_no_corpus_boundary_keys(*objects: object) -> None:
    forbidden_keys = {
        "absolute_path",
        "blob_" + "rel_path",
        "cache_root",
        "private_cache_root",
        "raw_" + "payload",
        "source_path",
        "text_preview",
    }
    for item in _walk_json(objects):
        if isinstance(item, dict):
            assert forbidden_keys.isdisjoint(item)
            for value in item.values():
                if isinstance(value, str):
                    assert ("file" + "://") not in value
                    assert ":\\" not in value


def _walk_json(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list | tuple):
        for child in value:
            yield from _walk_json(child)


def test_quality_metrics_require_unit_level_match():
    item = {
        "query": "target chunk",
        "relevant": [
            {
                "relative_path": "ops.md",
                "unit_type": "chunk",
                "chunk_no": 1,
                "gain": 3,
            }
        ],
    }
    wrong_chunk = SearchResult(
        score=0.9,
        modality="text",
        relative_path="ops.md",
        page_no=None,
        snippet="wrong chunk",
        unit_type="chunk",
        chunk_no=0,
    )
    right_chunk = SearchResult(
        score=0.8,
        modality="text",
        relative_path="ops.md",
        page_no=None,
        snippet="right chunk",
        unit_type="chunk",
        chunk_no=1,
    )

    miss = runner._quality_metrics([item], [[wrong_chunk]])
    hit = runner._quality_metrics([item], [[right_chunk]])

    assert miss["recall_at_5"] == 0.0
    assert miss["mrr_at_10"] == 0.0
    assert hit["recall_at_5"] == 1.0
    assert hit["mrr_at_10"] == 1.0


def test_quality_metrics_require_table_level_match():
    item = {
        "query": "target table",
        "relevant": [
            {
                "relative_path": "report.pdf",
                "unit_type": "pdf_table",
                "table_no": 1,
                "gain": 3,
            }
        ],
    }
    wrong_table = SearchResult(
        score=0.9,
        modality="text",
        relative_path="report.pdf",
        page_no=1,
        snippet="wrong table",
        unit_type="pdf_table",
        payload={"table_no": 0},
    )
    right_table = SearchResult(
        score=0.8,
        modality="text",
        relative_path="report.pdf",
        page_no=1,
        snippet="right table",
        unit_type="pdf_table",
        payload={"table_no": 1},
    )

    miss = runner._quality_metrics([item], [[wrong_table]])
    hit = runner._quality_metrics([item], [[right_table]])

    assert miss["recall_at_5"] == 0.0
    assert hit["recall_at_5"] == 1.0


def test_quality_metrics_enforce_max_rank():
    item = {
        "query": "ranked target",
        "relevant": [
            {
                "relative_path": "target.md",
                "unit_type": "document",
                "gain": 3,
                "max_rank": 1,
            }
        ],
    }
    distractor = SearchResult(
        score=0.9,
        modality="text",
        relative_path="distractor.md",
        page_no=None,
        snippet="distractor",
        unit_type="document",
    )
    target = SearchResult(
        score=0.8,
        modality="text",
        relative_path="target.md",
        page_no=None,
        snippet="target",
        unit_type="document",
    )

    metrics = runner._quality_metrics([item], [[distractor, target]])

    assert metrics["recall_at_5"] == 0.0
    assert metrics["mrr_at_10"] == 0.0


def test_quality_metrics_keep_duplicate_query_items_separate():
    first = {
        "query": "same words",
        "relevant": [{"relative_path": "first.md", "unit_type": "document"}],
    }
    second = {
        "query": "same words",
        "relevant": [{"relative_path": "second.md", "unit_type": "document"}],
    }
    first_result = SearchResult(
        score=0.9,
        modality="text",
        relative_path="first.md",
        page_no=None,
        snippet="first",
        unit_type="document",
    )
    second_result = SearchResult(
        score=0.9,
        modality="text",
        relative_path="second.md",
        page_no=None,
        snippet="second",
        unit_type="document",
    )

    metrics = runner._quality_metrics(
        [first, second],
        [[first_result], [second_result]],
    )

    assert metrics["evaluated_queries"] == 2
    assert metrics["recall_at_1"] == 1.0


def test_quality_metrics_emit_modality_and_tag_slices():
    korean = {
        "query": "한국어",
        "modality": "text",
        "tags": ["korean"],
        "relevant": [{"relative_path": "ko.md", "unit_type": "document"}],
    }
    image = {
        "query": "red square",
        "modality": "image",
        "tags": ["image"],
        "relevant": [{"relative_path": "red.png", "unit_type": "image"}],
    }
    korean_result = SearchResult(
        score=0.9,
        modality="text",
        relative_path="ko.md",
        page_no=None,
        snippet="ko",
        unit_type="document",
    )
    image_result = SearchResult(
        score=0.9,
        modality="image",
        relative_path="red.png",
        page_no=None,
        snippet="",
        unit_type="image",
    )

    metrics = runner._quality_metrics(
        [korean, image],
        [[korean_result], [image_result]],
    )

    assert metrics["quality_slices"]["tag:korean"]["evaluated_queries"] == 1
    assert metrics["quality_slices"]["tag:image"]["recall_at_1"] == 1.0
    assert metrics["quality_slices"]["modality:text"]["hit_at_1"] == 1.0


def test_write_report_scans_before_writing_sensitive_output(tmp_path: Path):
    leaked_profile = "OPENAI_" + "API_KEY=sk-" + "abcdef123456"
    report = BenchmarkReport(
        files=0,
        units=0,
        indexing_seconds=0.0,
        files_per_second=0.0,
        units_per_second=0.0,
        search_latency_ms={"p50": 0.0, "p95": 0.0, "p99": 0.0},
        collection_name=leaked_profile,
        text_embedding_profile="hash:64",
        vision_embedding_profile="hash:64",
        text_dimension=64,
        vision_dimension=64,
        evaluated_queries=0,
        recall_at_5=None,
        recall_at_10=None,
        mrr_at_10=None,
        stale_vector_count=0,
        duplicate_vector_count=0,
        qdrant_disk_bytes=0,
        sync=SyncReport(),
    )
    path = tmp_path / "benchmark.json"

    with pytest.raises(ValueError, match="artifact scan failed"):
        write_report(report, path)

    assert not path.exists()


def test_write_report_accepts_external_blocked_terms(tmp_path: Path):
    report = BenchmarkReport(
        files=0,
        units=0,
        indexing_seconds=0.0,
        files_per_second=0.0,
        units_per_second=0.0,
        search_latency_ms={"p50": 0.0, "p95": 0.0, "p99": 0.0},
        collection_name="release-marker",
        text_embedding_profile="hash:64",
        vision_embedding_profile="hash:64",
        text_dimension=64,
        vision_dimension=64,
        evaluated_queries=0,
        recall_at_5=None,
        recall_at_10=None,
        mrr_at_10=None,
        stale_vector_count=0,
        duplicate_vector_count=0,
        qdrant_disk_bytes=0,
        sync=SyncReport(),
    )
    path = tmp_path / "benchmark.json"

    with pytest.raises(ValueError, match="blocked expression"):
        write_report(report, path, banned_terms=["release-marker"])

    assert not path.exists()


def test_run_benchmark_closes_store_when_cleanup_fails(monkeypatch, tmp_path: Path):
    closed = []

    class FakeStore:
        collection_name = "fake"

        def __init__(self, settings):
            pass

        def drop_collection(self):
            raise RuntimeError("cleanup failed")

        def close(self):
            closed.append(True)

    class FakeSyncService:
        def __init__(self, settings, store, manifest):
            pass

        def sync_folder(self, folder):
            raise RuntimeError("sync failed")

    monkeypatch.setattr(runner, "QdrantStore", FakeStore)
    monkeypatch.setattr(runner, "SyncService", FakeSyncService)

    with pytest.raises(RuntimeError, match="sync failed"):
        runner._run_benchmark_isolated(
            tmp_path,
            queries=[],
            settings=Settings(data_dir=tmp_path / "data"),
            drop_collection=True,
        )

    assert closed == [True]


def test_run_benchmark_raises_cleanup_error_after_success(monkeypatch, tmp_path: Path):
    closed = []

    class FakeStore:
        collection_name = "fake"

        def __init__(self, settings):
            pass

        def count(self):
            return 0

        def payload_records(self):
            return []

        def drop_collection(self):
            raise RuntimeError("cleanup failed")

        def close(self):
            closed.append(True)

    class FakeSyncService:
        def __init__(self, settings, store, manifest):
            self.settings = settings

        def sync_folder(self, folder):
            return SyncReport(added=1, units=0)

    class FakeSearchService:
        def __init__(self, settings, store, manifest):
            pass

        def search(self, query, top_k=10, modality=None):
            return []

    monkeypatch.setattr(runner, "QdrantStore", FakeStore)
    monkeypatch.setattr(runner, "SyncService", FakeSyncService)
    monkeypatch.setattr(runner, "SearchService", FakeSearchService)

    with pytest.raises(RuntimeError, match="cleanup failed"):
        runner._run_benchmark_isolated(
            tmp_path,
            queries=[],
            settings=Settings(data_dir=tmp_path / "data"),
            drop_collection=True,
        )

    assert closed == [True]
