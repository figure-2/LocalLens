from __future__ import annotations

from benchmarks.path_prefix_benchmark import run_path_prefix_benchmark


def test_path_prefix_benchmark_keeps_results_in_scope():
    report = run_path_prefix_benchmark(files=30, target_files=5, queries=2, runs=1)

    assert report["files"] == 30
    assert report["scoped_files"] == 5
    assert report["runs"] == 1
    assert report["measurements"][0]["sync"]["failed"] == 0
    assert report["measurements"][0]["matching_paths_count"] == 5
    assert report["aggregate"]["prefix_all_results_in_scope"] is True
    assert report["aggregate"]["prefix_search_p50_ms"]["p50"] >= 0
