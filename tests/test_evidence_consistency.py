from __future__ import annotations

import json
from pathlib import Path

from locallens.security.evidence_consistency import check_evidence_consistency


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_evidence_consistency_passes_for_current_claims(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text("README.md\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("current report summary", encoding="utf-8")
    _write_json(tmp_path / ".locallens" / "current.json", {"metric": {"value": 0.9}})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [".locallens/old.json"],
            "checks": [
                {
                    "id": "metric",
                    "artifact": ".locallens/current.json",
                    "path": "metric.value",
                    "minimum": 0.8,
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "passed"
    assert report["findings"] == []
    assert report["checked_public_table_assertions"] == 0


def test_evidence_consistency_fails_closed_for_absolute_generated_manifest_entry(
    tmp_path: Path,
):
    unsafe_entry = "C:" + "/" + "Users/example/private.json"
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        f"{unsafe_entry}\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text("README.md\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("summary", encoding="utf-8")
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [],
            "historical_artifacts": [],
            "checks": [],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "unsafe artifact manifest entry"
    assert report["findings"][0]["check_id"] == "generated-manifest"
    assert unsafe_entry not in json.dumps(report)


def test_evidence_consistency_fails_closed_for_publication_manifest_repo_escape(
    tmp_path: Path,
):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "../private.md\n", encoding="utf-8"
    )
    _write_json(tmp_path / ".locallens" / "current.json", {"metric": 1})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [".locallens/old.json"],
            "checks": [],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "unsafe artifact manifest entry"
    assert report["findings"][0]["check_id"] == "publication-manifest"
    assert "../private.md" not in json.dumps(report)


def test_evidence_consistency_fails_when_historical_artifact_is_current(
    tmp_path: Path,
):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/old.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text("README.md\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("summary", encoding="utf-8")
    _write_json(tmp_path / ".locallens" / "old.json", {"metric": 1})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [],
            "historical_artifacts": [".locallens/old.json"],
            "checks": [],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "historical artifact listed as current evidence"


def test_evidence_consistency_fails_on_metric_mismatch(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text("README.md\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("summary", encoding="utf-8")
    _write_json(tmp_path / ".locallens" / "current.json", {"metric": 0.5})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [
                {
                    "id": "metric-minimum",
                    "artifact": ".locallens/current.json",
                    "path": "metric",
                    "minimum": 0.8,
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "claim value below minimum"


def test_evidence_consistency_fails_on_public_historical_reference(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text("README.md\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "Do not use .locallens/old.json for a current claim.", encoding="utf-8"
    )
    _write_json(tmp_path / ".locallens" / "current.json", {"metric": 1})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [".locallens/old.json"],
            "checks": [],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == (
        "historical artifact referenced by publication surface"
    )


def test_evidence_consistency_supports_list_selector(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text("README.md\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("summary", encoding="utf-8")
    _write_json(
        tmp_path / ".locallens" / "current.json",
        {"models": [{"model": "selected", "metrics": {"top1": 0.95}}]},
    )
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [
                {
                    "id": "selected-top1",
                    "artifact": ".locallens/current.json",
                    "path": "models[model=selected].metrics.top1",
                    "approx_equals": 0.95,
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "passed"
    assert report["checked_public_table_assertions"] == 0


def test_evidence_consistency_fails_when_public_text_drifts(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/release.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "release.md").write_text(
        "current recall@5 0.800", encoding="utf-8"
    )
    _write_json(tmp_path / ".locallens" / "current.json", {"recall_at_5": 0.941176})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [
                {
                    "id": "recall-public-text",
                    "artifact": ".locallens/current.json",
                    "path": "recall_at_5",
                    "approx_equals": 0.941176,
                    "public_text": [
                        {
                            "artifact": "docs/release.md",
                            "template": "current recall@5 {value}",
                            "value_format": ".3f",
                        }
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "public claim text mismatch"


def test_evidence_consistency_passes_public_table_assertion(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/benchmark.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "\n".join(
            [
                "| Area | Current Status | Decision |",
                "| --- | --- | --- |",
                "| Vision image retrieval | top1 0.970, recall@5 0.995 | Promote |",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(tmp_path / ".locallens" / "current.json", {"top1": 0.97})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [
                {
                    "id": "vision-table-top1",
                    "artifact": ".locallens/current.json",
                    "path": "top1",
                    "approx_equals": 0.97,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "row_key": "Vision image retrieval",
                            "column": "Current Status",
                            "template": "top1 {value}",
                            "value_format": ".3f",
                        }
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "passed"
    assert report["checked_public_table_assertions"] == 1


def test_evidence_consistency_checks_public_metric_table_coverage(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/benchmark.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "\n".join(
            [
                "| Model | Top1 | Recall@5 | MRR@10 |",
                "| --- | ---: | ---: | ---: |",
                "| `selected` | 0.970 | 0.995 | 0.983 |",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(
        tmp_path / ".locallens" / "current.json",
        {"models": [{"model": "selected", "top1": 0.97, "recall": 0.995, "mrr": 0.983}]},
    )
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "public_metric_table_coverage": [
                {
                    "artifact": "docs/benchmark.md",
                    "required_headers": ["Model", "Top1", "Recall@5", "MRR@10"],
                    "columns": ["Top1", "Recall@5", "MRR@10"],
                }
            ],
            "checks": [
                {
                    "id": "top1",
                    "artifact": ".locallens/current.json",
                    "path": "models[model=selected].top1",
                    "approx_equals": 0.97,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "row_key": "selected",
                            "column": "Top1",
                            "template": "{value}",
                            "value_format": ".3f",
                            "exact": True,
                        }
                    ],
                },
                {
                    "id": "recall",
                    "artifact": ".locallens/current.json",
                    "path": "models[model=selected].recall",
                    "approx_equals": 0.995,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "row_key": "selected",
                            "column": "Recall@5",
                            "template": "{value}",
                            "value_format": ".3f",
                            "exact": True,
                        }
                    ],
                },
                {
                    "id": "mrr",
                    "artifact": ".locallens/current.json",
                    "path": "models[model=selected].mrr",
                    "approx_equals": 0.983,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "row_key": "selected",
                            "column": "MRR@10",
                            "template": "{value}",
                            "value_format": ".3f",
                            "exact": True,
                        }
                    ],
                },
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "passed"
    assert report["checked_public_metric_table_cells"] == 3


def test_evidence_consistency_fails_when_public_metric_table_cell_has_no_claim(
    tmp_path: Path,
):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/benchmark.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "\n".join(
            [
                "| Model | Top1 | Recall@5 | MRR@10 |",
                "| --- | ---: | ---: | ---: |",
                "| `selected` | 0.970 | 0.995 | 0.983 |",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(
        tmp_path / ".locallens" / "current.json",
        {"models": [{"model": "selected", "top1": 0.97}]},
    )
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "public_metric_table_coverage": [
                {
                    "artifact": "docs/benchmark.md",
                    "required_headers": ["Model", "Top1", "Recall@5", "MRR@10"],
                    "columns": ["Top1", "Recall@5", "MRR@10"],
                }
            ],
            "checks": [
                {
                    "id": "top1",
                    "artifact": ".locallens/current.json",
                    "path": "models[model=selected].top1",
                    "approx_equals": 0.97,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "row_key": "selected",
                            "column": "Top1",
                            "template": "{value}",
                            "value_format": ".3f",
                            "exact": True,
                        }
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "public metric table cell missing claim"


def test_evidence_consistency_can_scope_coverage_to_single_number_cells(
    tmp_path: Path,
):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/release.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "release.md").write_text(
        "\n".join(
            [
                "| Area | Current Result |",
                "| --- | --- |",
                "| PDF fixture | 73 synthetic PDFs across text cases |",
                "| Text fixture | 22 files, 46 units, 34 evaluated text queries |",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(tmp_path / ".locallens" / "current.json", {"pdf_files": 73})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "public_metric_table_coverage": [
                {
                    "artifact": "docs/release.md",
                    "required_headers": ["Area", "Current Result"],
                    "columns": ["Current Result"],
                    "single_number_only": True,
                }
            ],
            "checks": [
                {
                    "id": "pdf-files",
                    "artifact": ".locallens/current.json",
                    "path": "pdf_files",
                    "equals": 73,
                    "public_table": [
                        {
                            "artifact": "docs/release.md",
                            "row_key": "PDF fixture",
                            "column": "Current Result",
                            "template": "{value} synthetic PDFs",
                        }
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "passed"
    assert report["checked_public_metric_table_cells"] == 1


def test_evidence_consistency_fails_when_public_table_drifts(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/benchmark.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "\n".join(
            [
                "| Model | Top1 | Recall@5 |",
                "| --- | ---: | ---: |",
                "| `google/siglip-base-patch16-224` | 0.900 | 0.995 |",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(
        tmp_path / ".locallens" / "current.json",
        {"models": [{"model": "siglip", "top1": 0.97}]},
    )
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [
                {
                    "id": "siglip-table-top1",
                    "artifact": ".locallens/current.json",
                    "path": "models[model=siglip].top1",
                    "approx_equals": 0.97,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "row_key": "google/siglip-base-patch16-224",
                            "column": "Top1",
                            "template": "{value}",
                            "value_format": ".3f",
                        }
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "public table claim mismatch"


def test_evidence_consistency_fails_when_exact_public_table_cell_has_extra_metric(
    tmp_path: Path,
):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/benchmark.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "\n".join(
            [
                "| Model | Top1 | Recall@5 |",
                "| --- | ---: | ---: |",
                "| `google/siglip-base-patch16-224` | 0.970 stale 0.900 | 0.995 |",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(
        tmp_path / ".locallens" / "current.json",
        {"models": [{"model": "siglip", "top1": 0.97}]},
    )
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [
                {
                    "id": "siglip-table-top1",
                    "artifact": ".locallens/current.json",
                    "path": "models[model=siglip].top1",
                    "approx_equals": 0.97,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "row_key": "google/siglip-base-patch16-224",
                            "column": "Top1",
                            "template": "{value}",
                            "value_format": ".3f",
                            "exact": True,
                        }
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "public table claim mismatch"


def test_evidence_consistency_fails_on_ambiguous_public_table_row(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/benchmark.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "\n".join(
            [
                "| Area | Current Status |",
                "| --- | --- |",
                "| Vision image retrieval | top1 0.970 |",
                "| Vision image retrieval | top1 0.900 |",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(tmp_path / ".locallens" / "current.json", {"top1": 0.97})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [
                {
                    "id": "vision-table-top1",
                    "artifact": ".locallens/current.json",
                    "path": "top1",
                    "approx_equals": 0.97,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "row_key": "Vision image retrieval",
                            "column": "Current Status",
                            "template": "top1 {value}",
                            "value_format": ".3f",
                        }
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "public table row is ambiguous"


def test_evidence_consistency_scopes_public_table_assertion_by_headers(
    tmp_path: Path,
):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/benchmark.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "\n".join(
            [
                "| Files | Recall@5 |",
                "| ---: | ---: |",
                "| 73 | 0.900 |",
                "",
                "| Files | Units | Recall@5 |",
                "| ---: | ---: | ---: |",
                "| 73 | 86 | 1.000 |",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(tmp_path / ".locallens" / "current.json", {"recall": 1.0})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [
                {
                    "id": "pdf-table-recall",
                    "artifact": ".locallens/current.json",
                    "path": "recall",
                    "approx_equals": 1.0,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "required_headers": ["Files", "Units", "Recall@5"],
                            "row_key": "73",
                            "column": "Recall@5",
                            "template": "{value}",
                            "value_format": ".3f",
                            "exact": True,
                        }
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "passed"


def test_evidence_consistency_scopes_metric_coverage_by_headers(tmp_path: Path):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text(
        "docs/benchmark.md\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "\n".join(
            [
                "| Files | Recall@5 |",
                "| ---: | ---: |",
                "| 73 | 0.900 |",
                "",
                "| Files | Units | Recall@5 |",
                "| ---: | ---: | ---: |",
                "| 73 | 86 | 1.000 |",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(tmp_path / ".locallens" / "current.json", {"recall": 1.0})
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "public_metric_table_coverage": [
                {
                    "artifact": "docs/benchmark.md",
                    "required_headers": ["Files", "Units", "Recall@5"],
                    "columns": ["Recall@5"],
                }
            ],
            "checks": [
                {
                    "id": "pdf-table-recall",
                    "artifact": ".locallens/current.json",
                    "path": "recall",
                    "approx_equals": 1.0,
                    "public_table": [
                        {
                            "artifact": "docs/benchmark.md",
                            "required_headers": ["Files", "Units", "Recall@5"],
                            "row_key": "73",
                            "column": "Recall@5",
                            "template": "{value}",
                            "value_format": ".3f",
                            "exact": True,
                        }
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "passed"
    assert report["checked_public_metric_table_cells"] == 1


def test_evidence_consistency_fails_on_blocked_semantic_claim_when_gate_is_hold(
    tmp_path: Path,
):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text("docs\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "LocalLens supports broad structured-table retrieval.",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / ".locallens" / "current.json",
        {"claim_class_gate": {"broad_claim_allowed": False}},
    )
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [],
            "semantic_text_guards": [
                {
                    "id": "broad-table-claim-guard",
                    "artifact": ".locallens/current.json",
                    "path": "claim_class_gate.broad_claim_allowed",
                    "active_when": {"equals": False},
                    "scan_artifacts": ["docs"],
                    "blocked_patterns": ["broad structured-table retrieval"],
                    "allowed_line_patterns": [
                        "not .*broad structured-table retrieval",
                        "must not .*broad structured-table retrieval",
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "failed"
    assert report["findings"][0]["reason"] == "semantic claim guard violation"


def test_evidence_consistency_allows_negative_semantic_claim_when_gate_is_hold(
    tmp_path: Path,
):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text("docs\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "Cell-only success must not become broad structured-table retrieval.",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / ".locallens" / "current.json",
        {"claim_class_gate": {"broad_claim_allowed": False}},
    )
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [],
            "semantic_text_guards": [
                {
                    "id": "broad-table-claim-guard",
                    "artifact": ".locallens/current.json",
                    "path": "claim_class_gate.broad_claim_allowed",
                    "active_when": {"equals": False},
                    "scan_artifacts": ["docs"],
                    "blocked_patterns": ["broad structured-table retrieval"],
                    "allowed_line_patterns": [
                        "not .*broad structured-table retrieval",
                        "must not .*broad structured-table retrieval",
                    ],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "passed"
    assert report["checked_semantic_text_guards"] == 1


def test_evidence_consistency_skips_semantic_guard_when_gate_promotes(
    tmp_path: Path,
):
    (tmp_path / "generated_evidence_artifacts.txt").write_text(
        ".locallens/current.json\n", encoding="utf-8"
    )
    (tmp_path / "publication_artifacts.txt").write_text("docs\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark.md").write_text(
        "LocalLens supports broad structured-table retrieval.",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / ".locallens" / "current.json",
        {"claim_class_gate": {"broad_claim_allowed": True}},
    )
    _write_json(
        tmp_path / "release_evidence_claims.json",
        {
            "publication_manifests": ["publication_artifacts.txt"],
            "required_artifacts": [".locallens/current.json"],
            "historical_artifacts": [],
            "checks": [],
            "semantic_text_guards": [
                {
                    "id": "broad-table-claim-guard",
                    "artifact": ".locallens/current.json",
                    "path": "claim_class_gate.broad_claim_allowed",
                    "active_when": {"equals": False},
                    "scan_artifacts": ["docs"],
                    "blocked_patterns": ["broad structured-table retrieval"],
                }
            ],
        },
    )

    report = check_evidence_consistency(root=tmp_path)

    assert report["status"] == "passed"
