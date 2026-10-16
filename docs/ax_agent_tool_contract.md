# LocalLens AX Agent Tool Contract

## 1. Purpose

`/api/v1/agent/tools/document-search`는 Agent가 답변을 생성하기 전에 사용할 문서 근거 후보를 반환하는 tool endpoint다.

이 endpoint는 최종 답변의 정답성을 보장하지 않는다. 역할은 검색 결과를 Agent가 사용할 수 있는 evidence packet과 answer-ready context로 정규화하는 것이다.

## 2. Request

```json
{
  "query": "휴가 신청 절차",
  "user_id": "employee_hr",
  "top_k": 5,
  "filters": {
    "department_id": "hr",
    "document_type": "pdf"
  }
}
```

## 3. Response

```json
{
  "tool_name": "search_documents",
  "tool_input": {
    "query": "휴가 신청 절차",
    "user_id": "employee_hr",
    "top_k": 5,
    "filters": {}
  },
  "evidence_packets": [
    {
      "document_id": "doc_hr_leave_policy",
      "chunk_id": "chunk_hr_leave_001",
      "title": "휴가 신청 가이드",
      "snippet": "연차와 반차는 사내 포털의 근태 메뉴에서 신청합니다.",
      "source_ref": "doc_hr_leave_policy#page=1&chunk=chunk_hr_leave_001",
      "score": 1.0,
      "keyword_score": 1.0,
      "semantic_score": 0.9861,
      "match_type": "hybrid"
    }
  ],
  "answer_ready_context": {
    "query": "휴가 신청 절차",
    "user_id": "employee_hr",
    "source_refs": [
      "doc_hr_leave_policy#page=1&chunk=chunk_hr_leave_001"
    ],
    "snippets": [
      {
        "title": "휴가 신청 가이드",
        "source_ref": "doc_hr_leave_policy#page=1&chunk=chunk_hr_leave_001",
        "snippet": "연차와 반차는 사내 포털의 근태 메뉴에서 신청합니다.",
        "match_type": "hybrid"
      }
    ],
    "instruction": "Use only the returned evidence packets..."
  },
  "mock_answer": "시연용 답변",
  "claim_boundary": "This mock tool returns evidence packets only. It does not claim final answer correctness."
}
```

## 4. Agent Flow

```text
User question
-> Agent tool input
-> PostgreSQL keyword candidates
-> Qdrant semantic candidates
-> Hybrid retrieval fusion
-> Evidence packets
-> Answer-ready context
-> Answer composer
```

## 5. Claim Boundary

Safe:

- Agent tool endpoint returns evidence packets.
- Evidence packet includes `source_ref`, score, match type, and snippet.
- Answer-ready context is built from returned evidence packets.
- Mock answer composer uses evidence packets only.

Unsafe:

- Final answer correctness is guaranteed.
- Agent answer quality is benchmarked on real data.
- Production Agent workflow was validated.
- Real company documents were used.

## 6. Interview Explanation

이 구조의 핵심은 Agent가 바로 LLM 답변을 생성하지 않고, 먼저 검색 도구를 통해 사용할 수 있는 근거 후보를 받는다는 점이다. 검색 결과는 단순 text가 아니라 `source_ref`, 점수, 검색 방식, 문서 metadata를 포함한 evidence packet으로 정규화된다.

면접에서는 “Agent가 어떤 근거를 보고 답했는지 추적 가능하게 만들기 위해 tool response contract를 분리했다”고 설명하면 된다.
