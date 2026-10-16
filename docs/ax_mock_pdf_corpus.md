# LocalLens AX mock PDF corpus

## 목적

AX 문서 검색 시나리오를 처음 보는 사람이 실제 문서 흐름을 이해할 수 있도록 `sql/002_ax_mock_seed.sql`의 mock chunk 내용과 대응되는 PDF 파일을 제공한다.

## 위치

```text
benchmarks/fixtures/ax_pdf_corpus/
```

## 포함 파일

| 파일 | document_id | seed 문서 타입 | 용도 |
|---|---|---|---|
| `doc_hr_leave_policy_v1.pdf` | `doc_hr_leave_policy` | `pdf` | mock source PDF |
| `doc_all_security_policy_v1.pdf` | `doc_all_security_policy` | `pdf` | mock source PDF |
| `doc_eng_oncall_runbook_v3_export_preview.pdf` | `doc_eng_oncall_runbook` | `markdown` | PDF export preview |
| `doc_sales_proposal_template_v2_export_preview.pdf` | `doc_sales_proposal_template` | `pptx` | PDF export preview |

## Claim boundary

- 이 파일들은 실제 회사 문서가 아니다.
- 이 파일들은 개인정보나 비공개 내부자료를 포함하지 않는다.
- local smoke 검증은 PostgreSQL/Qdrant seed data 기준으로 수행된다.
- PDF corpus는 시연과 문서 이해를 위한 보조 자료다.
- `markdown`, `pptx` seed 문서의 PDF는 원본 타입을 바꾼 것이 아니라 설명용 export preview다.

