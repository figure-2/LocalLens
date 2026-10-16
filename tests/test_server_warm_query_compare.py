from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks import server_warm_query_compare as compare
from locallens.core.config import Settings


def test_server_warm_query_compare_builds_sanitized_delta(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run(
        folder,
        settings,
        queries,
        golden_path,
        server_url,
        runs,
        warmup_runs,
        allow_remote_server=False,
    ):
        calls.append(server_url)
        scale = 2.0 if server_url else 1.0
        return {
            "benchmark_mode": "warm-query",
            "indexed_once": True,
            "reused_collection": True,
            "server_target": "http://localhost" if server_url else "local-path",
            "collection_name": "fixture",
            "fixture": "corpus",
            "golden": "golden.json",
            "files": 1,
            "units": 2,
            "indexing_seconds": 1.0 * scale,
            "sync": {"failed": 0},
            "evaluated_queries": 1,
            "cold_pass": {
                "search_latency_ms": {"p50": 10.0 * scale, "p95": 20.0 * scale, "p99": 30.0 * scale},
                "quality": {"recall_at_10": 1.0},
            },
            "warmup_runs": warmup_runs,
            "runs": runs,
            "warm_passes": [],
            "warm_aggregate": {
                "search_latency_ms": {
                    "p50": {"p50": 8.0 * scale, "p95": 9.0 * scale, "p99": 10.0 * scale},
                    "p95": {"p50": 16.0 * scale, "p95": 17.0 * scale, "p99": 18.0 * scale},
                    "p99": {"p50": 24.0 * scale, "p95": 25.0 * scale, "p99": 26.0 * scale},
                }
            },
        }

    monkeypatch.setattr(compare, "run_warm_query_benchmark", fake_run)

    report = compare.run_server_warm_query_compare(
        folder=tmp_path / "corpus",
        settings=Settings(data_dir=tmp_path / "data"),
        golden_path=tmp_path / "golden.json",
        server_url="http://127.0.0.1:6333",
        runs=3,
        warmup_runs=1,
    )

    assert calls == [None, "http://127.0.0.1:6333"]
    assert report["benchmark_mode"] == "local-server-warm-query-compare"
    assert report["server_target"] == "http://localhost"
    assert report["runs"] == 3
    assert report["warmup_runs"] == 1
    assert report["delta"]["indexing_seconds"] == 1.0
    assert report["delta"]["cold_p50_ms"] == 10.0
    assert report["delta"]["warm_p50_ms"] == 8.0
    assert "127.0.0.1" not in str(report)


def test_server_warm_query_compare_rejects_non_loopback_url(tmp_path: Path):
    with pytest.raises(ValueError, match="loopback"):
        compare.run_server_warm_query_compare(
            folder=tmp_path / "corpus",
            settings=Settings(data_dir=tmp_path / "data"),
            golden_path=None,
            server_url="https://qdrant.example.test",
            runs=1,
            warmup_runs=0,
        )


def test_server_warm_query_compare_cli_rejects_non_loopback_url(
    tmp_path: Path, capsys
):
    source = tmp_path / "corpus"
    source.mkdir()

    exit_code = compare.main(
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
