# LocalLens 기존 구조 기반 데모 구현 보고서

## 목적

이 문서는 기존 버전의 로컬 멀티모달 검색 흐름을 유지하면서 AX 확장 버전에서 실제 데모 경로로 연결한 내용을 정리한다.

## 유지한 핵심 흐름

- 로컬 폴더 스캔과 파일 변경 감지
- 텍스트·이미지·PDF 통합 검색
- 파일 동기화 후 임베딩을 갱신하는 흐름
- Tkinter 기반 로컬 검색 화면
- provider adapter를 통한 PDF 이미지·표·그래프 설명 생성

## 개선한 영역

- PostgreSQL metadata backend
- Qdrant vector backend
- hybrid retrieval과 query normalization
- PDF OCR·표 구조 처리와 재사용 가능한 캐시
- FastAPI 및 React 데모 경로
- benchmark, evidence consistency, release gate

## 검증 범위

현재 문서와 테스트가 확인하는 범위는 로컬 fixture, mock provider, Docker 기반 서비스, smoke/e2e 실행이다. 실제 운영 환경 성능이나 외부 provider의 실호출 성공을 의미하지 않는다.

## 공개 설명 기준

공개 문서에서는 “기존 버전의 로컬 멀티모달 검색 흐름을 유지하면서 저장·검색·검증 계층을 확장했다”고 설명한다. 특정 개인 경로, 이전 저장소명, 교육과정명, 팀 프로젝트 식별자는 공개 문서에 포함하지 않는다.
