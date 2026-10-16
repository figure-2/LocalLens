# LocalLens VLM Provider Adapter

## 결정

기존 프로젝트의 이미지, 표, 그래프 설명 생성 흐름은 유지한다. 다만 provider를 고정하지 않고 `mock-vlm`, `local-vlm`, `clova-studio` 모드로 분리한다.

## 구현 관점

| 담당 관점     | 결정                                                                           |
| ------------- | ------------------------------------------------------------------------------ |
| 멀티모달 추출 | PDF 내부 이미지 후보를 `pdf_visual_caption` unit으로 만들어 검색 인덱스에 연결 |
| 백엔드 어댑터 | Clova Studio는 OpenAI-compatible chat completions payload로 호출               |
| 검증          | 유료 API 없이 `mock-vlm`과 payload 단위 테스트로 smoke 가능                    |
| Claim 경계    | mock/local smoke와 Clova 실호출 검증을 분리해서 기록                           |

## 모드

| Mode           | 설명                                           | 사용 시점                 |
| -------------- | ---------------------------------------------- | ------------------------- |
| `off`          | PDF 텍스트/표 중심 추출                        | 기본값                    |
| `mock-vlm`     | 외부 API 없이 caption unit 흐름 확인           | 로컬 시연, 테스트         |
| `local-vlm`    | 로컬 Hugging Face VLM 후보 사용                | GPU/모델 캐시가 있는 환경 |
| `clova-studio` | 기존 PDF 처리 경로와 호환되는 Clova Studio VLM 계열 provider | API key가 있는 환경       |

## 안전한 표현

- PDF 이미지/표/그래프 설명 생성을 위한 VLM provider adapter를 분리했다.
- mock/local smoke에서는 외부 API 없이 caption unit 생성 흐름을 검증했다.
- Clova Studio 경로는 OpenAI-compatible payload로 연결 가능하도록 구현했다.

## 위험한 표현

- Clova Studio 실호출까지 통과했다.
- 유료 API 환경에서 성능을 검증했다.
- PDF 이미지 검색 정확도가 개선됐다.

위 표현은 실제 Clova credentials 기반 실행 결과와 별도 평가셋이 있을 때만 사용할 수 있다.
