# LocalLens 기존 버전과 AX 개선 버전 비교 보고서

## 요약

AX 개선 버전은 기존 로컬 멀티모달 파일 검색 흐름을 유지하면서 저장소, 검색 품질, API·UI, 검증 체계를 확장한다.

## 기능 비교

| 영역 | 기존 버전 | AX 개선 버전 |
|---|---|---|
| 사용자 흐름 | 로컬 폴더 선택과 데스크톱 검색 | Tkinter 흐름 유지 + FastAPI·React 데모 |
| 메타데이터 | 로컬 저장 중심 | PostgreSQL 및 manifest 기반 관리 |
| 벡터 검색 | 기본 벡터 검색 | Qdrant contract와 type-aware collection |
| 질의 처리 | 기본 semantic 검색 | hybrid retrieval, 정규화, rerank |
| PDF | 텍스트·이미지 처리 | OCR 표 구조, caption adapter, 캐시 재사용 |
| 검증 | 기능 단위 테스트와 smoke | benchmark, evidence consistency, release gate |

## 개선의 의미

AX 버전의 핵심 개선은 단순한 저장소 교체가 아니라 검색 경로를 교체 가능한 계층으로 분리하고, 질의·추출·저장·검증 결과를 재현할 수 있게 만든 것이다.

## 제한 사항

- benchmark 결과는 fixture와 정의된 평가 범위에 한정한다.
- mock provider 통과를 외부 모델 실호출 성공으로 표현하지 않는다.
- 운영 환경의 정확도·지연시간·장애율 개선은 별도 실험이 필요하다.
