from __future__ import annotations

import io
import hashlib
import json
import os
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
PDF_DIR = ROOT / "fixtures" / "pdf_corpus"
TABLE_GOLDEN = ROOT / "fixtures" / "golden_pdf_table_queries.json"
OCR_GOLDEN = ROOT / "fixtures" / "golden_pdf_ocr_queries.json"
KOREAN_OCR_GOLDEN = ROOT / "fixtures" / "golden_pdf_ocr_korean_queries.json"
SCANNED_TABLE_GOLDEN = ROOT / "fixtures" / "golden_pdf_scanned_table_queries.json"
CACHE_SAFETY_GOLDEN = ROOT / "fixtures" / "golden_pdf_cache_safety_queries.json"
BASE_GOLDEN = ROOT / "fixtures" / "golden_pdf_queries.json"
PDF_CORPUS_MANIFEST = ROOT / "fixtures" / "pdf_corpus_manifest.json"

CORPUS_ID = "pdf-ocrtable-synthetic"
CORPUS_VERSION = "2026-06-02-120"
CORPUS_SCHEMA_VERSION = "pdf-corpus-manifest-v1"
QUERY_SCHEMA_VERSION = "pdf-golden-query-v2"
GENERATOR_VERSION = "generate-pdf-expansion-v2"
SLICE_REGISTRY_VERSION = "pdf-slices-v1"

BASE_PDF_CASES = [
    ("born_digital_notes.pdf", "base_document", ["task:document-retrieval"]),
    ("contract_summary.pdf", "base_document", ["task:document-retrieval"]),
    ("diagram_layout.pdf", "base_visual", ["task:visual-retrieval", "layout:diagram-mixed"]),
    ("invoice_like_table.pdf", "base_table", ["task:table-retrieval", "layout:invoice-like"]),
    ("mixed_language_notes.pdf", "base_document", ["task:document-retrieval", "lang:ko-en"]),
    ("multilingual_visual_notice.pdf", "base_visual", ["task:visual-retrieval", "lang:ko-en"]),
    ("process_flow.pdf", "base_visual", ["task:visual-retrieval", "layout:diagram-mixed"]),
    ("product_diagram.pdf", "base_visual", ["task:visual-retrieval", "layout:diagram-mixed"]),
    ("report_appendix.pdf", "base_document", ["task:document-retrieval"]),
    ("scanned_like_page.pdf", "base_ocr", ["task:ocr", "scan:scanned-like"]),
    ("scanned_receipt_like.pdf", "base_ocr", ["task:ocr", "layout:receipt-like"]),
    ("table_report.pdf", "base_table", ["task:table-retrieval", "layout:simple-grid"]),
]

TABLE_CASES = [
    ("table_budget_review_01.pdf", "budget review", "owner", "variance", "finance"),
    ("table_rollout_plan_02.pdf", "rollout plan", "stage", "status", "delivery"),
    ("table_quality_audit_03.pdf", "quality audit", "check", "result", "qa"),
    ("table_support_queue_04.pdf", "support queue", "priority", "agent", "support"),
    ("table_inventory_count_05.pdf", "inventory count", "sku", "stock", "ops"),
    ("table_model_score_06.pdf", "model score", "metric", "score", "ml"),
    ("table_storage_cost_07.pdf", "storage cost", "service", "monthly", "infra"),
    ("table_security_scan_08.pdf", "security scan", "rule", "finding", "security"),
    ("table_release_gate_09.pdf", "release gate", "gate", "evidence", "release"),
    ("table_latency_check_10.pdf", "latency check", "path", "p95", "perf"),
    ("table_policy_matrix_11.pdf", "policy matrix", "area", "decision", "policy"),
    ("table_dataset_slice_12.pdf", "dataset slice", "tag", "count", "eval"),
    ("table_vendor_matrix_13.pdf", "vendor matrix", "tool", "fit", "selection"),
    ("table_error_budget_14.pdf", "error budget", "service", "budget", "sre"),
    ("table_index_delta_15.pdf", "index delta", "file", "action", "sync"),
    ("table_table_coverage_16.pdf", "table coverage", "pdf", "tables", "document"),
    ("table_ocr_queue_17.pdf", "ocr queue", "batch", "language", "ocr"),
    ("table_signal_score_18.pdf", "signal score", "signal", "weight", "ranking"),
    ("table_product_roadmap_19.pdf", "product roadmap", "milestone", "owner", "planning"),
    ("table_compliance_matrix_20.pdf", "compliance matrix", "control", "status", "governance"),
    ("table_onboarding_check_21.pdf", "onboarding check", "task", "assignee", "people"),
    ("table_incident_review_22.pdf", "incident review", "event", "impact", "ops"),
    ("table_model_registry_23.pdf", "model registry", "model", "version", "mlops"),
    ("table_access_review_24.pdf", "access review", "role", "approval", "identity"),
    ("table_cost_allocation_25.pdf", "cost allocation", "team", "amount", "finance"),
    ("table_experiment_score_26.pdf", "experiment score", "variant", "uplift", "analytics"),
    ("table_data_retention_27.pdf", "data retention", "dataset", "policy", "governance"),
    ("table_task_handoff_28.pdf", "task handoff", "task", "receiver", "delivery"),
    ("table_audit_sampling_29.pdf", "audit sampling", "sample", "finding", "audit"),
    ("table_capacity_plan_30.pdf", "capacity plan", "node", "usage", "infra"),
]

OCR_CASES = [
    ("ocr_receipt_total_01.pdf", "receipt total approved", "amount 184 dollars", "clean"),
    ("ocr_service_notice_02.pdf", "service window confirmed", "owner local ops", "clean"),
    ("ocr_inventory_label_03.pdf", "inventory shelf blue", "count 42 units", "clean"),
    ("ocr_invoice_stamp_04.pdf", "invoice paid marker", "batch alpha seven", "clean"),
    ("ocr_meeting_card_05.pdf", "meeting room change", "floor three east", "clean"),
    ("ocr_noisy_receipt_06.pdf", "noisy receipt captured", "total 216 dollars", "noisy"),
    ("ocr_rotated_notice_07.pdf", "rotated notice approved", "window nine thirty", "rotated"),
    ("ocr_low_contrast_label_08.pdf", "low contrast label", "batch delta four", "low_contrast"),
    ("ocr_bilingual_gate_09.pdf", "bilingual gate notice", "local access approved", "bilingual"),
    ("ocr_bilingual_inventory_10.pdf", "bilingual inventory card", "shelf orange count 58", "bilingual"),
    ("ocr_noisy_invoice_11.pdf", "noisy invoice marker", "amount 472 dollars", "noisy"),
    ("ocr_rotated_card_12.pdf", "rotated visitor card", "desk seven west", "rotated"),
    ("ocr_low_contrast_schedule_13.pdf", "low contrast schedule", "shift starts monday", "low_contrast"),
    ("ocr_english_badge_14.pdf", "temporary badge issued", "desk four north", "clean"),
    ("ocr_english_noisy_permit_15.pdf", "noisy permit accepted", "lane eight west", "noisy"),
    ("ocr_english_rotated_asset_16.pdf", "rotated asset label", "rack twelve south", "rotated"),
    ("ocr_english_low_contrast_memo_17.pdf", "low contrast memo", "archive box thirty", "low_contrast"),
    ("ocr_english_bilingual_ticket_18.pdf", "ticket handoff complete", "support desk local", "bilingual"),
    ("ocr_english_small_invoice_19.pdf", "small invoice note", "amount 319 dollars", "small"),
    ("ocr_english_dense_card_20.pdf", "dense card approved", "serial alpha nine", "clean"),
]

KOREAN_OCR_CASES = [
    (
        "ocr_korean_notice_14.pdf",
        "로컬 검색 승인",
        "문서 보관함 이십칠",
        "korean",
    ),
    (
        "ocr_korean_inventory_15.pdf",
        "재고 선반 파랑",
        "수량 사십이",
        "korean",
    ),
    (
        "ocr_korean_noisy_notice_16.pdf",
        "긴급 점검 안내",
        "서버실 출입 제한",
        "korean_noisy",
    ),
    (
        "ocr_korean_low_contrast_receipt_17.pdf",
        "영수증 총액 확인",
        "금액 십팔만 원",
        "korean_low_contrast",
    ),
    (
        "ocr_korean_rotated_label_18.pdf",
        "문서 라벨 회전",
        "보관 위치 삼층",
        "korean_rotated",
    ),
    (
        "ocr_korean_bilingual_gate_19.pdf",
        "출입 승인 완료",
        "visitor badge local",
        "korean_bilingual",
    ),
    (
        "ocr_korean_small_text_20.pdf",
        "회의실 예약 변경",
        "오후 세시 동관",
        "korean_small",
    ),
    (
        "ocr_korean_delivery_21.pdf",
        "배송 확인 완료",
        "상자 번호 칠십삼",
        "korean",
    ),
    (
        "ocr_korean_noisy_schedule_22.pdf",
        "점검 일정 변경",
        "수요일 오전 열시",
        "korean_noisy",
    ),
    (
        "ocr_korean_bilingual_label_23.pdf",
        "보안 라벨 확인",
        "secure zone local",
        "korean_bilingual",
    ),
    (
        "ocr_korean_noisy_budget_24.pdf",
        "예산 승인 대기",
        "검토 번호 구십일",
        "korean_noisy",
    ),
    (
        "ocr_korean_rotated_invoice_25.pdf",
        "청구서 검토 완료",
        "승인 코드 팔오이",
        "korean_rotated",
    ),
    (
        "ocr_korean_low_contrast_asset_26.pdf",
        "자산 라벨 확인",
        "랙 위치 서쪽 둘",
        "korean_low_contrast",
    ),
    (
        "ocr_korean_bilingual_ticket_27.pdf",
        "지원 티켓 접수",
        "help desk local",
        "korean_bilingual",
    ),
    (
        "ocr_korean_small_policy_28.pdf",
        "정책 변경 알림",
        "버전 이점삼",
        "korean_small",
    ),
    (
        "ocr_korean_noisy_temperature_29.pdf",
        "장비 온도 경고",
        "센서 번호 십육",
        "korean_noisy",
    ),
    (
        "ocr_korean_rotated_shipping_30.pdf",
        "출고 명세 확인",
        "팔레트 칠 번",
        "korean_rotated",
    ),
    (
        "ocr_korean_low_contrast_meeting_31.pdf",
        "회의 자료 보관",
        "폴더 번호 삼십",
        "korean_low_contrast",
    ),
    (
        "ocr_korean_bilingual_audit_32.pdf",
        "감사 로그 완료",
        "audit trail local",
        "korean_bilingual",
    ),
    (
        "ocr_korean_small_backup_33.pdf",
        "백업 작업 성공",
        "새벽 두시 완료",
        "korean_small",
    ),
    (
        "ocr_korean_noisy_access_34.pdf",
        "접근 권한 확인",
        "승인 번호 사십육",
        "korean_noisy",
    ),
    (
        "ocr_korean_rotated_asset_35.pdf",
        "회전 자산 태그",
        "보관 선반 동쪽 넷",
        "korean_rotated",
    ),
    (
        "ocr_korean_low_contrast_invoice_36.pdf",
        "저대비 청구서",
        "금액 이십오만 원",
        "korean_low_contrast",
    ),
    (
        "ocr_korean_bilingual_ops_37.pdf",
        "운영 카드 확인",
        "ops desk local",
        "korean_bilingual",
    ),
    (
        "ocr_korean_small_asset_38.pdf",
        "소형 자산 라벨",
        "태그 번호 팔십일",
        "korean_small",
    ),
]

SCANNED_TABLE_CASES = [
    (
        "scanned_table_image_01.pdf",
        "north sales table",
        ["region", "owner", "total"],
        [["north", "kim", "184"], ["west", "lee", "126"]],
        "clean",
    ),
    (
        "scanned_table_blur_02.pdf",
        "support queue table",
        ["ticket", "priority", "agent"],
        [["alpha", "high", "mina"], ["beta", "low", "joon"]],
        "blurred",
    ),
    (
        "scanned_table_rotated_03.pdf",
        "latency sample table",
        ["path", "p95", "owner"],
        [["search", "42ms", "ops"], ["index", "88ms", "data"]],
        "rotated",
    ),
    (
        "scanned_table_merged_04.pdf",
        "merged cell table",
        ["group", "status", "count"],
        [["release", "ready", "17"], ["audit", "review", "9"]],
        "merged-cell",
    ),
    (
        "scanned_table_low_contrast_05.pdf",
        "low contrast table",
        ["item", "state", "score"],
        [["alpha", "ready", "71"], ["gamma", "watch", "43"]],
        "low-contrast",
    ),
    (
        "scanned_table_noisy_06.pdf",
        "noisy intake table",
        ["batch", "owner", "count"],
        [["kappa", "nora", "218"], ["lambda", "ivan", "164"]],
        "noisy",
    ),
    (
        "scanned_table_bilingual_07.pdf",
        "bilingual routing table",
        ["route", "status", "memo"],
        [["seoul", "open", "gate"], ["busan", "hold", "desk"]],
        "bilingual",
    ),
    (
        "scanned_table_dense_numeric_08.pdf",
        "dense numeric table",
        ["metric", "p95", "p99"],
        [["query", "118ms", "241ms"], ["sync", "384ms", "722ms"]],
        "dense-numeric",
    ),
    (
        "scanned_table_skewed_grid_09.pdf",
        "skewed grid table",
        ["lane", "owner", "risk"],
        [["north", "lina", "low"], ["south", "taro", "high"]],
        "skewed",
    ),
    (
        "scanned_table_small_font_10.pdf",
        "small font table",
        ["case", "signal", "rank"],
        [["delta", "strong", "one"], ["omega", "weak", "nine"]],
        "small-font",
    ),
    (
        "scanned_table_receipt_11.pdf",
        "receipt line table",
        ["item", "qty", "total"],
        [["paper", "two", "18"], ["clip", "five", "7"]],
        "receipt-like",
    ),
    (
        "scanned_table_invoice_12.pdf",
        "invoice review table",
        ["code", "amount", "state"],
        [["a31", "219", "paid"], ["b72", "144", "hold"]],
        "invoice-like",
    ),
    (
        "scanned_table_dense_mixed_13.pdf",
        "dense mixed table",
        ["unit", "count", "memo"],
        [["alpha", "312", "ready"], ["theta", "419", "watch"]],
        "dense-numeric",
    ),
    (
        "scanned_table_bilingual_receipt_14.pdf",
        "bilingual receipt table",
        ["section", "status", "memo"],
        [["seoul", "ready", "local"], ["incheon", "hold", "desk"]],
        "bilingual",
    ),
    (
        "scanned_table_low_contrast_invoice_15.pdf",
        "low contrast invoice table",
        ["line", "price", "owner"],
        [["delta", "88", "nina"], ["sigma", "63", "yoon"]],
        "low-contrast",
    ),
]

DISTRACTOR_CASES = [
    ("distractor_notes_01.pdf", "table planning note", "no target table is present", "text"),
    ("distractor_notes_02.pdf", "receipt summary memo", "amount words appear without OCR target", "text"),
    ("distractor_notes_03.pdf", "korean operations memo", "로컬 안내 문구만 포함", "text"),
    ("distractor_notes_04.pdf", "scanned table discussion", "mentions grid but no target rows", "text"),
    ("distractor_notes_05.pdf", "invoice planning memo", "approval words without relevant table", "text"),
    ("distractor_notes_06.pdf", "latency review memo", "p95 and cache words without benchmark target", "text"),
    ("distractor_notes_07.pdf", "audit background memo", "sample and finding words only", "text"),
    ("distractor_notes_08.pdf", "inventory narrative memo", "stock count words without label target", "text"),
    ("distractor_notes_09.pdf", "bilingual routing memo", "LOCAL ROUTING and 로컬 경로 in paragraph form", "text"),
    ("distractor_notes_10.pdf", "capacity narrative memo", "node usage words without table cells", "text"),
    ("distractor_notes_11.pdf", "policy narrative memo", "area decision words without matrix", "text"),
    ("distractor_notes_12.pdf", "support narrative memo", "priority agent words without queue rows", "text"),
    ("distractor_notes_13.pdf", "asset narrative memo", "rack shelf words without OCR target", "text"),
    ("distractor_notes_14.pdf", "meeting narrative memo", "floor desk words without card image", "text"),
    ("distractor_notes_15.pdf", "backup narrative memo", "새벽 두시 words without OCR image", "text"),
    ("distractor_notes_16.pdf", "shipping narrative memo", "팔레트 words without rotated label", "text"),
    ("distractor_notes_17.pdf", "quality narrative memo", "check result words without table", "text"),
    ("distractor_notes_18.pdf", "release narrative memo", "gate evidence words without release table", "text"),
]


def main() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    for index, case in enumerate(TABLE_CASES, start=1):
        _write_missing(PDF_DIR / case[0], _write_table_pdf, case, index)
    for case in OCR_CASES:
        _write_missing(PDF_DIR / case[0], _write_ocr_pdf, case)
    for case in KOREAN_OCR_CASES:
        _write_missing(PDF_DIR / case[0], _write_ocr_pdf, case)
    for case in SCANNED_TABLE_CASES:
        _write_missing(PDF_DIR / case[0], _write_scanned_table_pdf, case)
    for case in DISTRACTOR_CASES:
        _write_missing(PDF_DIR / case[0], _write_distractor_pdf, case)
    BASE_GOLDEN.write_text(
        json.dumps({"queries": _base_queries()}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    TABLE_GOLDEN.write_text(
        json.dumps({"queries": _table_queries()}, indent=2) + "\n",
        encoding="utf-8",
    )
    OCR_GOLDEN.write_text(
        json.dumps({"queries": _ocr_queries()}, indent=2) + "\n",
        encoding="utf-8",
    )
    KOREAN_OCR_GOLDEN.write_text(
        json.dumps({"queries": _korean_ocr_queries()}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    SCANNED_TABLE_GOLDEN.write_text(
        json.dumps({"queries": _scanned_table_queries()}, indent=2) + "\n",
        encoding="utf-8",
    )
    CACHE_SAFETY_GOLDEN.write_text(
        json.dumps({"queries": _cache_safety_queries()}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    PDF_CORPUS_MANIFEST.write_text(
        json.dumps(_corpus_manifest(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_missing(path: Path, writer, *args) -> None:
    if path.exists():
        return
    writer(path, *args)


def _write_table_pdf(path: Path, case: tuple[str, str, str, str, str], index: int) -> None:
    _, title, left_header, middle_header, tag = case
    doc = fitz.open()
    page = doc.new_page(width=480, height=300)
    page.insert_text((36, 32), f"LocalLens table fixture {index}: {title}", fontsize=12)
    x_points = [36, 156, 276, 420]
    y_points = [64, 96, 128, 160, 192]
    for x_point in x_points:
        page.draw_line((x_point, y_points[0]), (x_point, y_points[-1]))
    for y_point in y_points:
        page.draw_line((x_points[0], y_point), (x_points[-1], y_point))
    rows = [
        [left_header, middle_header, "note"],
        [f"{tag}-alpha", "green", "ready"],
        [f"{tag}-beta", "yellow", "review"],
        [f"{tag}-gamma", "blue", "closed"],
    ]
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            page.insert_text(
                (x_points[column_index] + 8, y_points[row_index] + 21),
                value,
                fontsize=9,
            )
    doc.save(str(path))
    doc.close()


def _write_ocr_pdf(path: Path, case: tuple[str, str, str, str]) -> None:
    _, first_line, second_line, style = case
    is_low_contrast = "low_contrast" in style
    background = (238, 238, 238) if is_low_contrast else "white"
    ink = (118, 118, 118) if is_low_contrast else "black"
    image = Image.new("RGB", (1200, 420), background)
    draw = ImageDraw.Draw(image)
    font = _font(42 if "small" in style else 56)
    small_font = _font(34 if "small" in style else 44)
    draw.text((72, 70), first_line.upper(), fill=ink, font=font)
    draw.text((72, 170), second_line.upper(), fill=ink, font=small_font)
    if "bilingual" in style:
        draw.text((72, 270), "LOCAL NOTICE / 로컬 안내", fill=ink, font=_font(36))
    draw.rectangle((48, 48, 1152, 350), outline=ink, width=4)
    if "noisy" in style:
        _apply_noise(draw)
    if "rotated" in style:
        image = image.rotate(2, expand=False, fillcolor="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=640, height=300)
    page.insert_image(fitz.Rect(40, 32, 600, 256), stream=buffer.getvalue())
    doc.save(str(path))
    doc.close()


def _write_scanned_table_pdf(
    path: Path,
    case: tuple[str, str, list[str], list[list[str]], str],
) -> None:
    _, title, headers, rows, style = case
    background = (235, 235, 235) if style == "low-contrast" else "white"
    ink = (115, 115, 115) if style == "low-contrast" else "black"
    image = Image.new("RGB", (1400, 720), background)
    draw = ImageDraw.Draw(image)
    font = _font(36 if style == "small-font" else 44)
    small_font = _font(28 if style == "small-font" else 36)
    draw.text((80, 48), title.upper(), fill=ink, font=font)
    x_points = [80, 440, 800, 1160]
    y_points = [148, 228, 308, 388]
    if style == "merged-cell":
        draw.rectangle(
            ((x_points[0], y_points[0]), (x_points[-1], y_points[1])),
            outline=ink,
            width=5,
        )
        draw.text((x_points[0] + 28, y_points[0] + 22), "summary header", fill=ink, font=small_font)
        body_y_points = [y_points[1], y_points[2], y_points[3], 468]
    else:
        body_y_points = y_points
    for x_point in x_points:
        draw.line(
            ((x_point, body_y_points[0]), (x_point, body_y_points[-1])),
            fill=ink,
            width=4,
        )
    for y_point in body_y_points:
        draw.line(
            ((x_points[0], y_point), (x_points[-1], y_point)),
            fill=ink,
            width=4,
        )
    table_rows = [headers, *rows]
    for row_index, row in enumerate(table_rows):
        if row_index >= len(body_y_points) - 1:
            break
        for column_index, value in enumerate(row):
            draw.text(
                (x_points[column_index] + 24, body_y_points[row_index] + 22),
                value.upper(),
                fill=ink,
                font=small_font,
            )
    if style == "blurred":
        image = image.filter(ImageFilter.GaussianBlur(radius=0.8))
    if style == "noisy":
        _apply_noise(draw)
    if style == "bilingual":
        draw.text((80, 510), "LOCAL ROUTING / 로컬 경로", fill=ink, font=_font(30))
    if style in {"rotated", "skewed"}:
        image = image.rotate(2, expand=False, fillcolor="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=640, height=360)
    page.insert_image(fitz.Rect(32, 32, 608, 328), stream=buffer.getvalue())
    doc.save(str(path))
    doc.close()


def _write_distractor_pdf(path: Path, case: tuple[str, str, str, str]) -> None:
    _, title, body, _style = case
    doc = fitz.open()
    page = doc.new_page(width=520, height=260)
    page.insert_text((36, 42), f"LocalLens distractor fixture: {title}", fontsize=12)
    page.insert_textbox(
        fitz.Rect(36, 74, 480, 210),
        (
            f"{body}. This generated document intentionally shares vocabulary "
            "with nearby queries while omitting the expected evidence unit."
        ),
        fontsize=10,
    )
    doc.save(str(path))
    doc.close()


def _font(size: int):
    for candidate in _font_candidates():
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def _font_candidates() -> list[str]:
    windows_dir = os.environ.get("WINDIR")
    windows_fonts = []
    if windows_dir:
        font_dir = Path(windows_dir) / "Fonts"
        windows_fonts = [
            str(font_dir / "malgun.ttf"),
            str(font_dir / "malgunbd.ttf"),
        ]
    return [*windows_fonts, "malgun.ttf", "arial.ttf", "calibri.ttf"]


def _apply_noise(draw: ImageDraw.ImageDraw) -> None:
    for index in range(0, 1200, 37):
        y = 42 + ((index * 17) % 300)
        draw.line((index, y, min(index + 11, 1199), y), fill=(180, 180, 180), width=1)
    for index in range(24, 1180, 53):
        y = 58 + ((index * 23) % 280)
        draw.ellipse((index, y, index + 3, y + 3), fill=(165, 165, 165))


def _table_queries() -> list[dict]:
    queries = []
    for case in TABLE_CASES:
        filename, title, left_header, middle_header, tag = case
        case_id = _case_id(filename)
        queries.append(
            {
                "id": f"table-{filename.removesuffix('.pdf')}",
                "query_id": f"table-{filename.removesuffix('.pdf')}",
                "query_set_id": "golden-pdf-table-v2",
                "corpus_id": CORPUS_ID,
                "corpus_version": CORPUS_VERSION,
                "schema_version": QUERY_SCHEMA_VERSION,
                "query": f"{title} table {left_header} {middle_header} {tag} alpha beta",
                "modality": "text",
                "backend_profile": "sentence-transformers",
                "top_k": 10,
                "relevant": [
                    {
                        "case_id": case_id,
                        "relative_path": filename,
                        "unit_type": "pdf_table",
                        "table_no": 0,
                        "gain": 3,
                        "max_rank": 5,
                    }
                ],
                "tags": [
                    "pdf",
                    "text",
                    "table",
                    "local-table",
                    tag,
                    "domain:pdf",
                    "task:table-retrieval",
                    "claim:narrow-table",
                ],
                "slice_tags": [
                    "domain:pdf",
                    "task:table-retrieval",
                    "layout:simple-grid",
                    f"topic:{tag}",
                    "claim:narrow-table",
                ],
                "claim_class": "retrieval-quality",
            }
        )
    return queries


def _base_queries() -> list[dict]:
    raw = json.loads(BASE_GOLDEN.read_text(encoding="utf-8"))
    queries = raw.get("queries", raw) if isinstance(raw, dict) else raw
    result = []
    for item in queries:
        query_id = str(item.get("query_id", item.get("id", item["query"])))
        relevant = []
        for target in item.get("relevant", []):
            locator = dict(target)
            locator.setdefault("case_id", _case_id(str(locator["relative_path"])))
            relevant.append(locator)
        tags = list(dict.fromkeys([*item.get("tags", []), "domain:pdf", "task:base-pdf"]))
        slice_tags = list(
            dict.fromkeys(
                [
                    "domain:pdf",
                    "task:base-pdf",
                    f"modality:{item.get('modality', 'unknown')}",
                    *[
                        f"tag:{tag}"
                        for tag in item.get("tags", [])
                        if tag not in {"pdf", "text", "image", "domain:pdf", "task:base-pdf"}
                        and not tag.startswith(("domain:", "task:", "claim:", "modality:"))
                    ],
                    "claim:base-fixture",
                ]
            )
        )
        normalized = {
            **item,
            "id": str(item.get("id", query_id)),
            "query_id": query_id,
            "query_set_id": "golden-pdf-base-v1",
            "corpus_id": CORPUS_ID,
            "corpus_version": CORPUS_VERSION,
            "schema_version": QUERY_SCHEMA_VERSION,
            "relevant": relevant,
            "tags": tags,
            "slice_tags": slice_tags,
            "claim_class": "retrieval-quality",
        }
        result.append(normalized)
    return result


def _ocr_queries() -> list[dict]:
    queries = []
    for case in OCR_CASES:
        filename, first_line, second_line, style = case
        case_id = _case_id(filename)
        queries.append(
            {
                "id": f"ocr-{filename.removesuffix('.pdf')}",
                "query_id": f"ocr-{filename.removesuffix('.pdf')}",
                "query_set_id": "golden-pdf-ocr-en-v2",
                "corpus_id": CORPUS_ID,
                "corpus_version": CORPUS_VERSION,
                "schema_version": QUERY_SCHEMA_VERSION,
                "query": f"{first_line} {second_line}",
                "modality": "text",
                "backend_profile": "sentence-transformers",
                "top_k": 10,
                "relevant": [
                    {
                        "case_id": case_id,
                        "relative_path": filename,
                        "unit_type": "pdf_ocr_text",
                        "image_no": 0,
                        "gain": 3,
                        "max_rank": 5,
                    }
                ],
                "tags": [
                    "pdf",
                    "text",
                    "ocr",
                    "local-ocr",
                    style,
                    "domain:pdf",
                    "task:ocr",
                    "lang:en",
                    f"scan:{_scan_tag(style)}",
                    "claim:narrow-ocr",
                ],
                "slice_tags": [
                    "domain:pdf",
                    "task:ocr",
                    "lang:en",
                    f"scan:{_scan_tag(style)}",
                    "claim:narrow-ocr",
                ],
                "claim_class": "retrieval-quality",
            }
        )
    return queries


def _korean_ocr_queries() -> list[dict]:
    queries = []
    for case in KOREAN_OCR_CASES:
        filename, first_line, second_line, style = case
        tags = ["pdf", "text", "ocr", "local-ocr", "korean"]
        if style != "korean":
            tags.append(style)
        case_id = _case_id(filename)
        lang_tag = "lang:ko-en" if "bilingual" in style else "lang:ko"
        queries.append(
            {
                "id": f"ocr-korean-{filename.removesuffix('.pdf')}",
                "query_id": f"ocr-korean-{filename.removesuffix('.pdf')}",
                "query_set_id": "golden-pdf-ocr-ko-v2",
                "corpus_id": CORPUS_ID,
                "corpus_version": CORPUS_VERSION,
                "schema_version": QUERY_SCHEMA_VERSION,
                "query": f"{first_line} {second_line}",
                "modality": "text",
                "backend_profile": "sentence-transformers",
                "top_k": 10,
                "relevant": [
                    {
                        "case_id": case_id,
                        "relative_path": filename,
                        "unit_type": "pdf_ocr_text",
                        "image_no": 0,
                        "gain": 3,
                        "max_rank": 5,
                    }
                ],
                "tags": [
                    *tags,
                    "domain:pdf",
                    "task:ocr",
                    lang_tag,
                    f"scan:{_scan_tag(style)}",
                    "claim:narrow-ocr",
                ],
                "slice_tags": [
                    "domain:pdf",
                    "task:ocr",
                    lang_tag,
                    f"scan:{_scan_tag(style)}",
                    "claim:narrow-ocr",
                ],
                "claim_class": "retrieval-quality",
            }
        )
    return queries


def _scanned_table_queries() -> list[dict]:
    queries = []
    for case in SCANNED_TABLE_CASES:
        filename, title, headers, rows, style = case
        flat = " ".join([title, *headers, *[value for row in rows for value in row]])
        case_id = _case_id(filename)
        queries.append(
            {
                "id": f"scanned-table-{filename.removesuffix('.pdf')}",
                "query_id": f"scanned-table-{filename.removesuffix('.pdf')}",
                "query_set_id": "golden-pdf-scanned-table-v2",
                "corpus_id": CORPUS_ID,
                "corpus_version": CORPUS_VERSION,
                "schema_version": QUERY_SCHEMA_VERSION,
                "query": flat,
                "modality": "text",
                "backend_profile": "sentence-transformers",
                "top_k": 10,
                "expected_table": {
                    "rows": [headers, *rows],
                },
                "relevant": [
                    {
                        "case_id": case_id,
                        "relative_path": filename,
                        "unit_type": "pdf_ocr_text",
                        "image_no": 0,
                        "gain": 3,
                        "max_rank": 5,
                    }
                ],
                "tags": [
                    "pdf",
                    "text",
                    "ocr",
                    "scanned-table",
                    style,
                    "domain:pdf",
                    "task:table-structure",
                    "task:ocr",
                    f"scan:{_scan_tag(style)}",
                    f"layout:{_layout_tag(style)}",
                    "claim:narrow-ocr",
                ],
                "slice_tags": [
                    "domain:pdf",
                    "task:table-structure",
                    "task:ocr",
                    f"scan:{_scan_tag(style)}",
                    f"layout:{_layout_tag(style)}",
                    "claim:narrow-ocr",
                ],
                "claim_class": "retrieval-quality",
            }
        )
    return queries


def _cache_safety_queries() -> list[dict]:
    hard_negative_specs = [
        (
            "table-budget-vs-planning-note",
            "budget review table owner variance finance alpha beta",
            "table_budget_review_01.pdf",
            "pdf_table",
            "distractor_notes_01.pdf",
            ["task:table-retrieval", "topic:finance"],
        ),
        (
            "receipt-total-vs-summary-memo",
            "receipt total approved amount 184 dollars",
            "ocr_receipt_total_01.pdf",
            "pdf_ocr_text",
            "distractor_notes_02.pdf",
            ["task:ocr", "layout:receipt-like", "lang:en"],
        ),
        (
            "ko-notice-vs-ops-memo",
            "로컬 검색 승인 문서 보관함 이십칠",
            "ocr_korean_notice_14.pdf",
            "pdf_ocr_text",
            "distractor_notes_03.pdf",
            ["task:ocr", "lang:ko"],
        ),
        (
            "scanned-grid-vs-discussion",
            "north sales table region owner total kim west lee",
            "scanned_table_image_01.pdf",
            "pdf_ocr_text",
            "distractor_notes_04.pdf",
            ["task:table-structure", "task:ocr"],
        ),
        (
            "invoice-table-vs-planning",
            "invoice review table code amount state paid hold",
            "scanned_table_invoice_12.pdf",
            "pdf_ocr_text",
            "distractor_notes_05.pdf",
            ["task:table-structure", "layout:invoice-like"],
        ),
        (
            "latency-table-vs-memo",
            "latency check table path p95 perf alpha beta",
            "table_latency_check_10.pdf",
            "pdf_table",
            "distractor_notes_06.pdf",
            ["task:table-retrieval", "topic:perf"],
        ),
        (
            "audit-sampling-vs-background",
            "audit sampling table sample finding audit alpha beta",
            "table_audit_sampling_29.pdf",
            "pdf_table",
            "distractor_notes_07.pdf",
            ["task:table-retrieval", "topic:audit"],
        ),
        (
            "inventory-label-vs-narrative",
            "inventory shelf blue count 42 units",
            "ocr_inventory_label_03.pdf",
            "pdf_ocr_text",
            "distractor_notes_08.pdf",
            ["task:ocr", "lang:en"],
        ),
        (
            "routing-table-vs-bilingual-memo",
            "bilingual routing table route status memo seoul busan",
            "scanned_table_bilingual_07.pdf",
            "pdf_ocr_text",
            "distractor_notes_09.pdf",
            ["task:table-structure", "lang:ko-en"],
        ),
        (
            "capacity-table-vs-narrative",
            "capacity plan table node usage infra alpha beta",
            "table_capacity_plan_30.pdf",
            "pdf_table",
            "distractor_notes_10.pdf",
            ["task:table-retrieval", "topic:infra"],
        ),
        (
            "policy-matrix-vs-narrative",
            "policy matrix table area decision policy alpha beta",
            "table_policy_matrix_11.pdf",
            "pdf_table",
            "distractor_notes_11.pdf",
            ["task:table-retrieval", "topic:policy"],
        ),
        (
            "support-queue-vs-narrative",
            "support queue table priority agent support alpha beta",
            "table_support_queue_04.pdf",
            "pdf_table",
            "distractor_notes_12.pdf",
            ["task:table-retrieval", "topic:support"],
        ),
        (
            "rotated-asset-vs-narrative",
            "rotated asset label rack twelve south",
            "ocr_english_rotated_asset_16.pdf",
            "pdf_ocr_text",
            "distractor_notes_13.pdf",
            ["task:ocr", "scan:rotated"],
        ),
        (
            "meeting-card-vs-narrative",
            "meeting room change floor three east",
            "ocr_meeting_card_05.pdf",
            "pdf_ocr_text",
            "distractor_notes_14.pdf",
            ["task:ocr", "lang:en"],
        ),
        (
            "backup-card-vs-narrative",
            "백업 작업 성공 새벽 두시 완료",
            "ocr_korean_small_backup_33.pdf",
            "pdf_ocr_text",
            "distractor_notes_15.pdf",
            ["task:ocr", "lang:ko", "scan:small"],
        ),
        (
            "shipping-label-vs-narrative",
            "출고 명세 확인 팔레트 칠 번",
            "ocr_korean_rotated_shipping_30.pdf",
            "pdf_ocr_text",
            "distractor_notes_16.pdf",
            ["task:ocr", "lang:ko", "scan:rotated"],
        ),
        (
            "quality-table-vs-narrative",
            "quality audit table check result qa alpha beta",
            "table_quality_audit_03.pdf",
            "pdf_table",
            "distractor_notes_17.pdf",
            ["task:table-retrieval", "topic:qa"],
        ),
        (
            "release-gate-vs-narrative",
            "release gate table gate evidence release alpha beta",
            "table_release_gate_09.pdf",
            "pdf_table",
            "distractor_notes_18.pdf",
            ["task:table-retrieval", "topic:release"],
        ),
    ]
    lifecycle_specs = [
        ("warm-table-budget", "warm reuse budget review owner variance", "table_budget_review_01.pdf", "pdf_table", "warm-reuse"),
        ("warm-ocr-receipt", "warm reuse receipt total approved amount", "ocr_receipt_total_01.pdf", "pdf_ocr_text", "warm-reuse"),
        ("stale-table-rollout", "stale content rollout plan stage status", "table_rollout_plan_02.pdf", "pdf_table", "stale-content"),
        ("stale-ocr-noisy", "stale content noisy receipt total 216", "ocr_noisy_receipt_06.pdf", "pdf_ocr_text", "stale-content"),
        ("corrupt-table-latency", "corrupt cache latency check path p95", "table_latency_check_10.pdf", "pdf_table", "corrupt-blob"),
        ("corrupt-ocr-rotated", "corrupt cache rotated notice approved", "ocr_rotated_notice_07.pdf", "pdf_ocr_text", "corrupt-blob"),
        ("search-source-scanned", "search source proof north sales table", "scanned_table_image_01.pdf", "pdf_ocr_text", "search-source-negative"),
        ("search-source-ko", "search source proof 로컬 검색 승인", "ocr_korean_notice_14.pdf", "pdf_ocr_text", "search-source-negative"),
        ("search-source-release", "search source proof release gate evidence", "table_release_gate_09.pdf", "pdf_table", "search-source-negative"),
        ("manifest-scanned-invoice", "manifest removed invoice review table", "scanned_table_invoice_12.pdf", "pdf_ocr_text", "manifest-removed"),
        ("manifest-ko-bilingual", "manifest removed 출입 승인 완료 visitor badge", "ocr_korean_bilingual_gate_19.pdf", "pdf_ocr_text", "manifest-removed"),
        ("manifest-table-capacity", "manifest removed capacity plan node usage", "table_capacity_plan_30.pdf", "pdf_table", "manifest-removed"),
    ]
    queries = []
    for query_id, query, target, unit_type, negative, extra_tags in hard_negative_specs:
        queries.append(
            _cache_query(
                query_id=f"cache-hard-negative-{query_id}",
                query=query,
                target=target,
                unit_type=unit_type,
                scenario="hard-negative",
                claim_class="hard-negative-safety",
                negative_paths=[negative],
                extra_tags=extra_tags,
            )
        )
    for query_id, query, target, unit_type, scenario in lifecycle_specs:
        queries.append(
            _cache_query(
                query_id=f"cache-lifecycle-{query_id}",
                query=query,
                target=target,
                unit_type=unit_type,
                scenario=scenario,
                claim_class="cache-lifecycle-safety",
                negative_paths=[],
                extra_tags=[f"claim:{scenario}"],
            )
        )
    return queries


def _cache_query(
    *,
    query_id: str,
    query: str,
    target: str,
    unit_type: str,
    scenario: str,
    claim_class: str,
    negative_paths: list[str],
    extra_tags: list[str],
) -> dict:
    target_locator = {
        "case_id": _case_id(target),
        "relative_path": target,
        "unit_type": unit_type,
        "gain": 3,
        "max_rank": 5,
    }
    if unit_type == "pdf_table":
        target_locator["table_no"] = 0
    elif unit_type == "pdf_ocr_text":
        target_locator["image_no"] = 0
    else:
        raise ValueError(f"Unsupported cache query unit type: {unit_type}")
    slice_tags = [
        "domain:pdf",
        "task:cache-safety",
        *extra_tags,
        f"scenario:{scenario}",
        f"claim-class:{claim_class}",
    ]
    return {
        "id": query_id,
        "query_id": query_id,
        "query_set_id": "golden-pdf-cache-safety-v1",
        "corpus_id": CORPUS_ID,
        "corpus_version": CORPUS_VERSION,
        "schema_version": QUERY_SCHEMA_VERSION,
        "query": query,
        "modality": "text",
        "backend_profile": "sentence-transformers",
        "top_k": 10,
        "scenario": scenario,
        "claim_class": claim_class,
        "negative_paths": negative_paths,
        "relevant": [target_locator],
        "tags": [
            "pdf",
            "text",
            "cache-safety",
            scenario,
            claim_class,
            *extra_tags,
        ],
        "slice_tags": slice_tags,
    }


def _corpus_manifest() -> dict:
    cases = _all_corpus_cases()
    return {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "corpus_version": CORPUS_VERSION,
        "generator_version": GENERATOR_VERSION,
        "slice_registry_version": SLICE_REGISTRY_VERSION,
        "corpus_family": "pdf-ocrtable",
        "fixture_tier": "synthetic_public",
        "doc_count": len(cases),
        "query_set_ids": [
            "golden-pdf-base-v1",
            "golden-pdf-table-v2",
            "golden-pdf-ocr-en-v2",
            "golden-pdf-ocr-ko-v2",
            "golden-pdf-scanned-table-v2",
            "golden-pdf-cache-safety-v1",
        ],
        "artifact_hashes": {
            BASE_GOLDEN.name: _sha256_file(BASE_GOLDEN),
            TABLE_GOLDEN.name: _sha256_file(TABLE_GOLDEN),
            OCR_GOLDEN.name: _sha256_file(OCR_GOLDEN),
            KOREAN_OCR_GOLDEN.name: _sha256_file(KOREAN_OCR_GOLDEN),
            SCANNED_TABLE_GOLDEN.name: _sha256_file(SCANNED_TABLE_GOLDEN),
            CACHE_SAFETY_GOLDEN.name: _sha256_file(CACHE_SAFETY_GOLDEN),
        },
        "cases": cases,
        "slice_summary": _slice_summary(cases),
    }


def _all_corpus_cases() -> list[dict]:
    return [
        *(_case_metadata(filename, primary_slice, tags) for filename, primary_slice, tags in BASE_PDF_CASES),
        *(_case_metadata(case[0], "table", ["task:table-retrieval", "layout:simple-grid"]) for case in TABLE_CASES),
        *(_case_metadata(case[0], "english_ocr", ["task:ocr", "lang:en", f"scan:{_scan_tag(case[3])}"]) for case in OCR_CASES),
        *(
            _case_metadata(
                case[0],
                "korean_ocr",
                [
                    "task:ocr",
                    "lang:ko-en" if "bilingual" in case[3] else "lang:ko",
                    f"scan:{_scan_tag(case[3])}",
                ],
            )
            for case in KOREAN_OCR_CASES
        ),
        *(
            _case_metadata(
                case[0],
                "scanned_table",
                [
                    "task:table-structure",
                    "task:ocr",
                    f"scan:{_scan_tag(case[4])}",
                    f"layout:{_layout_tag(case[4])}",
                ],
            )
            for case in SCANNED_TABLE_CASES
        ),
        *(
            _case_metadata(
                case[0],
                "hard_negative",
                ["task:hard-negative", "claim:negative-control"],
            )
            for case in DISTRACTOR_CASES
        ),
    ]


def _case_metadata(filename: str, primary_slice: str, tags: list[str]) -> dict:
    return {
        "case_id": _case_id(filename),
        "corpus_id": CORPUS_ID,
        "corpus_version": CORPUS_VERSION,
        "relative_path": filename,
        "primary_slice": primary_slice,
        "slice_tags": ["domain:pdf", *tags],
        "fixture_tier": "synthetic_public",
        "generator_profile": GENERATOR_VERSION,
        "privacy_class": "generated-fixture",
        "expected_unit_types": _expected_unit_types(primary_slice),
        "content_variant": _content_variant(filename, tags),
    }


def _expected_unit_types(primary_slice: str) -> list[str]:
    if primary_slice == "table":
        return ["pdf_table"]
    if primary_slice in {"english_ocr", "korean_ocr", "scanned_table"}:
        return ["pdf_ocr_text"]
    return ["document"]


def _content_variant(filename: str, tags: list[str]) -> str:
    for tag in tags:
        if tag.startswith("scan:") and tag != "scan:clean":
            return tag.removeprefix("scan:")
    if filename.startswith("distractor_"):
        return "distractor"
    return "clean"


def _slice_summary(cases: list[dict]) -> dict:
    summary: dict[str, int] = {}
    for case in cases:
        summary[f"primary:{case['primary_slice']}"] = (
            summary.get(f"primary:{case['primary_slice']}", 0) + 1
        )
        for tag in case["slice_tags"]:
            summary[tag] = summary.get(tag, 0) + 1
    return dict(sorted(summary.items()))


def _case_id(filename: str) -> str:
    return filename.removesuffix(".pdf").replace("_", "-")


def _scan_tag(style: str) -> str:
    normalized = style.replace("_", "-")
    if normalized in {"blurred"}:
        return "noisy"
    if normalized in {"receipt-like", "invoice-like", "dense-numeric"}:
        return "clean"
    if normalized in {"merged-cell"}:
        return "clean"
    return normalized


def _layout_tag(style: str) -> str:
    normalized = style.replace("_", "-")
    if normalized in {"merged-cell"}:
        return "merged-cell"
    if normalized in {"dense-numeric", "small-font"}:
        return "dense"
    if normalized in {"receipt-like", "invoice-like"}:
        return normalized
    return "simple-grid"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
