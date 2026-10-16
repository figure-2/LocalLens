from __future__ import annotations

MOCK_USERS = {
    "employee_hr": {
        "user_id": "employee_hr",
        "name": "HR Employee",
        "department_id": "hr",
        "acl_tags": ["all_employee", "hr"],
    },
    "employee_eng": {
        "user_id": "employee_eng",
        "name": "Engineering Employee",
        "department_id": "engineering",
        "acl_tags": ["all_employee", "engineering"],
    },
    "employee_sales": {
        "user_id": "employee_sales",
        "name": "Sales Employee",
        "department_id": "sales",
        "acl_tags": ["all_employee", "sales"],
    },
}


MOCK_DOCUMENTS = [
    {
        "document_id": "doc_hr_leave_policy",
        "title": "휴가 신청 가이드",
        "department_id": "hr",
        "document_type": "pdf",
        "acl_tags": ["all_employee", "hr"],
        "version_id": "v1",
        "chunks": [
            {
                "chunk_id": "chunk_hr_leave_001",
                "page": 1,
                "modality": "pdf_text",
                "text": "연차와 반차는 사내 포털의 근태 메뉴에서 신청합니다. 팀장 승인 후 인사팀 검토가 완료되면 휴가 일정이 확정됩니다.",
                "keywords": ["휴가", "연차", "반차", "근태", "승인", "인사"],
            },
            {
                "chunk_id": "chunk_hr_leave_002",
                "page": 2,
                "modality": "pdf_text",
                "text": "병가는 증빙 서류를 첨부해야 하며, 긴급 휴가는 사후 승인 절차를 통해 처리할 수 있습니다.",
                "keywords": ["병가", "증빙", "긴급", "사후", "승인"],
            },
        ],
    },
    {
        "document_id": "doc_eng_oncall_runbook",
        "title": "장애 대응 온콜 Runbook",
        "department_id": "engineering",
        "document_type": "markdown",
        "acl_tags": ["engineering"],
        "version_id": "v3",
        "chunks": [
            {
                "chunk_id": "chunk_eng_oncall_001",
                "page": None,
                "modality": "text",
                "text": "장애 알림이 발생하면 담당자는 대시보드에서 영향 범위를 확인하고, 에러율과 지연 시간을 먼저 점검합니다.",
                "keywords": ["장애", "온콜", "대시보드", "에러율", "지연", "점검"],
            },
            {
                "chunk_id": "chunk_eng_oncall_002",
                "page": None,
                "modality": "text",
                "text": "장애 조치 후에는 원인, 조치 내용, 재발 방지 항목을 사후 보고서에 기록합니다.",
                "keywords": ["장애", "조치", "원인", "재발", "보고서"],
            },
        ],
    },
    {
        "document_id": "doc_sales_proposal_template",
        "title": "고객 제안서 작성 템플릿",
        "department_id": "sales",
        "document_type": "pptx",
        "acl_tags": ["sales"],
        "version_id": "v2",
        "chunks": [
            {
                "chunk_id": "chunk_sales_template_001",
                "page": 4,
                "modality": "slide_text",
                "text": "고객 제안서는 문제 정의, 기대 효과, 도입 일정, 비용 구조 순서로 작성합니다.",
                "keywords": ["고객", "제안서", "문제", "효과", "일정", "비용"],
            },
            {
                "chunk_id": "chunk_sales_template_002",
                "page": 8,
                "modality": "slide_text",
                "text": "AX 제안에서는 반복 업무 절감, 문서 검색 시간 단축, 지식 접근성 향상을 핵심 가치로 설명합니다.",
                "keywords": ["AX", "반복", "문서", "검색", "지식", "가치"],
            },
        ],
    },
    {
        "document_id": "doc_all_security_policy",
        "title": "사내 문서 보안 기본 정책",
        "department_id": "security",
        "document_type": "pdf",
        "acl_tags": ["all_employee"],
        "version_id": "v1",
        "chunks": [
            {
                "chunk_id": "chunk_security_policy_001",
                "page": 3,
                "modality": "pdf_text",
                "text": "문서는 공개, 내부, 제한, 기밀 등급으로 구분하며, 권한이 없는 사용자는 제한 문서를 열람할 수 없습니다.",
                "keywords": ["문서", "보안", "공개", "내부", "제한", "기밀", "권한"],
            },
            {
                "chunk_id": "chunk_security_policy_002",
                "page": 5,
                "modality": "pdf_text",
                "text": "검색 시스템은 사용자 권한을 기준으로 검색 후보를 필터링하고 최종 결과 반환 전 접근 가능 여부를 다시 확인해야 합니다.",
                "keywords": ["검색", "권한", "필터링", "접근", "결과", "확인"],
            },
        ],
    },
    {
        "document_id": "file_project_report_qdrant",
        "title": "Qdrant 도입 검토 보고서",
        "department_id": "personal",
        "document_type": "pdf",
        "acl_tags": ["all_employee"],
        "version_id": "v1",
        "chunks": [
            {
                "chunk_id": "chunk_project_report_qdrant_001",
                "page": 2,
                "modality": "pdf_text",
                "text": "Qdrant는 벡터 검색과 payload filter를 함께 제공해 문서 chunk, 파일 유형, 접근 범위를 검색 단계에서 함께 제한할 수 있습니다.",
                "keywords": ["Qdrant", "벡터", "payload", "filter", "문서", "검색", "청크"],
            },
            {
                "chunk_id": "chunk_project_report_qdrant_002",
                "page": 4,
                "modality": "pdf_text",
                "text": "PostgreSQL은 문서 메타데이터와 검색 로그를 관리하고, Qdrant는 텍스트와 이미지 caption 벡터를 검색하는 구조로 분리합니다.",
                "keywords": ["PostgreSQL", "Qdrant", "메타데이터", "검색로그", "이미지", "caption"],
            },
        ],
    },
    {
        "document_id": "file_architecture_diagram_png",
        "title": "검색 아키텍처 다이어그램 이미지",
        "department_id": "personal",
        "document_type": "image",
        "acl_tags": ["all_employee"],
        "version_id": "v1",
        "chunks": [
            {
                "chunk_id": "chunk_image_architecture_001",
                "page": None,
                "modality": "image",
                "text": "PostgreSQL metadata store와 Qdrant vector store가 FastAPI API와 Agent tool로 연결된 검색 아키텍처 다이어그램 이미지입니다.",
                "keywords": ["이미지", "아키텍처", "다이어그램", "PostgreSQL", "Qdrant", "FastAPI", "Agent"],
            },
        ],
    },
    {
        "document_id": "file_dashboard_screenshot_png",
        "title": "파란색 대시보드 화면 캡처",
        "department_id": "personal",
        "document_type": "image",
        "acl_tags": ["all_employee"],
        "version_id": "v1",
        "chunks": [
            {
                "chunk_id": "chunk_image_dashboard_001",
                "page": None,
                "modality": "image",
                "text": "파란색 대시보드 화면에 검색 결과 카드, 필터 패널, 점수 그래프가 함께 표시된 UI 캡처 이미지입니다.",
                "keywords": ["이미지", "파란색", "대시보드", "검색결과", "필터", "그래프", "UI"],
            },
        ],
    },
]
