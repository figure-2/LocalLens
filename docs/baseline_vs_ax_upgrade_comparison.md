# LocalLens 기존 버전과 AX 개선 버전 A/B 비교

## 비교 기준

두 버전은 로컬 텍스트·이미지·PDF 검색이라는 공통 목적을 갖는다. 비교는 아키텍처와 검증 경로를 기준으로 하며, 성능 우열은 동일 조건의 측정 결과가 있는 경우에만 판단한다.

## 기존 버전의 강점

- 로컬 폴더를 직접 선택하는 단순한 사용자 흐름
- 파일 변경 감지와 필요한 파일만 동기화하는 구조
- 텍스트·이미지·PDF를 한 화면에서 검색하는 데스크톱 경험

## AX 개선 버전의 강점

- PostgreSQL metadata와 Qdrant vector backend 분리
- hybrid retrieval, Korean query normalization, reranking
- PDF OCR·표 구조 처리와 caption provider adapter
- FastAPI·React 데모 및 CLI 경로
- mock, local, external-compatible provider 분리
- benchmark와 release gate를 통한 반복 검증

## 남은 검증 과제

AX 버전이 구조적으로 확장되었더라도 실제 이미지 검색 품질, 운영 데이터의 recall, 외부 provider의 실호출 안정성은 별도 데이터셋과 동일 조건 실험으로 확인해야 한다.

## 공개용 결론

AX 개선 버전은 기존 검색 경험을 유지하면서 저장·검색·검증 계층을 확장한 버전이다. 공개 설명에서는 이 범위를 넘어서 정확도나 운영 안정성의 개선을 단정하지 않는다.
