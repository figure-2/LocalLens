from fastapi.testclient import TestClient

from locallens.api.main import create_app


def test_agent_tool_returns_answer_ready_context():
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/agent/tools/document-search",
            json={
                "query": "휴가 신청 절차",
                "user_id": "employee_hr",
                "top_k": 2,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_name"] == "search_documents"
    assert payload["tool_input"]["query"] == "휴가 신청 절차"
    assert payload["evidence_packets"]
    assert payload["answer_ready_context"]["source_refs"]
    assert payload["mock_answer"]
    assert "final answer correctness" in payload["claim_boundary"]
