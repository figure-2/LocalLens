from __future__ import annotations

from types import SimpleNamespace

import pytest

import locallens.ui.tkinter_app as ui


@pytest.fixture
def tk_app(monkeypatch, tmp_path):
    try:
        root = ui.tk.Tk()
    except ui.tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    monkeypatch.setenv("LOCALLENS_DATA_DIR", str(tmp_path / "data"))
    app = ui.LocalLensApp(root)
    try:
        yield root, app
    finally:
        root.destroy()


def button_by_text(root, text):
    stack = [root]
    while stack:
        widget = stack.pop()
        try:
            if widget.cget("text") == text:
                return widget
        except ui.tk.TclError:
            pass
        stack.extend(widget.winfo_children())
    raise AssertionError(f"button not found: {text}")


def test_tk_search_button_warns_on_blank_query(monkeypatch, tk_app):
    root, app = tk_app
    warnings = []
    monkeypatch.setattr(
        ui.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )

    button_by_text(root, "Search").invoke()
    root.update()

    assert warnings == [("LocalLens", "Enter a search query.")]
    assert app.status_var.get() == "Ready"


def test_tk_search_event_invalidates_stale_results(monkeypatch, tk_app, tmp_path):
    root, app = tk_app
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "old.md").write_text("old", encoding="utf-8")
    app.result_root_path = first_root
    app.last_results = [SimpleNamespace(relative_path="old.md")]
    row_id = app.results.insert("", ui.tk.END, values=("0.9", "text", "old.md", "", "old"))
    app.results.selection_set(row_id)
    app.folder_var.set(str(second_root))
    app.query_var.set("new query")
    opened = []
    monkeypatch.setattr(ui.os, "startfile", lambda path: opened.append(path), raising=False)

    def hold_run(status, fn, on_success):
        app._set_busy(status)

    app._run = hold_run

    button_by_text(root, "Search").invoke()
    root.update()
    app.open_selected()

    assert opened == []
    assert app.last_results == []
    assert app.result_root_path is None
    assert app.results.get_children() == ()
    assert app.status_var.get() == "Searching..."


def test_tk_purge_cancel_keeps_ready_state(monkeypatch, tk_app):
    root, app = tk_app
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda title, message: False)

    button_by_text(root, "Purge").invoke()
    root.update()

    assert app.status_var.get() == "Ready"
