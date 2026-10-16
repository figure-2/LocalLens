# LocalLens AX Mock E2E 사용자 시나리오

## 1. 시나리오 목적

이 문서는 `LocalLens AX`를 실제 사내 문서 탐색 AX 서비스처럼 시연하기 위한 mock E2E 기준서다.

유료 API, 실제 사내 문서, 실제 임직원 계정은 사용하지 않는다.

검증 대상은 다음이다.

```text
문서 검색 UX
권한 기반 검색 결과 제한
근거 snippet / source_ref 표시
Agent tool evidence packet 반환
검색 피드백 수집 흐름
```

## 2. 시연 배경

가상의 회사 `Acme AX Lab`에는 여러 부서 문서가 흩어져 있다.

임직원은 파일명이나 폴더 경로를 모르는 상태에서 자연어로 문서를 찾고 싶다.

문서에는 공통 문서, HR 문서, Engineering 문서, Sales 문서가 있다.

사용자는 본인 권한 범위 안의 문서만 검색할 수 있어야 한다.

## 3. 사용자 페르소나

| 사용자 | user_id | 권한 | 목적 |
|---|---|---|---|
| HR 담당자 | `employee_hr` | `all_employee`, `hr` | 휴가/근태/보안 정책 검색 |
| 엔지니어 | `employee_eng` | `all_employee`, `engineering` | 장애 대응 runbook 검색 |
| 세일즈 담당자 | `employee_sales` | `all_employee`, `sales` | 제안서/AX 가치 문서 검색 |

## 4. Mock 문서 구성

| 문서 | 권한 | 핵심 내용 |
|---|---|---|
| 휴가 신청 가이드 | `all_employee`, `hr` | 연차, 반차, 병가 신청 절차 |
| 장애 대응 온콜 Runbook | `engineering` | 장애 알림, 대시보드 점검, 사후 보고 |
| 고객 제안서 작성 템플릿 | `sales` | 문제 정의, 기대 효과, AX 가치 설명 |
| 사내 문서 보안 기본 정책 | `all_employee` | 문서 등급, 권한 필터, 접근 통제 |

## 5. 전체 시연 흐름

```text
1. HR 담당자로 접속
2. 문서 목록 확인
3. "휴가 신청 절차" 검색
4. 휴가 신청 가이드 결과와 source_ref 확인
5. "장애 대응 온콜" 검색
6. engineering 전용 문서가 보이지 않는지 확인
7. "문서 권한 필터" 검색
8. 사내 문서 보안 정책 결과 확인
9. Agent tool로 같은 질문 호출
10. 최종 답변이 아니라 evidence packet만 반환되는지 확인
11. 검색 결과 피드백 제출
```

## 6. 상세 테스트 질문

### Q1. 정상 검색

```text
휴가 신청 절차
```

기대:

```text
휴가 신청 가이드가 상위 결과로 나온다.
snippet에 연차, 반차, 근태, 승인 흐름이 포함된다.
source_ref에 document_id, page, chunk_id가 포함된다.
```

### Q2. 권한 차단 검색

```text
장애 대응 온콜
```

사용자:

```text
employee_hr
```

기대:

```text
doc_eng_oncall_runbook이 결과에 나오면 안 된다.
권한 없는 engineering 문서가 노출되지 않는다.
```

### Q3. 공통 보안 문서 검색

```text
문서 권한 필터는 어떻게 적용해야 해?
```

기대:

```text
사내 문서 보안 기본 정책이 검색된다.
snippet에 권한, 필터링, 접근 가능 여부 재확인 내용이 포함된다.
```

### Q4. Sales 문서 검색

```text
AX 제안서에는 어떤 가치를 넣어야 해?
```

사용자:

```text
employee_sales
```

기대:

```text
고객 제안서 작성 템플릿이 검색된다.
반복 업무 절감, 문서 검색 시간 단축, 지식 접근성 향상 내용이 나온다.
```

### Q5. Agent tool 호출

```text
문서 권한 필터는 어떻게 적용해야 해?
```

기대:

```text
tool_name은 search_documents다.
evidence_packets가 반환된다.
최종 답변 correctness는 주장하지 않는다.
```

## 7. 성공 기준

| 항목 | 기준 |
|---|---|
| API Health | `/api/v1/health`가 `ok` 반환 |
| 문서 목록 | 사용자 권한에 맞는 문서만 반환 |
| 검색 결과 | query, document_id, chunk_id, snippet, source_ref 포함 |
| 권한 경계 | HR 사용자가 engineering 전용 문서를 볼 수 없음 |
| Agent tool | evidence packet만 반환 |
| 피드백 | rating, document_id, chunk_id를 mock accepted 처리 |

## 8. 실패 기준

다음 중 하나라도 발생하면 baseline 실패다.

```text
권한 없는 문서가 검색 결과에 노출됨
검색 결과에 source_ref가 없음
Agent tool이 evidence packet이 아닌 최종 답변을 생성함
health endpoint 실패
프론트에서 검색 요청을 보낼 수 없음
```

## 9. Claim Boundary

이 시나리오로 주장 가능한 것:

```text
mock dataset 기준 사내 문서 검색 AX 흐름을 시연할 수 있다.
mock 권한 기준 검색 결과 제한 흐름을 확인할 수 있다.
Agent tool이 evidence packet을 반환하는 구조를 확인할 수 있다.
```

이 시나리오로 주장하면 안 되는 것:

```text
실제 사내 문서 검색 성공
실제 임직원 권한 시스템 연동 완료
production 운영 성공
실사용 검색 정확도 보장
권한 누출 완전 방지
```

