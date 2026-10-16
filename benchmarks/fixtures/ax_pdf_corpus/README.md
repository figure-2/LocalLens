# LocalLens AX mock PDF corpus

이 폴더는 AX 문서 검색 시나리오를 설명하기 위한 공개용 mock PDF corpus입니다.

- 실제 회사 문서, 개인정보, 내부자료를 포함하지 않습니다.
- `sql/002_ax_mock_seed.sql`의 mock document/chunk 내용과 대응됩니다.
- `mock_source_pdf`는 seed의 document_type이 `pdf`인 문서입니다.
- `mock_export_preview_pdf`는 markdown/pptx seed 문서를 PDF로 내보낸 시연용 preview입니다. 원본 타입을 PDF로 주장하지 않습니다.
- local smoke의 검색 검증은 PostgreSQL/Qdrant seed를 기준으로 수행되며, 이 PDF들은 공개 시연과 문서 이해를 위한 보조 자료입니다.
