from __future__ import annotations

from pathlib import Path

import pytest

from locallens.core.types import BenchmarkReport, SyncReport
import locallens.app.cli as cli
from locallens.app.cli import main


pytest.importorskip("qdrant_client")


def test_cli_index_and_search(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALLENS_DATA_DIR", str(tmp_path / "data"))
    source = tmp_path / "docs"
    source.mkdir()
    (source / "a.txt").write_text("local semantic search")

    assert main(["index", str(source)]) == 0
    assert main(["search", "semantic"]) == 0

    output = capsys.readouterr().out
    assert "a.txt" in output


def test_cli_search_passes_path_prefix(tmp_path: Path, monkeypatch, capsys):
    calls = []

    class FakeStore:
        def close(self):
            calls.append(("close",))

    class FakeSearchService:
        def __init__(self, settings):
            self.store = FakeStore()

        def search(
            self,
            query,
            top_k=10,
            modality=None,
            ext=None,
            path_prefix=None,
        ):
            calls.append(
                {
                    "query": query,
                    "top_k": top_k,
                    "modality": modality,
                    "ext": ext,
                    "path_prefix": path_prefix,
                }
            )
            return []

    monkeypatch.setattr(cli, "SearchService", FakeSearchService)

    assert main(["search", "target", "--path-prefix", "team"]) == 0

    assert calls[0]["path_prefix"] == "team"
    assert calls[-1] == ("close",)
    assert capsys.readouterr().out.rstrip() == "[]"


def test_cli_search_reports_invalid_top_k(monkeypatch, capsys):
    class FakeStore:
        def close(self):
            pass

    class FakeSearchService:
        def __init__(self, settings):
            self.store = FakeStore()

        def search(self, *args, **kwargs):
            raise ValueError("Top K must be a positive integer.")

    monkeypatch.setattr(cli, "SearchService", FakeSearchService)

    assert main(["search", "target", "--top-k", "0"]) == 2

    output = capsys.readouterr().out
    assert "Top K must be a positive integer." in output


def test_cli_benchmark_and_purge_release_qdrant_lock(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALLENS_DATA_DIR", str(tmp_path / "data"))
    source = tmp_path / "docs"
    source.mkdir()
    (source / "b.txt").write_text("benchmark semantic search")
    report_path = tmp_path / "benchmark.json"

    assert main(["benchmark", str(source), "--out", str(report_path)]) == 0
    assert report_path.exists()
    assert main(["purge"]) == 0
    assert main(["search", "semantic"]) == 0
    assert capsys.readouterr().out.rstrip().endswith("[]")


def test_cli_purge_removes_default_benchmark_artifact(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("LOCALLENS_DATA_DIR", str(data_dir))
    source = tmp_path / "docs"
    source.mkdir()
    (source / "c.txt").write_text("benchmark cleanup search")
    default_report = data_dir / "benchmark.json"

    assert main(["benchmark", str(source)]) == 0
    assert default_report.exists()
    assert main(["purge"]) == 0

    assert not default_report.exists()


def test_cli_purge_does_not_remove_unrelated_data_dir_files(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    keep = data_dir / "keep.txt"
    keep.write_text("unrelated")
    monkeypatch.setenv("LOCALLENS_DATA_DIR", str(data_dir))

    assert main(["purge"]) == 0

    assert keep.exists()


def test_cli_scan_previews_included_and_excluded_files(tmp_path: Path, capsys):
    source = tmp_path / "docs"
    source.mkdir()
    (source / "note.md").write_text("scan target")
    (source / ".env").write_text("TOKEN=value")

    exit_code = main(["scan", str(source)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"included": 1' in output
    assert '"excluded": 1' in output
    assert '"relative_path": "note.md"' in output
    assert '"relative_path": ".env"' in output
    assert "root_path" not in output


def test_cli_benchmark_applies_blocked_term_gate(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALLENS_DATA_DIR", str(tmp_path / "data"))
    source = tmp_path / "docs"
    source.mkdir()
    (source / "d.txt").write_text("benchmark semantic search")
    report_path = tmp_path / "benchmark.json"

    exit_code = main(
        [
            "benchmark",
            str(source),
            "--out",
            str(report_path),
            "--blocked-term",
            "locallens_units",
        ]
    )

    assert exit_code == 1
    assert not report_path.exists()
    assert "blocked expression" in capsys.readouterr().out


def test_cli_benchmark_fails_when_sync_report_has_failures(
    tmp_path: Path, monkeypatch, capsys
):
    def fake_run_benchmark(folder, queries, settings, golden_path=None):
        return BenchmarkReport(
            files=1,
            units=0,
            indexing_seconds=0.0,
            files_per_second=0.0,
            units_per_second=0.0,
            search_latency_ms={"p50": 0.0, "p95": 0.0, "p99": 0.0},
            collection_name="locallens_units",
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
            sync=SyncReport(failed=1),
        )

    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)
    source = tmp_path / "docs"
    source.mkdir()
    report_path = tmp_path / "benchmark.json"

    exit_code = main(["benchmark", str(source), "--out", str(report_path)])

    assert exit_code == 1
    assert not report_path.exists()
    assert "failed during indexing" in capsys.readouterr().out


def test_cli_scan_artifacts_reports_findings(tmp_path: Path, capsys):
    artifact = tmp_path / "release.md"
    artifact.write_text("release marker", encoding="utf-8")
    terms = tmp_path / "terms.txt"
    terms.write_text("release marker", encoding="utf-8")

    exit_code = main(
        [
            "scan-artifacts",
            str(artifact),
            "--blocked-terms-file",
            str(terms),
        ]
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert '"scanned": 1' in output
    assert "blocked expression" in output
    assert "release marker" not in output


def test_cli_scan_artifacts_sanitizes_absolute_finding_paths(tmp_path: Path, capsys):
    artifact = tmp_path / "release.md"
    artifact.write_text("release marker", encoding="utf-8")
    terms = tmp_path / "terms.txt"
    terms.write_text("release marker", encoding="utf-8")

    exit_code = main(
        [
            "scan-artifacts",
            str(artifact.resolve()),
            "--blocked-terms-file",
            str(terms.resolve()),
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 1
    assert "blocked expression" in output
    assert str(tmp_path) not in output
    assert "<external>/release.md" in output


def test_cli_scan_artifacts_masks_blocked_path_names(tmp_path: Path, capsys):
    blocked_name = "release-checkpoint-marker.md"
    artifact = tmp_path / blocked_name
    artifact.write_text("clean body", encoding="utf-8")

    exit_code = main(
        [
            "scan-artifacts",
            str(artifact),
            "--blocked-term",
            "checkpoint marker",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 1
    assert "blocked expression" in output
    assert "checkpoint" not in output
    assert "<blocked-path>" in output


def test_cli_scan_artifacts_passes_clean_files(tmp_path: Path, capsys):
    artifact = tmp_path / "release.md"
    artifact.write_text("clean public notes", encoding="utf-8")

    exit_code = main(["scan-artifacts", str(artifact)])

    assert exit_code == 0
    assert '"findings": []' in capsys.readouterr().out


def test_cli_scan_artifacts_reads_manifest(tmp_path: Path, capsys):
    artifact = tmp_path / "release.md"
    artifact.write_text("clean release notes", encoding="utf-8")
    manifest = tmp_path / "release_artifacts.txt"
    manifest.write_text("# release artifacts\nrelease.md\n", encoding="utf-8")

    exit_code = main(["scan-artifacts", "--manifest", str(manifest)])

    assert exit_code == 0
    assert '"scanned": 1' in capsys.readouterr().out


def test_cli_scan_artifacts_fails_closed_for_absolute_manifest_entry(
    tmp_path: Path, capsys
):
    manifest = tmp_path / "release_artifacts.txt"
    unsafe_entry = "C:" + "/" + "Users/example/private.md"
    manifest.write_text(f"{unsafe_entry}\n", encoding="utf-8")

    exit_code = main(["scan-artifacts", "--manifest", str(manifest)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "unsafe path" in output
    assert "private.md" not in output
    assert unsafe_entry not in output


def test_cli_scan_artifacts_fails_closed_for_repo_escape_manifest_entry(
    tmp_path: Path, capsys
):
    manifest = tmp_path / "release_artifacts.txt"
    manifest.write_text("../private.md\n", encoding="utf-8")

    exit_code = main(["scan-artifacts", "--manifest", str(manifest)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "repo escape" in output
    assert "../private.md" not in output


def test_cli_scan_artifacts_reads_multiple_manifests(tmp_path: Path, capsys):
    first = tmp_path / "publication.md"
    second = tmp_path / "hygiene.md"
    first.write_text("clean publication notes", encoding="utf-8")
    second.write_text("clean repository notes", encoding="utf-8")
    first_manifest = tmp_path / "publication_artifacts.txt"
    second_manifest = tmp_path / "repo_hygiene_artifacts.txt"
    terms = tmp_path / "terms.txt"
    first_manifest.write_text("publication.md\n", encoding="utf-8")
    second_manifest.write_text("hygiene.md\n", encoding="utf-8")
    terms.write_text("absent publication marker\n", encoding="utf-8")

    exit_code = main(
        [
            "scan-artifacts",
            "--manifest",
            str(first_manifest),
            "--manifest",
            str(second_manifest),
            "--blocked-terms-file",
            str(terms),
        ]
    )

    assert exit_code == 0
    assert '"scanned": 2' in capsys.readouterr().out


def test_cli_scan_artifacts_fails_closed_for_publication_manifest_without_terms(
    tmp_path: Path, capsys
):
    artifact = tmp_path / "publication.md"
    manifest = tmp_path / "publication_artifacts.txt"
    artifact.write_text("clean publication notes", encoding="utf-8")
    manifest.write_text("publication.md\n", encoding="utf-8")

    exit_code = main(["scan-artifacts", "--manifest", str(manifest)])

    assert exit_code == 2
    output = capsys.readouterr().out
    assert "publication scan requires" in output
    assert "publication.md" not in output


def test_cli_scan_artifacts_fails_closed_for_publication_manifest_with_empty_terms(
    tmp_path: Path, capsys
):
    artifact = tmp_path / "publication.md"
    manifest = tmp_path / "publication_artifacts.txt"
    terms = tmp_path / "terms.txt"
    artifact.write_text("clean publication notes", encoding="utf-8")
    manifest.write_text("publication.md\n", encoding="utf-8")
    terms.write_text("\n# inactive only\n", encoding="utf-8")

    exit_code = main(
        [
            "scan-artifacts",
            "--manifest",
            str(manifest),
            "--blocked-terms-file",
            str(terms),
        ]
    )

    assert exit_code == 2
    assert "at least one active term" in capsys.readouterr().out


def test_cli_scan_artifacts_fails_closed_for_generated_evidence_manifest(
    tmp_path: Path, capsys
):
    artifact = tmp_path / "report.json"
    manifest = tmp_path / "generated_evidence_artifacts.txt"
    artifact.write_text('{"status": "ok"}', encoding="utf-8")
    manifest.write_text("report.json\n", encoding="utf-8")

    exit_code = main(["scan-artifacts", "--manifest", str(manifest)])

    assert exit_code == 2
    assert "publication scan requires" in capsys.readouterr().out


def test_cli_scan_artifacts_publication_mode_requires_active_terms(
    tmp_path: Path, capsys
):
    artifact = tmp_path / "release.md"
    artifact.write_text("clean release notes", encoding="utf-8")

    exit_code = main(["scan-artifacts", str(artifact), "--publication-scan"])

    assert exit_code == 2
    assert "publication scan requires" in capsys.readouterr().out


def test_cli_scan_artifacts_requires_paths_or_manifest(capsys):
    exit_code = main(["scan-artifacts"])

    assert exit_code == 2
    assert "artifact paths or --manifest are required" in capsys.readouterr().out


def test_cli_release_gate_writes_report(tmp_path: Path, monkeypatch, capsys):
    output = tmp_path / "release_gate.json"
    captured = {}

    def fake_run_release_gate(**kwargs):
        captured.update(kwargs)
        return {"status": "passed", "steps": []}

    monkeypatch.setattr("locallens.app.cli.run_release_gate", fake_run_release_gate)

    exit_code = main(
        [
            "release-gate",
            "--blocked-terms-file",
            str(tmp_path / "terms.txt"),
            "--root",
            str(tmp_path),
            "--out",
            str(output),
            "--python",
            "python",
        ]
    )

    assert exit_code == 0
    assert captured["root"] == tmp_path
    assert captured["python_executable"] == "python"
    assert '"status": "passed"' in capsys.readouterr().out
    assert '"status": "passed"' in output.read_text(encoding="utf-8")


def test_cli_compare_stores_writes_delta_report(tmp_path: Path, monkeypatch, capsys):
    reports = []

    def fake_run_benchmark(folder, queries, settings, golden_path=None, drop_collection=False):
        report = BenchmarkReport(
            files=1,
            units=2,
            indexing_seconds=1.0 + len(reports),
            files_per_second=1.0,
            units_per_second=2.0,
            search_latency_ms={"p50": 3.0 + len(reports), "p95": 4.0, "p99": 5.0},
            collection_name=settings.collection_name,
            text_embedding_profile="hash:64",
            vision_embedding_profile="hash:64",
            text_dimension=64,
            vision_dimension=64,
            evaluated_queries=1,
            recall_at_5=1.0,
            recall_at_10=1.0,
            mrr_at_10=1.0,
            stale_vector_count=0,
            duplicate_vector_count=0,
            qdrant_disk_bytes=0,
            sync=SyncReport(added=1, units=2),
        )
        reports.append((settings.qdrant_url, drop_collection))
        return report

    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)
    source = tmp_path / "docs"
    source.mkdir()
    out = tmp_path / "compare.json"

    exit_code = main(
        [
            "compare-stores",
            str(source),
            "--server-url",
            "http://localhost:6333",
            "--out",
            str(out),
        ]
    )

    assert exit_code == 0
    assert reports == [(None, True), ("http://localhost:6333", True)]
    assert out.exists()
    assert '"search_p50_ms": 1.0' in out.read_text(encoding="utf-8")
    assert "http://localhost:6333" not in out.read_text(encoding="utf-8")
    assert "server" in capsys.readouterr().out


def test_cli_compare_stores_repeated_runs_write_aggregate(
    tmp_path: Path, monkeypatch, capsys
):
    reports = []

    def fake_run_benchmark(folder, queries, settings, golden_path=None, drop_collection=False):
        report = BenchmarkReport(
            files=1,
            units=2,
            indexing_seconds=1.0 + len(reports),
            files_per_second=1.0,
            units_per_second=2.0,
            search_latency_ms={
                "p50": 3.0 + len(reports),
                "p95": 4.0 + len(reports),
                "p99": 5.0 + len(reports),
            },
            collection_name=settings.collection_name,
            text_embedding_profile="hash:64",
            vision_embedding_profile="hash:64",
            text_dimension=64,
            vision_dimension=64,
            evaluated_queries=1,
            recall_at_5=1.0,
            recall_at_10=1.0,
            mrr_at_10=1.0,
            stale_vector_count=0,
            duplicate_vector_count=0,
            qdrant_disk_bytes=0,
            sync=SyncReport(added=1, units=2),
        )
        reports.append((settings.qdrant_url, drop_collection))
        return report

    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)
    source = tmp_path / "docs"
    source.mkdir()
    out = tmp_path / "compare-repeated.json"

    exit_code = main(
        [
            "compare-stores",
            str(source),
            "--server-url",
            "http://localhost:6333",
            "--runs",
            "2",
            "--warmup-runs",
            "1",
            "--out",
            str(out),
        ]
    )

    assert exit_code == 0
    assert len(reports) == 6
    assert reports[0] == (None, True)
    assert reports[1] == ("http://localhost:6333", True)
    content = out.read_text(encoding="utf-8")
    assert '"runs": 2' in content
    assert '"warmup_runs": 1' in content
    assert '"aggregate"' in content
    assert '"measurements"' in capsys.readouterr().out


def test_cli_compare_stores_rejects_invalid_run_counts(tmp_path: Path, capsys):
    source = tmp_path / "docs"
    source.mkdir()

    exit_code = main(
        [
            "compare-stores",
            str(source),
            "--server-url",
            "http://localhost:6333",
            "--runs",
            "0",
        ]
    )

    assert exit_code == 2
    assert "--runs must be >= 1" in capsys.readouterr().out


def test_cli_compare_stores_fails_when_local_sync_has_failures(
    tmp_path: Path, monkeypatch, capsys
):
    calls = []

    def fake_run_benchmark(folder, queries, settings, golden_path=None, drop_collection=False):
        calls.append(settings.qdrant_url)
        return BenchmarkReport(
            files=1,
            units=0,
            indexing_seconds=0.0,
            files_per_second=0.0,
            units_per_second=0.0,
            search_latency_ms={"p50": 0.0, "p95": 0.0, "p99": 0.0},
            collection_name=settings.collection_name,
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
            sync=SyncReport(failed=1),
        )

    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)
    source = tmp_path / "docs"
    source.mkdir()
    out = tmp_path / "compare.json"

    exit_code = main(
        [
            "compare-stores",
            str(source),
            "--server-url",
            "http://localhost:6333",
            "--out",
            str(out),
        ]
    )

    assert exit_code == 1
    assert calls == [None]
    assert not out.exists()
    assert "failed during indexing" in capsys.readouterr().out


def test_cli_compare_stores_reports_server_connection_error(
    tmp_path: Path, monkeypatch, capsys
):
    calls = []

    def fake_run_benchmark(folder, queries, settings, golden_path=None, drop_collection=False):
        calls.append(settings.qdrant_url)
        if settings.qdrant_url:
            raise OSError("[WinError 10061] connection refused")
        return BenchmarkReport(
            files=1,
            units=2,
            indexing_seconds=1.0,
            files_per_second=1.0,
            units_per_second=2.0,
            search_latency_ms={"p50": 3.0, "p95": 4.0, "p99": 5.0},
            collection_name=settings.collection_name,
            text_embedding_profile="hash:64",
            vision_embedding_profile="hash:64",
            text_dimension=64,
            vision_dimension=64,
            evaluated_queries=1,
            recall_at_5=1.0,
            recall_at_10=1.0,
            mrr_at_10=1.0,
            stale_vector_count=0,
            duplicate_vector_count=0,
            qdrant_disk_bytes=0,
            sync=SyncReport(added=1, units=2),
        )

    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)
    source = tmp_path / "docs"
    source.mkdir()
    out = tmp_path / "compare.json"

    exit_code = main(
        [
            "compare-stores",
            str(source),
            "--server-url",
            "http://localhost:6333",
            "--out",
            str(out),
        ]
    )

    assert exit_code == 1
    assert calls == [None, "http://localhost:6333"]
    assert not out.exists()
    assert "WinError 10061" in capsys.readouterr().out


def test_cli_compare_stores_rejects_non_loopback_server_url(tmp_path: Path, capsys):
    source = tmp_path / "docs"
    source.mkdir()

    exit_code = main(
        [
            "compare-stores",
            str(source),
            "--server-url",
            "https://qdrant.example.test",
        ]
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "loopback" in output
    assert "qdrant.example.test" not in output
