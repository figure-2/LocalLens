from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
IMAGE_DIR = ROOT / "fixtures" / "image_corpus"
GOLDEN_PATH = ROOT / "fixtures" / "golden_quality_queries.json"


SCENES = [
    ("badge_blue_security", "blue security badge", "badge", "blue", "security"),
    ("badge_green_security", "green security badge", "badge", "green", "security"),
    ("binder_red_archive", "red archive binder", "binder", "red", "archive"),
    ("binder_gray_archive", "gray archive binder", "binder", "gray", "archive"),
    ("calendar_green_deadline", "green deadline mark on a calendar", "calendar", "green", "deadline"),
    ("calendar_purple_deadline", "purple deadline mark on a calendar", "calendar", "purple", "deadline"),
    ("camera_black_tripod", "black camera on a tripod", "camera", "black", "tripod"),
    ("camera_silver_tripod", "silver camera on a tripod", "camera", "silver", "tripod"),
    ("chart_blue_pie", "blue pie chart on a report", "chart", "blue", "pie"),
    ("chart_orange_pie", "orange pie chart on a report", "chart", "orange", "pie"),
    ("clipboard_teal_checklist", "teal checklist on a clipboard", "clipboard", "teal", "checklist"),
    ("clipboard_yellow_checklist", "yellow checklist on a clipboard", "clipboard", "yellow", "checklist"),
    ("mailbox_blue_parcel", "blue parcel near a mailbox", "mailbox", "blue", "parcel"),
    ("mailbox_brown_parcel", "brown parcel near a mailbox", "mailbox", "brown", "parcel"),
    ("printer_black_paper", "black printer with paper", "printer", "black", "paper"),
    ("printer_white_paper", "white printer with paper", "printer", "white", "paper"),
    ("receipt_red_stamp", "red stamp on a receipt", "receipt", "red", "stamp"),
    ("receipt_blue_stamp", "blue stamp on a receipt", "receipt", "blue", "stamp"),
    ("router_green_signal", "green signal lights on a router", "router", "green", "signal"),
    ("router_amber_signal", "amber signal lights on a router", "router", "amber", "signal"),
    ("tablet_black_dashboard", "black tablet showing a dashboard", "tablet", "black", "dashboard"),
    ("tablet_white_dashboard", "white tablet showing a dashboard", "tablet", "white", "dashboard"),
    ("ticket_pink_transit", "pink transit ticket", "ticket", "pink", "transit"),
    ("ticket_blue_transit", "blue transit ticket", "ticket", "blue", "transit"),
    ("vial_blue_lab", "blue vial in a lab tray", "vial", "blue", "lab"),
    ("vial_amber_lab", "amber vial in a lab tray", "vial", "amber", "lab"),
    ("wallet_black_card", "black wallet with a card", "wallet", "black", "card"),
    ("wallet_tan_card", "tan wallet with a card", "wallet", "tan", "card"),
    ("workstation_green_screen", "green screen on a workstation", "workstation", "green", "screen"),
    ("workstation_purple_screen", "purple screen on a workstation", "workstation", "purple", "screen"),
    ("badge_red_compliance", "red compliance badge", "badge", "red", "compliance"),
    ("badge_purple_compliance", "purple compliance badge", "badge", "purple", "compliance"),
    ("binder_blue_manual", "blue manual binder", "binder", "blue", "manual"),
    ("binder_green_manual", "green manual binder", "binder", "green", "manual"),
    ("calendar_red_review", "red review mark on a calendar", "calendar", "red", "review"),
    ("calendar_orange_review", "orange review mark on a calendar", "calendar", "orange", "review"),
    ("camera_blue_inspection", "blue camera for inspection", "camera", "blue", "inspection"),
    ("camera_gray_inspection", "gray camera for inspection", "camera", "gray", "inspection"),
    ("chart_green_budget", "green budget pie chart", "chart", "green", "budget"),
    ("chart_purple_budget", "purple budget pie chart", "chart", "purple", "budget"),
    ("clipboard_red_audit", "red audit checklist on a clipboard", "clipboard", "red", "audit"),
    ("clipboard_blue_audit", "blue audit checklist on a clipboard", "clipboard", "blue", "audit"),
    ("mailbox_green_dispatch", "green dispatch parcel near a mailbox", "mailbox", "green", "dispatch"),
    ("mailbox_gray_dispatch", "gray dispatch parcel near a mailbox", "mailbox", "gray", "dispatch"),
    ("printer_blue_invoice", "blue printer with invoice paper", "printer", "blue", "invoice"),
    ("printer_gray_invoice", "gray printer with invoice paper", "printer", "gray", "invoice"),
    ("receipt_green_approval", "green approval stamp on a receipt", "receipt", "green", "approval"),
    ("receipt_purple_approval", "purple approval stamp on a receipt", "receipt", "purple", "approval"),
    ("router_blue_backup", "blue backup signal lights on a router", "router", "blue", "backup"),
    ("router_red_backup", "red backup signal lights on a router", "router", "red", "backup"),
    ("tablet_green_metrics", "green tablet showing metrics", "tablet", "green", "metrics"),
    ("tablet_purple_metrics", "purple tablet showing metrics", "tablet", "purple", "metrics"),
    ("ticket_green_gate", "green gate transit ticket", "ticket", "green", "gate"),
    ("ticket_yellow_gate", "yellow gate transit ticket", "ticket", "yellow", "gate"),
    ("vial_red_quality", "red quality vial in a lab tray", "vial", "red", "quality"),
    ("vial_teal_quality", "teal quality vial in a lab tray", "vial", "teal", "quality"),
    ("wallet_blue_identity", "blue identity wallet with a card", "wallet", "blue", "identity"),
    ("wallet_gray_identity", "gray identity wallet with a card", "wallet", "gray", "identity"),
    ("workstation_blue_monitoring", "blue monitoring screen on a workstation", "workstation", "blue", "monitoring"),
    ("workstation_red_monitoring", "red monitoring screen on a workstation", "workstation", "red", "monitoring"),
    ("badge_yellow_access", "yellow access badge", "badge", "yellow", "access"),
    ("badge_teal_access", "teal access badge", "badge", "teal", "access"),
    ("binder_purple_contract", "purple contract binder", "binder", "purple", "contract"),
    ("binder_tan_contract", "tan contract binder", "binder", "tan", "contract"),
    ("calendar_blue_meeting", "blue meeting mark on a calendar", "calendar", "blue", "meeting"),
    ("calendar_yellow_meeting", "yellow meeting mark on a calendar", "calendar", "yellow", "meeting"),
    ("camera_green_survey", "green camera for survey", "camera", "green", "survey"),
    ("camera_red_survey", "red camera for survey", "camera", "red", "survey"),
    ("chart_teal_forecast", "teal forecast pie chart", "chart", "teal", "forecast"),
    ("chart_gray_forecast", "gray forecast pie chart", "chart", "gray", "forecast"),
    ("clipboard_green_safety", "green safety checklist on a clipboard", "clipboard", "green", "safety"),
    ("clipboard_purple_safety", "purple safety checklist on a clipboard", "clipboard", "purple", "safety"),
    ("mailbox_red_return", "red return parcel near a mailbox", "mailbox", "red", "return"),
    ("mailbox_blue_return", "blue return parcel near a mailbox", "mailbox", "blue", "return"),
    ("printer_green_statement", "green printer with statement paper", "printer", "green", "statement"),
    ("printer_tan_statement", "tan printer with statement paper", "printer", "tan", "statement"),
    ("receipt_yellow_refund", "yellow refund stamp on a receipt", "receipt", "yellow", "refund"),
    ("receipt_teal_refund", "teal refund stamp on a receipt", "receipt", "teal", "refund"),
    ("router_purple_alert", "purple alert signal lights on a router", "router", "purple", "alert"),
    ("router_gray_alert", "gray alert signal lights on a router", "router", "gray", "alert"),
    ("tablet_red_status", "red tablet showing status", "tablet", "red", "status"),
    ("tablet_blue_status", "blue tablet showing status", "tablet", "blue", "status"),
    ("ticket_orange_boarding", "orange boarding ticket", "ticket", "orange", "boarding"),
    ("ticket_teal_boarding", "teal boarding ticket", "ticket", "teal", "boarding"),
    ("vial_green_sample", "green sample vial in a lab tray", "vial", "green", "sample"),
    ("vial_purple_sample", "purple sample vial in a lab tray", "vial", "purple", "sample"),
    ("wallet_red_badge", "red wallet with a badge card", "wallet", "red", "badge"),
    ("wallet_green_badge", "green wallet with a badge card", "wallet", "green", "badge"),
    ("workstation_yellow_terminal", "yellow terminal screen on a workstation", "workstation", "yellow", "terminal"),
    ("workstation_gray_terminal", "gray terminal screen on a workstation", "workstation", "gray", "terminal"),
    ("badge_orange_policy", "orange policy badge", "badge", "orange", "policy"),
    ("badge_brown_policy", "brown policy badge", "badge", "brown", "policy"),
    ("binder_teal_record", "teal record binder", "binder", "teal", "record"),
    ("binder_yellow_record", "yellow record binder", "binder", "yellow", "record"),
    ("calendar_gray_schedule", "gray schedule mark on a calendar", "calendar", "gray", "schedule"),
    ("calendar_teal_schedule", "teal schedule mark on a calendar", "calendar", "teal", "schedule"),
    ("camera_purple_evidence", "purple camera for evidence", "camera", "purple", "evidence"),
    ("camera_tan_evidence", "tan camera for evidence", "camera", "tan", "evidence"),
    ("chart_red_margin", "red margin pie chart", "chart", "red", "margin"),
    ("chart_blue_margin", "blue margin pie chart", "chart", "blue", "margin"),
    ("clipboard_gray_inventory", "gray inventory checklist on a clipboard", "clipboard", "gray", "inventory"),
    ("clipboard_orange_inventory", "orange inventory checklist on a clipboard", "clipboard", "orange", "inventory"),
    ("mailbox_purple_request", "purple request parcel near a mailbox", "mailbox", "purple", "request"),
    ("mailbox_tan_request", "tan request parcel near a mailbox", "mailbox", "tan", "request"),
    ("printer_red_contract", "red printer with contract paper", "printer", "red", "contract"),
    ("printer_teal_contract", "teal printer with contract paper", "printer", "teal", "contract"),
    ("receipt_black_verified", "black verified stamp on a receipt", "receipt", "black", "verified"),
    ("receipt_orange_verified", "orange verified stamp on a receipt", "receipt", "orange", "verified"),
    ("router_yellow_uplink", "yellow uplink signal lights on a router", "router", "yellow", "uplink"),
    ("router_teal_uplink", "teal uplink signal lights on a router", "router", "teal", "uplink"),
]

PALETTE = {
    "amber": (212, 137, 34),
    "black": (34, 38, 45),
    "blue": (47, 111, 209),
    "brown": (142, 93, 52),
    "gray": (118, 126, 138),
    "green": (45, 156, 95),
    "orange": (230, 130, 40),
    "pink": (224, 99, 150),
    "purple": (130, 92, 210),
    "red": (210, 68, 70),
    "silver": (175, 181, 188),
    "tan": (190, 150, 104),
    "teal": (47, 158, 160),
    "white": (238, 241, 244),
    "yellow": (232, 194, 62),
}


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for scene in SCENES:
        _write_scene(scene)
    _upsert_queries()


def _write_scene(scene: tuple[str, str, str, str, str]) -> None:
    name, _query, object_name, color_name, context_name = scene
    path = IMAGE_DIR / f"{name}.png"
    image = Image.new("RGB", (320, 220), (247, 248, 244))
    draw = ImageDraw.Draw(image)
    accent = PALETTE[color_name]
    _draw_background(draw)
    _draw_object(draw, object_name, accent)
    _draw_context(draw, context_name, accent)
    _draw_label(draw, object_name.replace("_", " ").upper())
    image.save(path)


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((0, 0, 319, 219), fill=(247, 248, 244))
    draw.rectangle((0, 178, 319, 219), fill=(224, 228, 222))
    for x in range(20, 320, 42):
        draw.line((x, 178, x + 24, 219), fill=(213, 218, 212), width=2)


def _draw_object(draw: ImageDraw.ImageDraw, object_name: str, accent: tuple[int, int, int]) -> None:
    dark = (42, 48, 56)
    light = (255, 255, 255)
    if object_name == "badge":
        draw.rounded_rectangle((118, 42, 202, 145), radius=12, fill=accent, outline=dark, width=3)
        draw.ellipse((145, 62, 175, 92), fill=light, outline=dark, width=2)
        draw.rectangle((136, 103, 184, 122), fill=light, outline=dark, width=2)
    elif object_name == "binder":
        draw.rounded_rectangle((96, 36, 210, 160), radius=8, fill=accent, outline=dark, width=3)
        draw.rectangle((115, 58, 191, 84), fill=light, outline=dark, width=2)
        draw.line((116, 110, 190, 110), fill=dark, width=3)
    elif object_name == "calendar":
        draw.rectangle((82, 42, 238, 158), fill=light, outline=dark, width=3)
        draw.rectangle((82, 42, 238, 70), fill=accent, outline=dark, width=3)
        for x in (121, 160, 199):
            draw.line((x, 78, x, 150), fill=(190, 195, 198), width=2)
        for y in (102, 126):
            draw.line((92, y, 228, y), fill=(190, 195, 198), width=2)
        draw.ellipse((166, 108, 204, 146), outline=accent, width=5)
    elif object_name == "camera":
        draw.rectangle((92, 64, 228, 126), fill=accent, outline=dark, width=3)
        draw.ellipse((132, 70, 188, 126), fill=(70, 80, 92), outline=dark, width=3)
        draw.ellipse((150, 88, 170, 108), fill=light)
        draw.line((160, 126, 124, 170), fill=dark, width=5)
        draw.line((160, 126, 196, 170), fill=dark, width=5)
    elif object_name == "chart":
        draw.rectangle((78, 44, 242, 158), fill=light, outline=dark, width=3)
        draw.pieslice((120, 64, 200, 144), 0, 250, fill=accent, outline=dark)
        draw.pieslice((120, 64, 200, 144), 250, 360, fill=(232, 232, 232), outline=dark)
    elif object_name == "clipboard":
        draw.rounded_rectangle((94, 42, 226, 164), radius=10, fill=(240, 230, 205), outline=dark, width=3)
        draw.rectangle((124, 34, 196, 58), fill=accent, outline=dark, width=3)
        for y in (82, 108, 134):
            draw.rectangle((115, y, 130, y + 15), fill=light, outline=dark, width=2)
            draw.line((142, y + 7, 205, y + 7), fill=dark, width=2)
    elif object_name == "mailbox":
        draw.rounded_rectangle((96, 62, 214, 132), radius=22, fill=accent, outline=dark, width=3)
        draw.rectangle((110, 132, 130, 170), fill=dark)
        draw.rectangle((200, 128, 252, 160), fill=(190, 135, 70), outline=dark, width=3)
    elif object_name == "printer":
        draw.rounded_rectangle((82, 84, 238, 150), radius=10, fill=accent, outline=dark, width=3)
        draw.rectangle((112, 46, 208, 90), fill=light, outline=dark, width=3)
        draw.rectangle((112, 126, 208, 166), fill=light, outline=dark, width=3)
    elif object_name == "receipt":
        draw.rectangle((106, 32, 214, 168), fill=light, outline=dark, width=3)
        for y in (58, 82, 106, 130):
            draw.line((124, y, 196, y), fill=(155, 162, 168), width=2)
        draw.ellipse((134, 92, 198, 136), outline=accent, width=6)
    elif object_name == "router":
        draw.rounded_rectangle((82, 92, 238, 140), radius=10, fill=(64, 72, 84), outline=dark, width=3)
        for x in (112, 148, 184, 220):
            draw.ellipse((x, 110, x + 12, 122), fill=accent)
        draw.line((120, 92, 102, 54), fill=dark, width=4)
        draw.line((200, 92, 218, 54), fill=dark, width=4)
    elif object_name == "tablet":
        draw.rounded_rectangle((76, 36, 244, 162), radius=12, fill=accent, outline=dark, width=4)
        draw.rectangle((94, 54, 226, 140), fill=(238, 244, 246), outline=dark, width=2)
        draw.line((110, 120, 142, 90), fill=(64, 150, 95), width=4)
        draw.line((142, 90, 176, 108), fill=(64, 150, 95), width=4)
        draw.line((176, 108, 210, 74), fill=(64, 150, 95), width=4)
    elif object_name == "ticket":
        draw.rounded_rectangle((82, 68, 238, 136), radius=14, fill=accent, outline=dark, width=3)
        draw.ellipse((72, 96, 94, 118), fill=(247, 248, 244), outline=dark, width=2)
        draw.ellipse((226, 96, 248, 118), fill=(247, 248, 244), outline=dark, width=2)
        draw.line((122, 80, 122, 124), fill=light, width=3)
    elif object_name == "vial":
        for x in (104, 142, 180):
            draw.rounded_rectangle((x, 54, x + 28, 152), radius=10, fill=light, outline=dark, width=3)
            draw.rectangle((x + 4, 98, x + 24, 148), fill=accent)
        draw.rectangle((92, 150, 228, 170), fill=(210, 215, 220), outline=dark, width=3)
    elif object_name == "wallet":
        draw.rounded_rectangle((82, 72, 238, 148), radius=12, fill=accent, outline=dark, width=3)
        draw.rectangle((154, 86, 222, 128), fill=light, outline=dark, width=2)
        draw.line((96, 110, 142, 110), fill=dark, width=3)
    elif object_name == "workstation":
        draw.rectangle((72, 42, 248, 138), fill=(55, 62, 72), outline=dark, width=3)
        draw.rectangle((92, 58, 228, 120), fill=accent)
        draw.rectangle((140, 138, 180, 164), fill=dark)
        draw.rectangle((102, 164, 218, 176), fill=dark)


def _draw_context(draw: ImageDraw.ImageDraw, context_name: str, accent: tuple[int, int, int]) -> None:
    draw.rounded_rectangle((18, 22, 82, 60), radius=8, fill=(255, 255, 255), outline=(130, 138, 144), width=2)
    draw.line((28, 42, 72, 42), fill=accent, width=4)
    draw.text((24, 26), context_name[:6].upper(), fill=(54, 60, 66), font=_font(10))


def _draw_label(draw: ImageDraw.ImageDraw, label: str) -> None:
    draw.text((18, 188), label, fill=(54, 60, 66), font=_font(16))


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _upsert_queries() -> None:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    queries = data.setdefault("queries", [])
    existing_ids = {item.get("id") for item in queries}
    for name, query, _object_name, _color_name, context_name in SCENES:
        query_id = f"image-{name.replace('_', '-')}-en-001"
        if query_id in existing_ids:
            continue
        queries.append(
            {
                "id": query_id,
                "query": query,
                "modality": "image",
                "backend_profile": "transformers",
                "top_k": 10,
                "relevant": [
                    {
                        "relative_path": f"{name}.png",
                        "unit_type": "image",
                        "gain": 3,
                        "max_rank": 3,
                    }
                ],
                "tags": [
                    "image",
                    "english",
                    "scene",
                    "synthetic",
                    "sanitized-style",
                    "realworld-style",
                    "hard-negative",
                    context_name,
                ],
            }
        )
    GOLDEN_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
