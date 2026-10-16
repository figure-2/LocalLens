from __future__ import annotations

import json
from pathlib import Path

try:
    from benchmarks.generate_image_expansion import IMAGE_DIR, SCENES, _write_scene
except ModuleNotFoundError:
    from generate_image_expansion import IMAGE_DIR, SCENES, _write_scene


ROOT = Path(__file__).resolve().parent
ALIAS_IMAGE_DIR = ROOT / "fixtures" / "image_corpus_non_filename"
ALIAS_GOLDEN_PATH = ROOT / "fixtures" / "golden_image_non_filename_queries.json"


def main() -> None:
    generate_non_filename_fixture()


def generate_non_filename_fixture(
    *,
    source_dir: Path = IMAGE_DIR,
    output_dir: Path = ALIAS_IMAGE_DIR,
    golden_path: Path = ALIAS_GOLDEN_PATH,
    scenes: list[tuple[str, str, str, str, str]] | None = None,
) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    queries = []
    for index, scene in enumerate(scenes or SCENES, start=1):
        name, query, object_name, color_name, context_name = scene
        source_path = source_dir / f"{name}.png"
        if not source_path.exists():
            if source_dir == IMAGE_DIR:
                _write_scene(scene)
            else:
                raise FileNotFoundError(source_path)
        alias_name = f"asset_{index:04d}.png"
        (output_dir / alias_name).write_bytes(source_path.read_bytes())
        queries.append(
            {
                "id": f"image-alias-{index:04d}-en-001",
                "query": query,
                "modality": "image",
                "backend_profile": "transformers",
                "top_k": 10,
                "relevant": [
                    {
                        "relative_path": alias_name,
                        "unit_type": "image",
                        "gain": 3,
                        "max_rank": 3,
                    }
                ],
                "image_key": {
                    "object": object_name,
                    "color": color_name,
                    "context": context_name,
                },
                "tags": [
                    "image",
                    "english",
                    "scene",
                    "synthetic",
                    "sanitized-style",
                    "non-filename",
                    "hard-negative",
                    context_name,
                ],
            }
        )
    golden_path.write_text(
        json.dumps({"queries": queries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {"images": len(queries), "queries": len(queries)}


if __name__ == "__main__":
    main()
