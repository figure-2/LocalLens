-- LocalLens AX mock seed data for local PostgreSQL smoke tests.
-- This mirrors locallens.ax.mock_corpus without adding real company data.

BEGIN;

INSERT INTO departments (department_id, name) VALUES
    ('hr', 'Human Resources'),
    ('engineering', 'Engineering'),
    ('sales', 'Sales'),
    ('security', 'Security'),
    ('personal', 'Personal Local Files')
ON CONFLICT (department_id) DO UPDATE
SET name = EXCLUDED.name;

INSERT INTO users (user_id, department_id, display_name, role) VALUES
    ('employee_hr', 'hr', 'HR Employee', 'employee'),
    ('employee_eng', 'engineering', 'Engineering Employee', 'employee'),
    ('employee_sales', 'sales', 'Sales Employee', 'employee')
ON CONFLICT (user_id) DO UPDATE
SET
    department_id = EXCLUDED.department_id,
    display_name = EXCLUDED.display_name,
    role = EXCLUDED.role;

INSERT INTO documents (
    document_id,
    owner_department_id,
    title,
    document_type,
    access_level,
    current_version_id
) VALUES
    ('doc_hr_leave_policy', 'hr', '휴가 신청 가이드', 'pdf', 'internal', 'v1'),
    ('doc_eng_oncall_runbook', 'engineering', '장애 대응 온콜 Runbook', 'markdown', 'restricted', 'v3'),
    ('doc_sales_proposal_template', 'sales', '고객 제안서 작성 템플릿', 'pptx', 'restricted', 'v2'),
    ('doc_all_security_policy', 'security', '사내 문서 보안 기본 정책', 'pdf', 'internal', 'v1'),
    ('file_project_report_qdrant', 'personal', 'Qdrant 도입 검토 보고서', 'pdf', 'internal', 'v1'),
    ('file_architecture_diagram_png', 'personal', '검색 아키텍처 다이어그램 이미지', 'image', 'internal', 'v1'),
    ('file_dashboard_screenshot_png', 'personal', '파란색 대시보드 화면 캡처', 'image', 'internal', 'v1')
ON CONFLICT (document_id) DO UPDATE
SET
    owner_department_id = EXCLUDED.owner_department_id,
    title = EXCLUDED.title,
    document_type = EXCLUDED.document_type,
    access_level = EXCLUDED.access_level,
    current_version_id = EXCLUDED.current_version_id,
    updated_at = now();

INSERT INTO document_versions (
    document_id,
    version_id,
    content_hash,
    source_path_hash
) VALUES
    ('doc_hr_leave_policy', 'v1', 'mock_hash_hr_leave_v1', 'mock_path_hr_leave'),
    ('doc_eng_oncall_runbook', 'v3', 'mock_hash_eng_oncall_v3', 'mock_path_eng_oncall'),
    ('doc_sales_proposal_template', 'v2', 'mock_hash_sales_template_v2', 'mock_path_sales_template'),
    ('doc_all_security_policy', 'v1', 'mock_hash_security_policy_v1', 'mock_path_security_policy'),
    ('file_project_report_qdrant', 'v1', 'mock_hash_project_report_qdrant_v1', 'mock_path_project_report_qdrant'),
    ('file_architecture_diagram_png', 'v1', 'mock_hash_architecture_diagram_v1', 'mock_path_architecture_diagram'),
    ('file_dashboard_screenshot_png', 'v1', 'mock_hash_dashboard_screenshot_v1', 'mock_path_dashboard_screenshot')
ON CONFLICT (document_id, version_id) DO UPDATE
SET
    content_hash = EXCLUDED.content_hash,
    source_path_hash = EXCLUDED.source_path_hash;

INSERT INTO document_chunks (
    chunk_id,
    document_id,
    version_id,
    page_no,
    chunk_no,
    modality,
    text_preview,
    qdrant_point_id
) VALUES
    (
        'chunk_hr_leave_001',
        'doc_hr_leave_policy',
        'v1',
        1,
        1,
        'pdf_text',
        '연차와 반차는 사내 포털의 근태 메뉴에서 신청합니다.',
        'point_chunk_hr_leave_001'
    ),
    (
        'chunk_hr_leave_002',
        'doc_hr_leave_policy',
        'v1',
        2,
        2,
        'pdf_text',
        '병가는 증빙 서류를 첨부해야 하며, 긴급 휴가는 사후 승인 절차를 통해 처리할 수 있습니다.',
        'point_chunk_hr_leave_002'
    ),
    (
        'chunk_eng_oncall_001',
        'doc_eng_oncall_runbook',
        'v3',
        NULL,
        1,
        'text',
        '장애 알림이 발생하면 담당자는 대시보드에서 영향 범위를 확인합니다.',
        'point_chunk_eng_oncall_001'
    ),
    (
        'chunk_eng_oncall_002',
        'doc_eng_oncall_runbook',
        'v3',
        NULL,
        2,
        'text',
        '장애 조치 후에는 원인, 조치 내용, 재발 방지 항목을 사후 보고서에 기록합니다.',
        'point_chunk_eng_oncall_002'
    ),
    (
        'chunk_sales_template_001',
        'doc_sales_proposal_template',
        'v2',
        4,
        1,
        'slide_text',
        '고객 제안서는 문제 정의, 기대 효과, 도입 일정, 비용 구조 순서로 작성합니다.',
        'point_chunk_sales_template_001'
    ),
    (
        'chunk_sales_template_002',
        'doc_sales_proposal_template',
        'v2',
        8,
        2,
        'slide_text',
        'AX 제안에서는 반복 업무 절감, 문서 검색 시간 단축, 지식 접근성 향상을 핵심 가치로 설명합니다.',
        'point_chunk_sales_template_002'
    ),
    (
        'chunk_security_policy_001',
        'doc_all_security_policy',
        'v1',
        3,
        1,
        'pdf_text',
        '문서는 공개, 내부, 제한, 기밀 등급으로 구분합니다.',
        'point_chunk_security_policy_001'
    ),
    (
        'chunk_security_policy_002',
        'doc_all_security_policy',
        'v1',
        5,
        2,
        'pdf_text',
        '검색 시스템은 사용자 권한을 기준으로 검색 후보를 필터링해야 합니다.',
        'point_chunk_security_policy_002'
    ),
    (
        'chunk_project_report_qdrant_001',
        'file_project_report_qdrant',
        'v1',
        2,
        1,
        'pdf_text',
        'Qdrant는 벡터 검색과 payload filter를 함께 제공해 문서 chunk, 파일 유형, 접근 범위를 검색 단계에서 함께 제한할 수 있습니다.',
        'point_chunk_project_report_qdrant_001'
    ),
    (
        'chunk_project_report_qdrant_002',
        'file_project_report_qdrant',
        'v1',
        4,
        2,
        'pdf_text',
        'PostgreSQL은 문서 메타데이터와 검색 로그를 관리하고, Qdrant는 텍스트와 이미지 caption 벡터를 검색하는 구조로 분리합니다.',
        'point_chunk_project_report_qdrant_002'
    ),
    (
        'chunk_image_architecture_001',
        'file_architecture_diagram_png',
        'v1',
        NULL,
        1,
        'image',
        'PostgreSQL metadata store와 Qdrant vector store가 FastAPI API와 Agent tool로 연결된 검색 아키텍처 다이어그램 이미지입니다.',
        'point_chunk_image_architecture_001'
    ),
    (
        'chunk_image_dashboard_001',
        'file_dashboard_screenshot_png',
        'v1',
        NULL,
        1,
        'image',
        '파란색 대시보드 화면에 검색 결과 카드, 필터 패널, 점수 그래프가 함께 표시된 UI 캡처 이미지입니다.',
        'point_chunk_image_dashboard_001'
    )
ON CONFLICT (chunk_id) DO UPDATE
SET
    document_id = EXCLUDED.document_id,
    version_id = EXCLUDED.version_id,
    page_no = EXCLUDED.page_no,
    chunk_no = EXCLUDED.chunk_no,
    modality = EXCLUDED.modality,
    text_preview = EXCLUDED.text_preview,
    qdrant_point_id = EXCLUDED.qdrant_point_id;

INSERT INTO access_policies (policy_id, document_id, department_id, acl_tag, can_read) VALUES
    ('pol_hr_leave_all_employee', 'doc_hr_leave_policy', NULL, 'all_employee', true),
    ('pol_hr_leave_hr', 'doc_hr_leave_policy', 'hr', 'hr', true),
    ('pol_eng_oncall_engineering', 'doc_eng_oncall_runbook', 'engineering', 'engineering', true),
    ('pol_sales_template_sales', 'doc_sales_proposal_template', 'sales', 'sales', true),
    ('pol_security_policy_all_employee', 'doc_all_security_policy', NULL, 'all_employee', true),
    ('pol_project_report_all_employee', 'file_project_report_qdrant', NULL, 'all_employee', true),
    ('pol_architecture_diagram_all_employee', 'file_architecture_diagram_png', NULL, 'all_employee', true),
    ('pol_dashboard_screenshot_all_employee', 'file_dashboard_screenshot_png', NULL, 'all_employee', true)
ON CONFLICT (policy_id) DO UPDATE
SET
    document_id = EXCLUDED.document_id,
    department_id = EXCLUDED.department_id,
    acl_tag = EXCLUDED.acl_tag,
    can_read = EXCLUDED.can_read;

COMMIT;
