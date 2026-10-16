# LocalLens AX 공개 repo 보안 체크리스트

## 목적

이 문서는 LocalLens AX Upgrade를 공개 GitHub repo에 올리기 전 확인할 제외 대상, 안전한 claim, 위험 claim을 정리한다.

## 공개 repo에 남기면 안 되는 파일

- `.env`, `.env.local`, `.env.*`
- `.locallens/`, `.local/`
- `*.db`, `*.sqlite`, `*.sqlite3`
- Qdrant local storage: `qdrant_storage/`, `qdrant-storage/`, `qdrant_snapshots/`
- PostgreSQL local volume dump: `postgres-data/`, `postgres_data/`
- build output: `dist/`, `frontend/dist/`
- dependency/cache: `node_modules/`, `frontend/node_modules/`, `.pytest_cache/`, `__pycache__/`
- secret-like artifacts: `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*token*`, `*secret*`, `*password*`, `credentials*`
- local logs: `*.log`

## 코드/문서에 남겨도 되는 것

- mock dataset
- local smoke용 Docker compose
- `.env.example`의 빈 placeholder
- local-only 예시 계정 또는 비밀번호
- `LOCALLENS_AX_DATABASE_URL` 형식의 placeholder
- redacted API key 예시

## 반드시 피할 claim

- production 운영 성공
- 실제 사내 문서 검증 완료
- 실제 기업 데이터 benchmark 통과
- 검색 정확도 향상 보장
- LLM 최종 답변 정확도 보장
- mock answer가 실제 LLM 답변 품질을 증명한다는 표현

## 안전한 claim

- Docker 기반 PostgreSQL/Qdrant local smoke를 mock dataset으로 검증
- 권한 필터, 문서 메타데이터, hybrid retrieval, source reference, evidence packet 흐름을 local smoke로 확인
- Agent tool이 answer-ready context를 만들 수 있는 contract를 구성
- local demo corpus 기준으로 folder sync, text/image/PDF search, local VLM PDF visual caption, local Agent evidence packet 흐름을 `scripts/ll_real_demo_e2e.ps1`로 재현 가능하게 구성

## 공개 전 확인 명령

```powershell
rg -n --hidden --glob '!node_modules/**' --glob '!frontend/node_modules/**' --glob '!dist/**' --glob '!frontend/dist/**' --glob '!.git/**' "(API[_-]?KEY|SECRET|TOKEN|PASSWORD|DATABASE_URL|Bearer |sk-[A-Za-z0-9])" .
cd frontend
npm audit
npm run build
cd ..
.\scripts\ll_real_demo_e2e.ps1
```
