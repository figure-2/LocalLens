from __future__ import annotations

import re


KOCR_QUERY_NORMALIZATION_OFF = "off"
KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL = "alias-backfill"

KOREAN_TO_ENGLISH_ALIAS = {
    "로컬": "local",
    "검색": "search",
    "승인": "approval",
    "문서": "document",
    "보관함": "archive",
    "이십칠": "27",
    "재고": "inventory",
    "선반": "shelf",
    "파랑": "blue",
    "수량": "count",
    "사십이": "42",
    "긴급": "urgent",
    "점검": "inspection",
    "안내": "notice",
    "서버실": "server-room",
    "출입": "access",
    "제한": "restricted",
    "영수증": "receipt",
    "총액": "total",
    "확인": "verify",
    "금액": "amount",
    "십팔만": "180000",
    "원": "won",
    "라벨": "label",
    "회전": "rotated",
    "보관": "storage",
    "위치": "location",
    "삼층": "third-floor",
    "완료": "complete",
    "회의실": "meeting-room",
    "예약": "reservation",
    "변경": "change",
    "오후": "afternoon",
    "세시": "3pm",
    "동관": "east-wing",
    "배송": "delivery",
    "상자": "box",
    "번호": "number",
    "칠십삼": "73",
    "일정": "schedule",
    "수요일": "wednesday",
    "오전": "morning",
    "열시": "10am",
    "보안": "security",
    "예산": "budget",
    "대기": "pending",
    "검토": "review",
    "구십일": "91",
    "청구서": "invoice",
    "코드": "code",
    "팔오이": "852",
    "자산": "asset",
    "랙": "rack",
    "서쪽": "west",
    "둘": "2",
    "지원": "support",
    "티켓": "ticket",
    "접수": "received",
    "정책": "policy",
    "알림": "alert",
    "버전": "version",
    "이점삼": "2.3",
    "장비": "equipment",
    "온도": "temperature",
    "경고": "warning",
    "센서": "sensor",
    "십육": "16",
    "출고": "shipping",
    "명세": "manifest",
    "팔레트": "pallet",
    "칠": "7",
    "번": "number",
    "회의": "meeting",
    "자료": "materials",
    "폴더": "folder",
    "삼십": "30",
    "감사": "audit",
    "로그": "log",
    "백업": "backup",
    "작업": "job",
    "성공": "success",
    "새벽": "dawn",
    "두시": "2am",
    "접근": "access",
    "요청": "request",
    "대기중": "waiting",
    "장치": "device",
    "동쪽": "east",
    "여섯": "6",
    "운영": "operations",
    "노트": "note",
    "복구": "restore",
    "식별자": "identifier",
    "구역": "zone",
    "남쪽": "south",
    "넷": "4",
}
ENGLISH_TO_KOREAN_ALIAS = {
    value: key for key, value in KOREAN_TO_ENGLISH_ALIAS.items()
}


def normalize_korean_ocr_query(query: str, mode: str = KOCR_QUERY_NORMALIZATION_OFF) -> str:
    if mode == KOCR_QUERY_NORMALIZATION_OFF:
        return query
    if mode != KOCR_QUERY_NORMALIZATION_ALIAS_BACKFILL:
        raise ValueError("Unsupported KOCR query normalization mode")
    additions = [
        ENGLISH_TO_KOREAN_ALIAS[part.lower()]
        for part in re.findall(r"[A-Za-z0-9.-]+", query)
        if part.lower() in ENGLISH_TO_KOREAN_ALIAS
    ]
    if not additions:
        return query
    return f"{query} {' '.join(_unique(additions))}"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
