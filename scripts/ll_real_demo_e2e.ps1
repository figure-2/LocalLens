param(
    [string]$ModelCacheDir = "runtime-cache\smolvlm-256m-instruct",
    [string]$WorkspaceId = "real-demo-e2e",
    [string]$DataDir = ".locallens\real-demo-e2e",
    [switch]$KeepData
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
[Console]::InputEncoding = $Utf8NoBom

$Root = Split-Path -Parent $PSScriptRoot
$DemoRoot = Join-Path $Root "benchmarks\fixtures\locallens_real_demo"
$ResolvedModelCache = Join-Path $Root $ModelCacheDir

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

Push-Location $Root
try {
    Write-Step "Check local VLM cache"
    if (-not (Test-Path -LiteralPath $ResolvedModelCache)) {
        throw "Local VLM cache not found: $ResolvedModelCache"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ResolvedModelCache "config.json"))) {
        throw "Local VLM cache is missing config.json: $ResolvedModelCache"
    }

    Write-Step "Set environment variables"
    $env:LOCALLENS_MODEL_CACHE_DIR = $ResolvedModelCache
    $env:LOCALLENS_MODEL_LOCAL_FILES_ONLY = "1"
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"

    if ($KeepData) {
        $env:LOCALLENS_E2E_KEEP_DATA = "1"
    } else {
        Remove-Item Env:\LOCALLENS_E2E_KEEP_DATA -ErrorAction SilentlyContinue
    }
    $env:LOCALLENS_E2E_WORKSPACE_ID = $WorkspaceId
    $env:LOCALLENS_E2E_DATA_DIR = $DataDir
    $env:LOCALLENS_E2E_DEMO_ROOT = $DemoRoot
    $env:LOCALLENS_E2E_MODEL_NAME = "HuggingFaceTB/SmolVLM-256M-Instruct"

    Write-Step "Run real demo E2E"
    @'
from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from locallens.api.main import app


def assert_first_title(payload: dict, expected: str, label: str) -> None:
    results = payload.get("results", [])
    assert results, f"{label} returned no results"
    first = results[0]
    actual = first.get("title")
    assert actual == expected, f"{label} first title mismatch: expected={expected}, actual={actual}"


def local_agent_packet(query: str, user_id: str, mode: str, results: list[dict]) -> dict:
    source_refs = [item["source_ref"] for item in results]
    snippets = [
        {
            "title": item["title"],
            "source_ref": item["source_ref"],
            "snippet": item["snippet"],
            "match_type": item["match_type"],
            "modality": item["modality"],
        }
        for item in results
    ]
    primary = results[0] if results else None
    return {
        "tool_name": "locallens.local_search",
        "tool_input": {
            "query": query,
            "user_id": user_id,
            "mode": mode,
            "top_k": 5,
        },
        "evidence_packets": results,
        "answer_ready_context": {
            "query": query,
            "user_id": user_id,
            "mode": mode,
            "source_refs": source_refs,
            "snippets": snippets,
            "instruction": "Use only these LocalLens evidence packets.",
        },
        "mock_answer": (
            f"'{query}' primary evidence: {primary['title']} {primary['source_ref']}"
            if primary
            else f"'{query}' has no local file evidence."
        ),
        "claim_boundary": "Local demo evidence packet; not final LLM correctness proof.",
    }


root = Path(os.environ["LOCALLENS_E2E_DEMO_ROOT"]).resolve()
data_dir = Path(os.environ["LOCALLENS_E2E_DATA_DIR"]).resolve()
workspace_id = os.environ["LOCALLENS_E2E_WORKSPACE_ID"]
model_name = os.environ["LOCALLENS_E2E_MODEL_NAME"]
keep_data = os.environ.get("LOCALLENS_E2E_KEEP_DATA") == "1"

assert root.exists(), f"demo root does not exist: {root}"
assert root.is_dir(), f"demo root is not a directory: {root}"
assert root.name == "locallens_real_demo", f"unexpected demo root: {root}"

if not keep_data:
    marker = Path.cwd().resolve() / ".locallens"
    if data_dir.exists():
        assert marker in data_dir.parents, f"refusing to delete outside .locallens: {data_dir}"
        shutil.rmtree(data_dir)

client = TestClient(app)

sync = client.post(
    "/api/v1/local/sync",
    json={
        "root_path": str(root),
        "workspace_id": workspace_id,
        "data_dir": str(data_dir),
        "pdf_vlm_mode": "local-vlm",
        "pdf_vlm_model_name": model_name,
        "max_progress_events": 20,
    },
)
print("sync_status:", sync.status_code)
assert sync.status_code == 200, sync.text
sync_payload = sync.json()
report = sync_payload["report"]
print(
    "sync_report:",
    {
        key: report.get(key)
        for key in [
            "added",
            "updated",
            "deleted",
            "skipped",
            "failed",
            "units",
            "vlm_attempted",
            "vlm_succeeded",
            "vlm_empty",
            "vlm_failed",
        ]
    },
)
assert report["failed"] == 0, report
assert report["units"] >= 17, report
assert report["vlm_attempted"] >= 2, report
assert report["vlm_succeeded"] >= 2, report
assert report["vlm_failed"] == 0, report

search_cases = [
    (
        "text_document",
        {
            "q": "selective indexing content hash skipped files",
            "workspace_id": workspace_id,
            "data_dir": str(data_dir),
            "modality": "text",
            "unit_type": "document",
            "top_k": 5,
        },
        "local_sync_policy.md",
    ),
    (
        "image_description",
        {
            "q": "blue security badge shield",
            "workspace_id": workspace_id,
            "data_dir": str(data_dir),
            "modality": "image",
            "top_k": 5,
        },
        "blue_security_badge.png",
    ),
    (
        "pdf_text_page",
        {
            "q": "annual leave request approval flow",
            "workspace_id": workspace_id,
            "data_dir": str(data_dir),
            "modality": "text",
            "ext": ".pdf",
            "unit_type": "page",
            "top_k": 5,
        },
        "leave_approval_guide.pdf",
    ),
    (
        "pdf_visual_caption",
        {
            "q": "leave approval table manager approval HR confirmation",
            "workspace_id": workspace_id,
            "data_dir": str(data_dir),
            "modality": "text",
            "ext": ".pdf",
            "unit_type": "pdf_visual_caption",
            "top_k": 5,
        },
        "leave_approval_guide.pdf",
    ),
]

last_payload = None
for label, params, expected_title in search_cases:
    response = client.get("/api/v1/local/search", params=params)
    print(f"{label}_status:", response.status_code)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert_first_title(payload, expected_title, label)
    first = payload["results"][0]
    print(f"{label}_first:", first["title"], first["source_ref"])
    if label == "pdf_visual_caption":
        last_payload = payload

assert last_payload is not None
agent_packet = local_agent_packet(
    query="leave approval table manager approval HR confirmation",
    user_id="local_demo_user",
    mode="pdf",
    results=last_payload["results"],
)
print("local_agent_tool:", agent_packet["tool_name"])
print("local_agent_source_refs:", agent_packet["answer_ready_context"]["source_refs"][:2])
assert agent_packet["tool_name"] == "locallens.local_search"
assert agent_packet["evidence_packets"]
assert agent_packet["answer_ready_context"]["source_refs"]
assert any("leave_approval_guide.pdf" in ref for ref in agent_packet["answer_ready_context"]["source_refs"])

print("")
print("LL real demo E2E passed.")
print("- demo folder sync passed")
print("- text search passed")
print("- image search passed")
print("- PDF text search passed")
print("- PDF visual caption search passed")
print("- local Agent evidence packet passed")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "LL real demo E2E failed."
    }

    Write-Step "Summary"
    Write-Host "LL real demo E2E completed successfully." -ForegroundColor Green
    Write-Host "- demo folder sync passed"
    Write-Host "- text/image/PDF search passed"
    Write-Host "- local VLM PDF visual caption passed"
    Write-Host "- local Agent evidence packet passed"
} finally {
    Pop-Location
}
