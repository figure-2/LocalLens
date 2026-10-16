from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from benchmarks.generate_non_filename_image_fixture import (
    generate_non_filename_fixture,
)


def test_generate_non_filename_image_fixture_creates_alias_paths(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "alias"
    golden = tmp_path / "golden.json"
    source.mkdir()
    Image.new("RGB", (16, 16), (255, 0, 0)).save(source / "badge_blue_security.png")

    report = generate_non_filename_fixture(
        source_dir=source,
        output_dir=output,
        golden_path=golden,
        scenes=[
            (
                "badge_blue_security",
                "blue security badge",
                "badge",
                "blue",
                "security",
            )
        ],
    )
    data = json.loads(golden.read_text(encoding="utf-8"))
    first = data["queries"][0]

    assert report["images"] == 1
    assert report["queries"] == report["images"]
    assert first["relevant"][0]["relative_path"] == "asset_0001.png"
    assert first["image_key"] == {
        "object": "badge",
        "color": "blue",
        "context": "security",
    }
    assert "non-filename" in first["tags"]
    assert (output / "asset_0001.png").exists()
