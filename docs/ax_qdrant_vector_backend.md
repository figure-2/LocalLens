# LocalLens AX Qdrant Vector Backend

## 목적

`AX-VDB-002`는 기존 `qdrant_contract`를 실제 Qdrant upsert/search adapter에 연결한다.

이 단계는 Qdrant를 최종 검색 ranking 전체로 교체하지 않는다. Qdrant는 chunk embedding과 payload filter를 담당하고, PostgreSQL keyword search와의 결합은 `AX-RET-002`에서 진행한다.

## 책임 범위

- chunk payload contract 생성
- payload contract 검증
- chunk id를 Qdrant point id로 안정적으로 변환
- 문서 chunk embedding upsert
- 사용자 ACL과 metadata filter를 Qdrant query filter로 변환
- Qdrant search hit을 내부 `QdrantSearchHit` 형식으로 normalize

## 실행 모드

서버 Qdrant:

```powershell
$env:LOCALLENS_AX_QDRANT_URL = "http://localhost:6333"
$env:LOCALLENS_AX_QDRANT_COLLECTION = "locallens_ax_chunks"
```

Qdrant Cloud:

```powershell
$env:LOCALLENS_AX_QDRANT_URL = "https://example.cloud.qdrant.io:6333"
$env:LOCALLENS_AX_QDRANT_API_KEY = "<redacted>"
```

로컬 persistent mode:

```powershell
$env:LOCALLENS_AX_QDRANT_PATH = ".\\.local\\qdrant"
```

환경변수가 없으면 local smoke test용 in-memory Qdrant를 사용한다.

## Payload 핵심 필드

```text
document_id
chunk_id
version_id
page
modality
department_id
acl_tags
document_type
title
snippet
```

## 검색 경계

Qdrant query filter는 최소한 `acl_tags`를 포함한다.

선택 필터:

```text
department_id
document_type
document_id
```

## Claim Boundary

현재 주장 가능한 범위:

- Qdrant upsert/search adapter 추가
- payload contract 기반 point 생성 흐름 추가
- ACL/metadata filter 생성 흐름 추가
- fake client 기반 adapter contract test 추가

아직 주장하면 안 되는 범위:

- 실제 Qdrant 서버 성능 검증 완료
- 실제 embedding 모델 기반 검색 품질 검증 완료
- PostgreSQL keyword search와 semantic search fusion 완료
- 실사용 검색 정확도 보장
