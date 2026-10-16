from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from locallens.core.config import Settings
from locallens.extractors.pdf_vlm_adapter import build_local_vlm_captioner
from locallens.security.artifact_scan import load_blocked_terms
from locallens.security.artifact_scan import public_findings
from locallens.security.artifact_scan import scan_text_artifact
from locallens.security.redaction import redact_secret_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="local-vlm-image-smoke")
    parser.add_argument("image")
    parser.add_argument("--out", default=None)
    parser.add_argument("--blocked-term", action="append", default=[])
    parser.add_argument("--blocked-terms-file", default=None)
    args = parser.parse_args(argv)

    try:
        report = run_local_vlm_image_smoke(
            image_path=Path(args.image),
            settings=Settings.from_env(),
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1

    content = json.dumps(report, indent=2)
    findings = scan_text_artifact(
        content,
        args.out or "local-vlm-image-smoke",
        load_blocked_terms(args.blocked_term, args.blocked_terms_file),
    )
    if findings:
        print(
            json.dumps(
                {
                    "error": "artifact scan failed",
                    "findings": public_findings(findings),
                },
                indent=2,
            )
        )
        return 1
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    print(content)
    return 0 if report["status"] == "passed" else 1


def run_local_vlm_image_smoke(image_path: Path, settings: Settings) -> dict:
    started = time.perf_counter()
    captioner = build_local_vlm_captioner(settings)
    result = captioner.caption_region(
        image_path,
        {
            "relative_path": image_path.name,
            "page_no": 1,
            "image_no": 0,
            "bbox": None,
        },
    )
    elapsed = time.perf_counter() - started
    caption = redact_secret_text(result.text or "")
    non_empty = bool(caption.strip())
    return {
        "benchmark_mode": "local-vlm-image-smoke",
        "status": "passed" if non_empty else "failed",
        "unit_contract": "pdf_visual_caption",
        "fixture": {
            "kind": "single-image",
            "count": 1,
            "path_reported": False,
        },
        "candidate": settings.pdf_vlm_model_name or "unconfigured",
        "profile": captioner.profile,
        "locality": result.locality.to_payload(),
        "caption": {
            "non_empty": non_empty,
            "chars": len(caption),
            "sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
            "preview": caption[:240],
        },
        "runtime": {
            "seconds": elapsed,
        },
        "quality": {
            "status": "not-evaluated",
            "recall_at_5": None,
            "mrr_at_10": None,
            "p50_ms": None,
            "p95_ms": None,
        },
        "promotion_decision": "hold",
        "release_claim_allowed": False,
        "result_status": result.status,
    }


if __name__ == "__main__":
    raise SystemExit(main())
