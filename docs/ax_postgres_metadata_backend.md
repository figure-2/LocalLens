# LocalLens AX PostgreSQL Metadata Backend

## 목적

`AX-DB-002`는 mock metadata repository를 실제 PostgreSQL repository로 교체할 수 있는 실행 경로를 추가한다.

기본 실행은 여전히 mock E2E를 사용한다. 실제 PostgreSQL을 사용할 때만 환경변수로 backend를 전환한다.

## 실행 모드

```powershell
$env:LOCALLENS_AX_METADATA_BACKEND = "mock"
```

```powershell
$env:LOCALLENS_AX_METADATA_BACKEND = "postgres"
$env:LOCALLENS_AX_DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DBNAME"
```

`LOCALLENS_AX_DATABASE_URL`은 AX local smoke 전용 연결 문자열이다. 공개 repo에서는 실제 DB URL을 커밋하지 않고, `.env.example` 또는 문서에는 placeholder만 둔다. 구현도 의도치 않은 전역 `DATABASE_URL` 사용을 피하기 위해 AX 전용 환경 변수만 읽는다.

## PostgreSQL 책임 범위

- 사용자, 부서, 문서, 문서 버전 metadata
- 문서별 접근 정책
- 문서 chunk metadata와 Qdrant point 연결값
- 검색 로그
- 사용자 피드백

## 로컬 smoke seed

스키마와 mock seed는 아래 순서로 적용한다.

```powershell
psql $env:LOCALLENS_AX_DATABASE_URL -f .\sql\001_ax_postgres_schema.sql
psql $env:LOCALLENS_AX_DATABASE_URL -f .\sql\002_ax_mock_seed.sql
```

`002_ax_mock_seed.sql`은 실제 회사 데이터가 아니라 mock E2E와 같은 시나리오 데이터를 PostgreSQL 형태로 적재하기 위한 파일이다.

## Qdrant와의 경계

PostgreSQL은 vector search를 수행하지 않는다. Qdrant는 chunk embedding과 payload filter를 담당한다.

`AX-DB-002`는 PostgreSQL metadata 계층만 연결한다. PostgreSQL keyword search와 Qdrant semantic search fusion은 `AX-RET-002` 범위다.

## Claim Boundary

현재 주장 가능한 범위:

- PostgreSQL metadata repository 연결 경로 추가
- 환경변수 기반 mock/postgres backend 전환 구조 추가
- 검색 로그와 피드백을 PostgreSQL에 기록할 수 있는 adapter 추가

아직 주장하면 안 되는 범위:

- 실제 사내 문서 DB 운영 성공
- 실제 PostgreSQL 배포 검증 완료
- 실제 Qdrant 검색 성능 검증 완료
- 실사용 검색 정확도 보장
