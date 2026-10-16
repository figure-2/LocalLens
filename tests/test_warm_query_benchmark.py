from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.warm_query_benchmark import (
    _server_target_label,
    main,
    run_warm_query_benchmark,
)
from locallens.core.config import Settings


pytest.importorskip("qdrant_client")


def test_warm_query_benchmark_indexes_once_and_reuses_collection(tmp_path: Path):
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "notes.md").write_text("warm query benchmark target", encoding="utf-8")
    golden = tmp_path / "golden.json"
    golden.write_text(
        """
        {
          "queries": [
            {
              "query": "warm query benchmark target",
              "relevant": [
                {"relative_path": "notes.md", "unit_type": "document"}
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    report = run_warm_query_benchmark(
        folder=source,
        settings=Settings(data_dir=tmp_path / "data"),
        queries=[],
        golden_path=golden,
        server_url=None,
        runs=2,
        warmup_runs=1,
    )

    assert report["benchmark_mode"] == "warm-query"
    assert report["indexed_once"] is True
    assert report["reused_collection"] is True
    assert report["server_target"] == "local-path"
    assert report["files"] == 1
    assert report["units"] >= 1
    assert report["sync"]["failed"] == 0
    assert report["evaluated_queries"] == 1
    assert report["cold_pass"]["quality"]["recall_at_5"] == 1.0
    assert report["warmup_runs"] == 1
    assert report["runs"] == 2
    assert len(report["warm_passes"]) == 2
    assert report["warm_aggregate"]["search_latency_ms"]["p50"]["p50"] >= 0.0


def test_warm_query_benchmark_sanitizes_server_target_label():
    assert _server_target_label(None) == "local-path"
    assert _server_target_label("http://127.0.0.1:6333") == "http://localhost"
    assert _server_target_label("http://example.invalid:6333") == "http://remote"


def test_warm_query_benchmark_rejects_non_loopback_server_url(tmp_path: Path, capsys):
    source = tmp_path / "corpus"
    source.mkdir()

    exit_code = main(
        [
            str(source),
            "--server-url",
            "https://qdrant.example.test",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 2
    assert "loopback" in output
    assert "qdrant.example.test" not in output


def test_warm_query_benchmark_function_rejects_non_loopback_server_url(tmp_path: Path):
    source = tmp_path / "corpus"
    source.mkdir()

    with pytest.raises(ValueError, match="loopback"):
        run_warm_query_benchmark(
            folder=source,
            settings=Settings(data_dir=tmp_path / "data"),
            queries=[],
            golden_path=None,
            server_url="https://qdrant.example.test",
            runs=1,
            warmup_runs=0,
        )
