# LocalLens DB/VDB 업그레이드 아키텍처

## 결론

LocalLens의 기본 정체성은 로컬 텍스트, 이미지, PDF를 자연어로 찾는 멀티모달 파일 검색기다.

이번 업그레이드는 프로젝트를 AX 전용 검색기로 바꾸는 것이 아니라, 원본 LocalLens의 검색 흐름을 유지하면서 저장소와 검색 계층을 포트폴리오용으로 확장하는 작업이다.

## 담당 관점 회의 결론

| 관점 | 판단 |
|---|---|
| 제품 | 기본 시나리오는 문서 찾기와 이미지 찾기다. AX Workspace는 확장 모드로 둔다. |
| 백엔드 | SQLite manifest만으로 설명하면 MVP처럼 보일 수 있으므로 PostgreSQL 메타데이터 계층을 추가한다. |
| 검색 | FAISS 기반 로컬 벡터 검색의 장점은 유지하되, 공개 데모에서는 Qdrant payload filter와 검색 API를 보여준다. |
| 데이터 | PostgreSQL은 파일, 문서, 권한, 청크, 검색 로그를 관리하고 Qdrant는 벡터와 payload 검색을 담당한다. |
| Agent | 검색 결과는 Agent가 바로 사용할 수 있는 evidence packet으로 정규화한다. |
| 리스크 | mock 데이터 기준 시연이므로 실제 사내 문서 검색, 운영 정확도 향상, production 성공은 주장하지 않는다. |

## 전후 구조

| 구분 | 기존 LocalLens | 업그레이드 LocalLens |
|---|---|---|
| 메타데이터 | SQLite manifest | PostgreSQL metadata repository |
| 벡터 검색 | FAISS 중심 로컬 인덱스 | Qdrant collection + payload filter |
| 검색 방식 | semantic search 중심 | keyword + semantic hybrid retrieval |
| 입력 | 텍스트, 이미지, PDF | 텍스트, 이미지, PDF, AX workspace 문서 |
| UI | 로컬 탐색기 중심 | Local Files / Image Search / AX Workspace 모드 |
| Agent 연동 | 없음 또는 약함 | evidence packet 기반 tool contract |

## PostgreSQL 역할

PostgreSQL은 파일 검색의 상태와 관계형 정보를 담당한다.

| 테이블/개념 | 역할 |
|---|---|
| documents | 파일 또는 문서 단위 메타데이터 관리 |
| document_versions | 버전, 해시, 경로, 원본 타입 관리 |
| document_chunks | 검색 가능한 텍스트, PDF, 이미지 caption 청크 관리 |
| access_policies | 사용자/조직/태그 기반 접근 범위 관리 |
| search_logs | 검색 질의와 결과 추적 |
| feedback | 검색 결과 피드백 기록 |

## Qdrant 역할

Qdrant는 벡터 검색과 payload 기반 필터링을 담당한다.

| payload | 의미 |
|---|---|
| document_id | 원본 파일 또는 문서 ID |
| chunk_id | 검색 단위 ID |
| source_ref | 파일 경로, 페이지, 청크를 추적하는 근거 참조 |
| modality | text, pdf_text, image, slide_text 등 입력 유형 |
| department_id | AX Workspace 확장 모드용 조직 범위 |
| acl_tags | 접근 제어 태그 |

## 시연 모드

### 1. 문서 검색

사용자가 자연어로 문서 내용을 설명하면 관련 텍스트/PDF 문서를 찾는다.

예시 질의:

```text
Qdrant 도입 이유가 적힌 문서
```

### 2. 이미지 검색

사용자가 이미지 내용을 설명하면 caption/vector 기반으로 관련 이미지를 찾는다.

예시 질의:

```text
아키텍처 다이어그램 이미지
```

### 3. AX Workspace 확장

팀/회사 폴더 문서 검색, 권한 필터, Agent evidence packet을 보여주는 확장 시나리오다.

예시 질의:

```text
휴가 신청 절차
```

## Claim Boundary

쓸 수 있는 표현:

- PostgreSQL metadata와 Qdrant vector store를 연결한 mock/local smoke 기준 검색 흐름을 구성했다.
- 문서, PDF, 이미지 caption을 modality별 evidence packet으로 정규화했다.
- AX Workspace 확장 모드에서 권한 필터와 Agent tool contract를 mock 데이터 기준으로 검증했다.

피해야 할 표현:

- 실제 사내 문서 검색 정확도를 검증했다.
- 이미지 검색 성능이 향상되었다.
- production 운영에 성공했다.
- 모든 로컬 파일 형식을 완전 지원한다.
