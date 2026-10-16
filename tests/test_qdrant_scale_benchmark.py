from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks import qdrant_scale_benchmark as scale
from locallens.core.config import Settings


def test_qdrant_scale_benchmark_builds_local_server_summaries(
    monkeypatch,
    tmp_path: Path,
):
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
        calls.append((Path(folder).name, server_url, list(queries), golden_path))
        multiplier = 2.0 if server_url else 1.0
        return {
            "server_target": "http://localhost" if server_url else "local-path",
            "files": 3,
            "units": 6,
            "indexing_seconds": multiplier,
            "sync": {"failed": 0},
            "evaluated_queries": 2,
            "cold_pass": {
                "search_latency_ms": {
                    "p50": 10.0 * multiplier,
                    "p95": 20.0 * multiplier,
                    "p99": 30.0 * multiplier,
                },
                "quality": {"recall_at_5": 1.0},
            },
            "warm_aggregate": {
                "search_latency_ms": {
                    "p50": {"p50": 8.0 * multiplier},
                    "p95": {"p50": 16.0 * multiplier},
                    "p99": {"p50": 24.0 * multiplier},
                }
            },
        }

    monkeypatch.setattr(scale, "run_warm_query_benchmark", fake_run)

    report = scale.run_qdrant_scale_benchmark(
        settings=Settings(data_dir=tmp_path / "data"),
        sizes=[3],
        queries_per_size=2,
        server_url="http://127.0.0.1:6333",
        runs=2,
        warmup_runs=1,
    )

    assert calls == [
        (
            "corpus_3",
            None,
            ["llscale-00000-target", "llscale-00002-target"],
            None,
        ),
        (
            "corpus_3",
            "http://127.0.0.1:6333",
            ["llscale-00000-target", "llscale-00002-target"],
            None,
        ),
    ]
    assert report["benchmark_mode"] == "qdrant-scale-warm-query"
    assert report["profile"] == "hash-smoke"
    assert report["server_target"] == "http://localhost"
    assert report["results"][0]["files"] == 3
    assert report["results"][0]["queries"] == 2
    assert report["results"][0]["local"]["measured_queries"] == 2
    assert report["results"][0]["local"]["quality_scope"] == "not-evaluated"
    assert report["results"][0]["delta"]["warm_p50_ms"] == 8.0
    assert "127.0.0.1" not in str(report)


def test_qdrant_scale_benchmark_rejects_non_loopback_url(tmp_path: Path):
    with pytest.raises(ValueError, match="loopback"):
        scale.run_qdrant_scale_benchmark(
            settings=Settings(data_dir=tmp_path / "data"),
            sizes=[1],
            queries_per_size=1,
            server_url="https://qdrant.example.test",
            runs=1,
            warmup_runs=0,
        )


def test_qdrant_scale_benchmark_cli_rejects_non_loopback_url(capsys):
    exit_code = scale.main(
        [
            "--sizes",
            "1",
            "--server-url",
            "https://qdrant.example.test",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 2
    assert "loopback" in output
    assert "qdrant.example.test" not in output
