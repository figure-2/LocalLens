from fastapi.testclient import TestClient

from locallens.api.main import app


client = TestClient(app)


def test_ax_health_endpoint():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "mock-e2e"}


def test_ax_demo_scenario_endpoint():
    response = client.get("/api/v1/demo/scenario")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "LocalLens 멀티모달 검색 mock E2E"
    assert len(payload["script"]) >= 5


def test_hr_user_can_search_leave_policy():
    response = client.get(
        "/api/v1/search",
        params={"q": "휴가 신청 절차", "user_id": "employee_hr", "top_k": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "휴가 신청 절차"
    assert payload["results"]
    assert payload["results"][0]["document_id"] == "doc_hr_leave_policy"
    assert payload["results"][0]["source_ref"]


def test_hr_user_cannot_search_engineering_only_oncall_doc():
    response = client.get(
        "/api/v1/search",
        params={"q": "장애 대응 온콜", "user_id": "employee_hr", "top_k": 5},
    )

    assert response.status_code == 200
    document_ids = {item["document_id"] for item in response.json()["results"]}
    assert "doc_eng_oncall_runbook" not in document_ids


def test_local_user_can_search_image_by_description():
    response = client.get(
        "/api/v1/search",
        params={
            "q": "아키텍처 다이어그램 이미지",
            "user_id": "employee_hr",
            "top_k": 3,
            "modality": "image",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    assert payload["results"][0]["document_id"] == "file_architecture_diagram_png"
    assert payload["results"][0]["modality"] == "image"


def test_agent_tool_returns_evidence_packets_only():
    response = client.post(
        "/api/v1/agent/tools/document-search",
        json={
            "query": "문서 권한 필터",
            "user_id": "employee_hr",
            "top_k": 3,
            "filters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_name"] == "search_documents"
    assert "evidence_packets" in payload
    assert "claim_boundary" in payload


def test_hybrid_retrieval_falls_back_to_keyword_when_qdrant_empty(monkeypatch):
    monkeypatch.setenv("LOCALLENS_AX_RETRIEVAL_BACKEND", "hybrid")

    response = client.get(
        "/api/v1/search",
        params={"q": "휴가 신청 절차", "user_id": "employee_hr", "top_k": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    assert payload["results"][0]["document_id"] == "doc_hr_leave_policy"
    assert payload["results"][0]["match_type"] in {"keyword", "hybrid"}
