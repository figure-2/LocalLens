from locallens.ax.metadata import _token_overlap_score


def test_action_intent_chunk_ranks_above_related_procedure_chunk():
    query = "휴가 신청 절차"
    title = "휴가 신청 가이드"
    direct_application_chunk = (
        "연차와 반차는 사내 포털의 근태 메뉴에서 신청합니다. "
        "팀장 승인 후 인사팀 검토가 완료되면 휴가 일정이 확정됩니다."
    )
    related_exception_chunk = (
        "병가는 증빙 서류를 첨부해야 하며, 긴급 휴가는 사후 승인 절차를 통해 "
        "처리할 수 있습니다."
    )

    assert _token_overlap_score(query, title, direct_application_chunk) > (
        _token_overlap_score(query, title, related_exception_chunk)
    )
