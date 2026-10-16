# LocalLens AX Mock E2E Runbook

## 목적

유료 API나 외부 사내 데이터를 사용하지 않고 LocalLens AX의 핵심 흐름을 시연한다.

검증 범위는 mock dataset 기준이다.

## 실행

```powershell
python -m pip install -e ".[dev]"
python -m uvicorn locallens.api.main:app --reload --host 127.0.0.1 --port 8010
```

## Smoke Scenario

### 0. 시나리오 확인

```powershell
Invoke-RestMethod "http://127.0.0.1:8010/api/v1/demo/scenario"
```

기대:

```text
HR, Engineering, Sales 사용자와 5단계 시연 script가 반환된다.
```

### 1. Health

```powershell
Invoke-RestMethod "http://127.0.0.1:8010/api/v1/health"
```

기대:

```json
{
  "status": "ok",
  "mode": "mock-e2e"
}
```

### 2. 임직원 문서 목록

```powershell
Invoke-RestMethod "http://127.0.0.1:8010/api/v1/documents?user_id=employee_hr"
```

기대:

- `employee_hr`는 `all_employee`, `hr` 문서만 볼 수 있다.
- `engineering` 전용 온콜 문서는 보이면 안 된다.

### 3. 자연어 검색

```powershell
Invoke-RestMethod "http://127.0.0.1:8010/api/v1/search?q=휴가 신청 절차&user_id=employee_hr&top_k=3"
```

기대:

- 휴가 신청 가이드가 상위 결과에 나온다.
- 결과에 `document_id`, `chunk_id`, `snippet`, `source_ref`가 포함된다.

### 4. 권한 경계

```powershell
Invoke-RestMethod "http://127.0.0.1:8010/api/v1/search?q=장애 대응 온콜&user_id=employee_hr&top_k=3"
```

기대:

- `employee_hr`에게 engineering 전용 온콜 문서는 반환되지 않는다.

### 5. Agent Tool

```powershell
$body = @{
  query = "문서 권한 필터는 어떻게 적용해야 해?"
  user_id = "employee_hr"
  top_k = 3
  filters = @{}
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8010/api/v1/agent/tools/document-search" `
  -ContentType "application/json" `
  -Body $body
```

기대:

- `tool_name`은 `search_documents`
- `evidence_packets`만 반환
- 최종 답변 정확도 claim은 하지 않음

## Claim Boundary

이 mock E2E는 다음만 검증한다.

```text
mock corpus 기준 검색 API 응답 형식
mock corpus 기준 권한 필터 동작
Agent tool evidence packet 계약
```

다음은 주장하지 않는다.

```text
실제 PostgreSQL migration 적용 완료
실제 Qdrant 서버 성능 검증 완료
실사용 사내 데이터 검색 성공
production 운영 성공
```
