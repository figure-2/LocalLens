# LocalLens AX Hybrid Retrieval

## 목적

`AX-RET-002`는 PostgreSQL keyword search와 Qdrant semantic search 결과를 하나의 evidence packet 순위로 결합한다.

## 검색 흐름

```text
사용자 질문
-> PostgreSQL keyword search
-> Qdrant semantic search
-> document_id + chunk_id 기준 normalize
-> keyword/semantic score 정규화
-> overlap bonus 적용
-> EvidencePacket 반환
```

## Backend 전환

기본값은 기존 mock 검색이다.

```powershell
$env:LOCALLENS_AX_RETRIEVAL_BACKEND = "mock"
```

hybrid 검색 경로:

```powershell
$env:LOCALLENS_AX_RETRIEVAL_BACKEND = "hybrid"
```

## Docker local services

```powershell
docker compose -f docker-compose.ax.yml up -d
```

PostgreSQL local DSN:

```powershell
$env:LOCALLENS_AX_METADATA_BACKEND = "postgres"
$env:LOCALLENS_AX_DATABASE_URL = "postgresql://locallens:locallens_local_only@127.0.0.1:54329/locallens_ax"
```

위 DSN은 Docker local smoke용 고정 계정이다. 실제 운영 credential이 아니며 공개 claim에는 "local smoke용 mock DB"로만 설명한다.

Qdrant local URL:

```powershell
$env:LOCALLENS_AX_QDRANT_URL = "http://127.0.0.1:6333"
```

## Fusion 기준

- keyword score weight: 0.55
- semantic score weight: 0.45
- 양쪽 모두에서 잡힌 chunk는 overlap bonus 0.10
- key는 `document_id + chunk_id`

## 한국어 keyword 보강

PostgreSQL `simple` full-text search는 한국어 문장을 형태소 단위로 분해하지 못한다. 따라서 `AX-RET-003`에서는 PostgreSQL이 권한 필터와 후보 chunk 조회를 담당하고, 앱 계층에서 질의 토큰과 제목/본문 preview의 부분 일치 overlap을 계산한다.

예시:

```text
query: 휴가 신청 절차
title/snippet: 휴가 신청 가이드, 연차와 반차는 ... 신청합니다
matched terms: 휴가, 신청
```

이 방식은 mock/local smoke용 보강이다. 운영 수준의 한국어 검색은 trigram, 한국어 형태소 분석, 별도 keyword column, 또는 검색 엔진 연동을 추가 검토해야 한다.

## Chunk ranking 보강

`휴가 신청 절차`처럼 짧은 한국어 질의에서는 같은 문서 안의 여러 chunk가 동시에 후보가 될 수 있다. 문서 단위 hit는 맞더라도, chunk 순위는 제목 일치와 본문 preview 일치를 분리해 가중치를 준다.

현재 local smoke 기준:

- 제목 일치: 작은 보너스
- 본문 preview 일치: 더 큰 보너스
- `신청`, `작성`, `대응`, `조치`, `기록`, `확인` 같은 행위 의도가 본문에 직접 있으면 보너스
- `절차`, `순서` 질의에서 `신청합니다`, `먼저`, `단계`, `메뉴` 같은 진행 단서가 있으면 보너스
- keyword와 semantic 양쪽에서 잡힌 chunk: hybrid overlap 보너스

이 보강은 시연 안정성을 위한 1차 ranking 보정이다. 운영 수준 정밀도는 query rewriting, BM25/trigram, 한국어 형태소 분석, 또는 cross-encoder reranker를 별도 단계로 검토한다.

## Fallback

Qdrant search가 비어 있거나 실패하면 keyword search 결과만으로 응답한다.

이 fallback은 시연 안정성을 위한 장치이며, 실제 Qdrant 검색 품질 검증을 대체하지 않는다.

## Claim Boundary

현재 주장 가능한 범위:

- PostgreSQL keyword search adapter 추가
- Qdrant semantic search 결과 normalize 경로 추가
- keyword/semantic 결과 fusion 로직 추가
- Qdrant 실패 시 keyword fallback 유지

아직 주장하면 안 되는 범위:

- 실제 PostgreSQL + Qdrant 운영 성능 검증 완료
- 실제 embedding 모델 검색 품질 검증 완료
- 실사용 검색 정확도 보장
- 사내 실데이터 기반 benchmark 완료
