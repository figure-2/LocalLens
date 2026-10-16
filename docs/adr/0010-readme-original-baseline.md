# ADR 0010: README original-baseline cleanup

날짜: 2026-06-15

## 상태

Accepted

## 배경

LL-GIT 단계에서 README가 원본 LocalLens 설명 위에 업그레이드 세부 내용이 과하게 추가된 상태였다. GitHub 공개 repo 첫 화면은 프로젝트 정체성과 실행 방법을 빠르게 전달해야 하므로, 원본 README 구조를 기준으로 유지하고 업그레이드로 바뀐 기술스택, 라이브러리, 아키텍처만 짧게 반영하기로 했다.

## 결정

README는 원본 LocalLens README의 큰 구조를 유지한다.

유지한 원본 구조:

- `What It Does`
- `Quick Start`
- `Commands`
- `Storage`
- `Privacy Boundary`
- `Benchmark Fields`
- `Release Gate`
- `Embedding Backends`

추가/수정한 부분:

- 상단 demo screenshot
- `Upgrade Summary` 표
- 아키텍처 mermaid diagram
- FastAPI/React real demo quick start
- PostgreSQL/Qdrant AX extension 설명
- PDF VLM provider mode 설명
- release evidence 링크

## 제외한 표현

- production 운영 성공
- 실제 회사 문서 검증
- 실제 데이터 benchmark 성공
- local VLM이 Clova Studio보다 우수하다는 성능 주장

## 검증

README 수정 후 다음을 확인했다.

- README 내부 이미지 경로 존재
- README 상대 문서 링크 누락 없음
- `git diff --check` 오류 없음
- `scripts/ll_real_demo_e2e.ps1` 통과
- `npm --prefix frontend run build` 통과
- `npm --prefix frontend audit --audit-level=moderate` 취약점 0개

