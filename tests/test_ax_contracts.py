from locallens.ax.mock_corpus import MOCK_DOCUMENTS
from locallens.ax.hybrid import RetrievalCandidate
from locallens.ax.hybrid import fuse_candidates
from locallens.ax.metadata import _token_overlap_score
from locallens.ax.qdrant_contract import build_qdrant_payload
from locallens.ax.qdrant_contract import validate_qdrant_payload
from locallens.ax.qdrant_store import QdrantVectorStore
from locallens.ax.qdrant_store import build_qdrant_filter
from locallens.ax.qdrant_store import point_id_for_chunk


class FakeQdrantClient:
    def __init__(self):
        self.upsert_call = None
        self.query_call = None

    def upsert(self, **kwargs):
        self.upsert_call = kwargs

    def query_points(self, **kwargs):
        self.query_call = kwargs
        return []


def test_qdrant_payload_contract_contains_acl_and_source_keys():
    document = MOCK_DOCUMENTS[0]
    chunk = document["chunks"][0]

    payload = build_qdrant_payload(document, chunk)

    assert validate_qdrant_payload(payload) == []
    assert payload["document_id"] == document["document_id"]
    assert payload["chunk_id"] == chunk["chunk_id"]
    assert payload["acl_tags"]
    assert payload["snippet"]


def test_qdrant_payload_contract_rejects_missing_acl_tags():
    payload = build_qdrant_payload(MOCK_DOCUMENTS[0], MOCK_DOCUMENTS[0]["chunks"][0])
    payload.pop("acl_tags")

    errors = validate_qdrant_payload(payload)

    assert "acl_tags" in errors


def test_qdrant_point_id_is_stable_uuid():
    point_id = point_id_for_chunk("chunk_hr_leave_001")

    assert point_id == point_id_for_chunk("chunk_hr_leave_001")
    assert len(point_id) == 36


def test_qdrant_store_upserts_payload_contract_points():
    client = FakeQdrantClient()
    store = QdrantVectorStore(client, collection_name="test_chunks")
    document = MOCK_DOCUMENTS[0]
    vectors = {
        chunk["chunk_id"]: [0.1, 0.2, 0.3]
        for chunk in document["chunks"]
    }

    result = store.upsert_documents([document], vectors_by_chunk_id=vectors)

    assert result["upserted"] == 2
    assert client.upsert_call["collection_name"] == "test_chunks"
    assert len(client.upsert_call["points"]) == 2
    first_payload = client.upsert_call["points"][0].payload
    assert validate_qdrant_payload(first_payload) == []
    assert first_payload["document_id"] == "doc_hr_leave_policy"


def test_qdrant_search_builds_acl_and_metadata_filter():
    client = FakeQdrantClient()
    store = QdrantVectorStore(client, collection_name="test_chunks")

    results = store.search(
        query_vector=[0.1, 0.2, 0.3],
        acl_tags=["all_employee", "hr"],
        top_k=3,
        filters={"department_id": "hr", "document_type": "pdf"},
    )

    assert results == []
    assert client.query_call["collection_name"] == "test_chunks"
    assert client.query_call["limit"] == 3
    query_filter = client.query_call["query_filter"]
    dumped = query_filter.model_dump()
    assert any(item["key"] == "acl_tags" for item in dumped["must"])
    assert any(item["key"] == "department_id" for item in dumped["must"])
    assert any(item["key"] == "document_type" for item in dumped["must"])


def test_qdrant_filter_can_be_constructed_without_optional_filters():
    query_filter = build_qdrant_filter(acl_tags=["engineering"])

    dumped = query_filter.model_dump()
    assert dumped["must"][0]["key"] == "acl_tags"


def test_hybrid_fusion_boosts_overlap_between_keyword_and_semantic():
    keyword = RetrievalCandidate(
        document_id="doc_1",
        chunk_id="chunk_1",
        title="휴가 신청 가이드",
        snippet="연차 신청 절차",
        source_ref="doc_1#chunk=chunk_1",
        page=1,
        modality="pdf_text",
        department_id="hr",
        document_type="pdf",
        score=0.8,
        keyword_score=0.8,
        match_type="keyword",
    )
    semantic = RetrievalCandidate(
        document_id="doc_1",
        chunk_id="chunk_1",
        title="휴가 신청 가이드",
        snippet="연차 신청 절차",
        source_ref="doc_1#chunk=chunk_1",
        page=1,
        modality="pdf_text",
        department_id="hr",
        document_type="pdf",
        score=0.7,
        semantic_score=0.7,
        match_type="semantic",
    )

    fused = fuse_candidates([keyword], [semantic], top_k=1)

    assert fused[0].match_type == "hybrid"
    assert fused[0].keyword_score > 0
    assert fused[0].semantic_score > 0


def test_korean_keyword_overlap_scores_partial_terms():
    score = _token_overlap_score(
        "휴가 신청 절차",
        "휴가 신청 가이드",
        "연차와 반차는 사내 포털의 근태 메뉴에서 신청합니다.",
    )

    assert score > 0
