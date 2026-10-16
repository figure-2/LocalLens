from __future__ import annotations


MOCK_E2E_SCENARIO = {
    "title": "LocalLens 멀티모달 검색 mock E2E",
    "company": "LocalLens Demo Workspace",
    "goal": "로컬 텍스트, PDF, 이미지 설명을 자연어로 검색하고 AX Workspace 확장에서는 권한 범위 안의 근거만 확인한다.",
    "users": [
        {
            "user_id": "employee_hr",
            "label": "로컬 사용자",
            "acl_tags": ["all_employee", "hr"],
            "primary_questions": [
                "Qdrant 도입 이유가 적힌 문서",
                "아키텍처 다이어그램 이미지",
                "파란색 대시보드 화면 캡처",
                "휴가 신청 절차",
            ],
        },
        {
            "user_id": "employee_eng",
            "label": "엔지니어",
            "acl_tags": ["all_employee", "engineering"],
            "primary_questions": [
                "장애 대응 온콜",
                "장애 조치 후 보고서에는 무엇을 기록해?",
                "문서 권한 필터는 어떻게 적용해야 해?",
            ],
        },
        {
            "user_id": "employee_sales",
            "label": "세일즈 담당자",
            "acl_tags": ["all_employee", "sales"],
            "primary_questions": [
                "AX 제안서에는 어떤 가치를 넣어야 해?",
                "고객 제안서 작성 순서",
                "문서 권한 필터는 어떻게 적용해야 해?",
            ],
        },
    ],
    "script": [
        {
            "step": 1,
            "actor": "employee_hr",
            "action": "documents",
            "query": "",
            "expected": "로컬 사용자에게 공개 문서, 이미지, AX 예시 문서가 보인다.",
        },
        {
            "step": 2,
            "actor": "employee_hr",
            "action": "search",
            "query": "Qdrant 도입 이유가 적힌 문서",
            "expected": "Qdrant 도입 검토 보고서와 source_ref가 반환된다.",
        },
        {
            "step": 3,
            "actor": "employee_hr",
            "action": "search",
            "query": "아키텍처 다이어그램 이미지",
            "expected": "modality=image 조건에서 검색 아키텍처 다이어그램 이미지가 반환된다.",
        },
        {
            "step": 4,
            "actor": "employee_hr",
            "action": "agent_tool",
            "query": "문서 권한 필터는 어떻게 적용해야 해?",
            "expected": "AX Workspace 확장 모드에서 Agent tool은 최종 답변이 아니라 evidence packet을 반환한다.",
        },
        {
            "step": 5,
            "actor": "employee_sales",
            "action": "search",
            "query": "AX 제안서에는 어떤 가치를 넣어야 해?",
            "expected": "세일즈 권한 문서의 제안서 템플릿 chunk가 반환된다.",
        },
    ],
}
