param(
    [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
[Console]::InputEncoding = $Utf8NoBom

$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root "docker-compose.ax.yml"
$SchemaFile = Join-Path $Root "sql\001_ax_postgres_schema.sql"
$SeedFile = Join-Path $Root "sql\002_ax_mock_seed.sql"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Wait-Postgres {
    for ($i = 0; $i -lt 30; $i++) {
        docker compose -f $ComposeFile exec -T postgres pg_isready -U locallens -d locallens_ax *> $null
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "PostgreSQL did not become ready."
}

function Wait-Qdrant {
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:6333/healthz" -TimeoutSec 2 *> $null
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "Qdrant did not become ready."
}

Push-Location $Root
try {
    if (-not $SkipDocker) {
        Write-Step "Docker local services 실행"
        docker compose -f $ComposeFile up -d
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up failed."
        }
    }

    Write-Step "PostgreSQL/Qdrant readiness 확인"
    Wait-Postgres
    Wait-Qdrant

    Write-Step "PostgreSQL schema 적용"
    Get-Content -Raw -Encoding UTF8 -LiteralPath $SchemaFile |
        docker compose -f $ComposeFile exec -T postgres psql -U locallens -d locallens_ax -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL schema apply failed."
    }

    Write-Step "PostgreSQL mock seed 적용"
    Get-Content -Raw -Encoding UTF8 -LiteralPath $SeedFile |
        docker compose -f $ComposeFile exec -T postgres psql -U locallens -d locallens_ax -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL seed apply failed."
    }

    Write-Step "Qdrant collection 생성 및 mock vector upsert"
    $env:LOCALLENS_AX_QDRANT_URL = "http://127.0.0.1:6333"
    $env:LOCALLENS_AX_QDRANT_COLLECTION = "locallens_ax_chunks"
    @'
from locallens.ax.embeddings import deterministic_text_vector
from locallens.ax.mock_corpus import MOCK_DOCUMENTS
from locallens.ax.qdrant_store import QdrantVectorStore, build_qdrant_vector_store
from qdrant_client import models

vector_size = len(deterministic_text_vector("seed"))
store = build_qdrant_vector_store()
if store.client.collection_exists(store.collection_name):
    store.client.delete_collection(store.collection_name)
store.client.create_collection(
    collection_name=store.collection_name,
    vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
)
vectors = {}
for document in MOCK_DOCUMENTS:
    for chunk in document["chunks"]:
        vectors[chunk["chunk_id"]] = deterministic_text_vector(
            f"{document['title']} {chunk['text']}"
        )

result = store.upsert_documents(MOCK_DOCUMENTS, vectors_by_chunk_id=vectors)
print(result)
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Qdrant mock vector upsert failed."
    }

    Write-Step "pytest 실행"
    python -m pytest tests\test_ax_mock_e2e.py tests\test_ax_contracts.py tests\test_ax_ranking.py tests\test_ax_agent_contract.py -q
    if ($LASTEXITCODE -ne 0) {
        throw "pytest failed."
    }

    Write-Step "API smoke 실행"
    $env:LOCALLENS_AX_METADATA_BACKEND = "postgres"
    $env:LOCALLENS_AX_RETRIEVAL_BACKEND = "hybrid"
    $env:LOCALLENS_AX_DATABASE_URL = "postgresql://locallens:locallens_local_only@127.0.0.1:54329/locallens_ax"
    $env:LOCALLENS_AX_QDRANT_URL = "http://127.0.0.1:6333"
    $env:LOCALLENS_AX_QDRANT_COLLECTION = "locallens_ax_chunks"
    @'
from fastapi.testclient import TestClient

from locallens.api.main import create_app

LEAVE_QUERY = "\ud734\uac00 \uc2e0\uccad \uc808\ucc28"
DOCUMENT_QUERY = "Qdrant \ub3c4\uc785 \uc774\uc720\uac00 \uc801\ud78c \ubb38\uc11c"
IMAGE_QUERY = "\uc544\ud0a4\ud14d\ucc98 \ub2e4\uc774\uc5b4\uadf8\ub7a8 \uc774\ubbf8\uc9c0"

with TestClient(create_app()) as client:
    health = client.get("/api/v1/health")
    print("health:", health.status_code, health.json())
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    search = client.get(
        "/api/v1/search",
        params={"q": LEAVE_QUERY, "user_id": "employee_hr", "top_k": 3},
    )
    print("search:", search.status_code, search.json())
    assert search.status_code == 200
    payload = search.json()
    assert payload["results"], "search returned no results"
    top = payload["results"][0]
    assert top["document_id"] == "doc_hr_leave_policy"
    assert top.get("keyword_score", 0) > 0 or top.get("match_type") == "hybrid"

    document_search = client.get(
        "/api/v1/search",
        params={"q": DOCUMENT_QUERY, "user_id": "employee_hr", "top_k": 3},
    )
    print("document_search:", document_search.status_code, document_search.json())
    assert document_search.status_code == 200
    assert document_search.json()["results"], "document search returned no results"

    image_search = client.get(
        "/api/v1/search",
        params={
            "q": IMAGE_QUERY,
            "user_id": "employee_hr",
            "top_k": 3,
            "modality": "image",
        },
    )
    print("image_search:", image_search.status_code, image_search.json())
    assert image_search.status_code == 200
    image_payload = image_search.json()
    assert image_payload["results"], "image search returned no results"
    assert image_payload["results"][0]["modality"] == "image"

    agent = client.post(
        "/api/v1/agent/tools/document-search",
        json={"query": LEAVE_QUERY, "user_id": "employee_hr", "top_k": 3},
    )
    print("agent:", agent.status_code, agent.json())
    assert agent.status_code == 200
    agent_payload = agent.json()
    assert agent_payload["evidence_packets"]
    assert agent_payload["answer_ready_context"]["source_refs"]
    assert agent_payload["mock_answer"]

print("AX local smoke passed.")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "API smoke failed."
    }

    Write-Step "결과 요약"
    Write-Host "AX local smoke completed successfully." -ForegroundColor Green
    Write-Host "- Docker PostgreSQL/Qdrant ready"
    Write-Host "- PostgreSQL schema/seed applied"
    Write-Host "- Qdrant mock vectors upserted"
    Write-Host "- pytest passed"
    Write-Host "- API smoke passed"
} finally {
    Pop-Location
}

