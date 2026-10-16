from __future__ import annotations

import math
import re


def deterministic_text_vector(text: str, *, size: int = 8) -> list[float]:
    """Build a deterministic local feature vector for mock smoke tests.

    This is not an embedding quality claim. It maps AX demo keywords onto fixed
    dimensions so the Qdrant path can run without paid or external embedding APIs.
    """

    dimensions = [
        {"휴가", "연차", "반차", "병가", "근태", "승인", "신청"},
        {"장애", "온콜", "에러", "지연", "대시보드", "재발"},
        {"고객", "제안", "제안서", "영업", "비용", "도입"},
        {"보안", "권한", "기밀", "접근", "제한", "필터"},
        {"ax", "자동화", "문서검색", "지식", "반복"},
        {"문서", "검색", "파일", "결과", "후보"},
        {"보고서", "원인", "조치", "템플릿", "정책"},
        {"절차", "흐름", "기준", "가이드", "작성"},
    ]
    terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z0-9가-힣]+", text)
        if len(term) >= 2
    }
    values = []
    for index in range(size):
        group = dimensions[index % len(dimensions)]
        values.append(float(len(terms & {term.lower() for term in group})))
    if not any(values):
        values = [0.01 for _ in range(size)]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]
