from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from locallens.ui.tkinter_app import (
    EMPTY_RESULT_ROW,
    normalize_ext_filter,
    normalize_modality_filter,
    normalize_path_prefix_filter,
    normalize_top_k_filter,
    result_row,
    selected_result_path,
)


def test_tkinter_ui_uses_service_boundary():
    source = Path("locallens/ui/tkinter_app.py").read_text(encoding="utf-8")

    assert "QdrantStore" not in source
    assert "SyncService" in source
    assert "SearchService" in source
    assert "Treeview" in source
    assert "Combobox" in source
    assert "Spinbox" in source
    assert "path_prefix_var" in source
    assert "top_k_var" in source
    assert "Top-K" in source
    assert "Path prefix" in source
    assert "Open File" in source
    assert "root_id_for_path" in source
    assert "result_root_path" in source
    assert "Cancel" in source
    assert "Retry" in source
    assert "pdf_ocr_var" in source
    assert "pdf_table_var" in source
    assert "PDF OCR" in source
    assert "Tables" in source


def test_ui_filter_normalization():
    assert normalize_modality_filter("all") is None
    assert normalize_modality_filter("text") == "text"
    assert normalize_ext_filter("") is None
    assert normalize_ext_filter("  ") is None
    assert normalize_ext_filter("pdf") == ".pdf"
    assert normalize_ext_filter(".md") == ".md"
    assert normalize_ext_filter(" PDF ") == ".pdf"
    assert normalize_top_k_filter(" 7 ") == 7
    assert normalize_path_prefix_filter("") is None
    assert normalize_path_prefix_filter(" docs\\notes ") == "docs/notes"


def test_ui_result_row_and_empty_state():
    item = SimpleNamespace(
        score=0.812345,
        modality="text",
        relative_path="docs/notes.md",
        page_no=None,
        snippet="planning notes",
    )

    assert result_row(item) == (
        "0.8123",
        "text",
        "docs/notes.md",
        "",
        "planning notes",
    )
    assert EMPTY_RESULT_ROW == ("", "", "", "", "No results")


def test_ui_selected_result_path_guards_invalid_selection(tmp_path: Path):
    results = [SimpleNamespace(relative_path="docs/notes.md")]

    assert selected_result_path(None, results, 0) is None
    assert selected_result_path(tmp_path, results, -1) is None
    assert selected_result_path(tmp_path, results, 1) is None
    assert selected_result_path(tmp_path, results, 0) == tmp_path / "docs/notes.md"
