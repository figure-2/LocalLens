from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from locallens.core.types import SearchResult, SyncFailure, SyncProgress, SyncReport
from locallens.core.config import Settings
import locallens.ui.tkinter_app as ui


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeProgress:
    def __init__(self):
        self.started = []
        self.stopped = 0
        self.configured = []

    def start(self, interval):
        self.started.append(interval)

    def stop(self):
        self.stopped += 1

    def configure(self, **kwargs):
        self.configured.append(kwargs)


class FakeButton:
    def __init__(self):
        self.states = []

    def configure(self, **kwargs):
        self.states.append(kwargs["state"])


class FakeRoot:
    def __init__(self):
        self.callbacks = []

    def after(self, delay_ms, callback):
        self.callbacks.append((delay_ms, callback))

    def run_callbacks(self):
        callbacks = list(self.callbacks)
        self.callbacks.clear()
        for _, callback in callbacks:
            callback()


class FakeTree:
    def __init__(self):
        self.rows = []
        self.deleted = []
        self.selected = []
        self.index_by_item = {}

    def delete(self, *items):
        self.deleted.extend(items)
        self.rows.clear()

    def get_children(self):
        return tuple(f"row-{index}" for index, _ in enumerate(self.rows))

    def insert(self, parent, index, values):
        self.rows.append(values)

    def selection(self):
        return tuple(self.selected)

    def index(self, item):
        return self.index_by_item[item]


def app_shell(tmp_path: Path):
    app = ui.LocalLensApp.__new__(ui.LocalLensApp)
    app.root = FakeRoot()
    app.folder_var = FakeVar("")
    app.query_var = FakeVar("")
    app.status_var = FakeVar("Ready")
    app.modality_var = FakeVar("all")
    app.ext_var = FakeVar("")
    app.top_k_var = FakeVar("10")
    app.path_prefix_var = FakeVar("")
    app.pdf_ocr_var = FakeVar(False)
    app.pdf_table_var = FakeVar(False)
    app.progress = FakeProgress()
    app.results = FakeTree()
    app.action_buttons = [FakeButton(), FakeButton()]
    app.cancel_button = FakeButton()
    app.retry_button = FakeButton()
    app.cancel_requested = False
    app.last_retry = None
    app.last_results = []
    app.result_root_path = tmp_path
    app.settings = Settings(data_dir=tmp_path / "data")
    return app


def run_immediately(app):
    def immediate(status, fn, on_success, cancellable=False):
        app._set_busy(status, cancellable=cancellable)
        on_success(fn())

    app._run = immediate


def test_index_button_command_warns_without_folder(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    warnings = []
    monkeypatch.setattr(
        ui.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )

    app.index_folder()

    assert warnings == [("LocalLens", "Select a folder first.")]


def test_search_button_command_applies_filters_and_renders_results(
    monkeypatch, tmp_path: Path
):
    app = app_shell(tmp_path)
    app.folder_var.set(str(tmp_path))
    app.query_var.set("privacy")
    app.modality_var.set("text")
    app.ext_var.set("md")
    app.top_k_var.set("7")
    app.path_prefix_var.set("docs")
    run_immediately(app)
    calls = []

    class FakeStore:
        def close(self):
            calls.append(("close",))

    class FakeSearchService:
        def __init__(self, settings):
            self.store = FakeStore()

        def search(
            self,
            query,
            top_k=10,
            modality=None,
            root_id=None,
            ext=None,
            path_prefix=None,
        ):
            calls.append(
                {
                    "query": query,
                    "top_k": top_k,
                    "modality": modality,
                    "root_id": root_id,
                    "ext": ext,
                    "path_prefix": path_prefix,
                }
            )
            return [
                SearchResult(
                    score=0.9,
                    modality="text",
                    relative_path="privacy.md",
                    page_no=None,
                    snippet="privacy notes",
                    unit_type="chunk",
                )
            ]

    monkeypatch.setattr(ui, "SearchService", FakeSearchService)
    app.results.rows = [("old", "", "", "", "old")]

    app.search()

    assert calls[0]["query"] == "privacy"
    assert calls[0]["top_k"] == 7
    assert calls[0]["modality"] == "text"
    assert calls[0]["root_id"]
    assert calls[0]["ext"] == ".md"
    assert calls[0]["path_prefix"] == "docs"
    assert calls[-1] == ("close",)
    assert app.results.rows == [("0.9000", "text/chunk", "privacy.md", "", "privacy notes")]
    assert app.result_root_path == tmp_path.resolve()
    assert app.status_var.get() == "1 results"
    assert app.progress.started == [12]
    assert app.progress.stopped == 1
    assert app.action_buttons[0].states == [ui.tk.DISABLED, ui.tk.NORMAL]


def test_search_warns_for_unsupported_extension(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    app.folder_var.set(str(tmp_path))
    app.query_var.set("privacy")
    app.ext_var.set("exe")
    warnings = []
    monkeypatch.setattr(
        ui.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )
    calls = []
    monkeypatch.setattr(ui, "SearchService", lambda settings: calls.append(settings))

    app.search()

    assert warnings == [("LocalLens", "Unsupported extension filter: .exe")]
    assert calls == []
    assert app.status_var.get() == "Ready"


def test_search_warns_for_invalid_top_k(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    app.folder_var.set(str(tmp_path))
    app.query_var.set("privacy")
    app.top_k_var.set("0")
    warnings = []
    monkeypatch.setattr(
        ui.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )
    calls = []
    monkeypatch.setattr(ui, "SearchService", lambda settings: calls.append(settings))

    app.search()

    assert warnings == [("LocalLens", "Top K must be a positive integer.")]
    assert calls == []


def test_search_warns_for_absolute_path_prefix(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    app.folder_var.set(str(tmp_path))
    app.query_var.set("privacy")
    app.path_prefix_var.set("C:" + "/Users/name/docs")
    warnings = []
    monkeypatch.setattr(
        ui.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )
    calls = []
    monkeypatch.setattr(ui, "SearchService", lambda settings: calls.append(settings))

    app.search()

    assert warnings == [("LocalLens", "Path prefix must be a relative folder.")]
    assert calls == []


def test_show_results_empty_state(tmp_path: Path):
    app = app_shell(tmp_path)

    app._show_results([])

    assert app.results.rows == [ui.EMPTY_RESULT_ROW]
    assert app.status_var.get() == "0 results"


def test_purge_button_command_confirms_and_updates_status(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    run_immediately(app)
    calls = []
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda title, message: True)

    class FakeStore:
        def close(self):
            calls.append("close")

    class FakeSyncService:
        def __init__(self, settings):
            self.store = FakeStore()

        def purge(self):
            calls.append("purge")

    monkeypatch.setattr(ui, "SyncService", FakeSyncService)

    app.purge()

    assert calls == ["purge", "close"]
    assert app.status_var.get() == "Purged"


def test_open_selected_double_click_starts_existing_file(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    target = tmp_path / "docs" / "notes.md"
    target.parent.mkdir()
    target.write_text("notes", encoding="utf-8")
    app.last_results = [SimpleNamespace(relative_path="docs/notes.md")]
    app.results.selected = ["row-0"]
    app.results.index_by_item = {"row-0": 0}
    opened = []
    monkeypatch.setattr(ui.os, "startfile", lambda path: opened.append(path), raising=False)

    app.open_selected()

    assert opened == [target]


def test_open_selected_reports_missing_file(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    app.last_results = [SimpleNamespace(relative_path="docs/missing.md")]
    app.results.selected = ["row-0"]
    app.results.index_by_item = {"row-0": 0}
    errors = []
    monkeypatch.setattr(
        ui.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
    )

    app.open_selected()

    assert errors == [("LocalLens", "File not found: missing.md")]


def test_open_selected_reports_unresolved_result_path(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    app.last_results = [SimpleNamespace(relative_path="../escape.md")]
    app.results.selected = ["row-0"]
    app.results.index_by_item = {"row-0": 0}
    errors = []
    monkeypatch.setattr(
        ui.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
    )

    app.open_selected()

    assert errors == [("LocalLens", "Could not resolve result path.")]


def test_open_selected_reports_startfile_failure(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    target = tmp_path / "docs" / "notes.md"
    target.parent.mkdir()
    target.write_text("notes", encoding="utf-8")
    app.last_results = [SimpleNamespace(relative_path="docs/notes.md")]
    app.results.selected = ["row-0"]
    app.results.index_by_item = {"row-0": 0}
    errors = []

    def fail_open(path):
        raise OSError("no association")

    monkeypatch.setattr(ui.os, "startfile", fail_open, raising=False)
    monkeypatch.setattr(
        ui.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
    )

    app.open_selected()

    assert errors == [("LocalLens", "Could not open file: notes.md")]


def test_open_selected_reports_stale_selection(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    app.last_results = [SimpleNamespace(relative_path="docs/notes.md")]
    app.results.selected = ["row-missing"]
    errors = []
    monkeypatch.setattr(
        ui.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
    )

    app.open_selected()

    assert errors == [("LocalLens", "Selected result is no longer available.")]


def test_search_start_invalidates_stale_results_before_completion(
    monkeypatch, tmp_path: Path
):
    app = app_shell(tmp_path)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    target = first_root / "old.md"
    target.write_text("old", encoding="utf-8")
    app.result_root_path = first_root
    app.last_results = [SimpleNamespace(relative_path="old.md")]
    app.results.rows = [("0.9000", "text", "old.md", "", "old")]
    app.results.selected = ["row-0"]
    app.results.index_by_item = {"row-0": 0}
    app.folder_var.set(str(second_root))
    app.query_var.set("new query")
    opened = []
    monkeypatch.setattr(ui.os, "startfile", lambda path: opened.append(path), raising=False)
    monkeypatch.setattr(ui, "SearchService", lambda settings: None)

    def hold_run(status, fn, on_success):
        app._set_busy(status)

    app._run = hold_run

    app.search()
    app.open_selected()

    assert opened == []
    assert app.last_results == []
    assert app.result_root_path is None
    assert app.results.rows == []


def test_index_button_command_runs_sync(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    app.folder_var.set(str(tmp_path))
    app.pdf_ocr_var.set(True)
    app.pdf_table_var.set(True)
    run_immediately(app)
    calls = []

    class FakeStore:
        def close(self):
            calls.append("close")

    class FakeSyncService:
        def __init__(self, settings):
            self.store = FakeStore()
            calls.append(("modes", settings.pdf_ocr_mode, settings.pdf_table_mode))

        def sync_folder(self, folder, progress_callback=None):
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        phase="indexing",
                        processed=0,
                        total=1,
                        relative_path="doc.txt",
                    )
                )
            calls.append(("sync", folder))
            return SyncReport(added=1, units=2)

    monkeypatch.setattr(ui, "SyncService", FakeSyncService)

    app.index_folder()

    assert calls == [("modes", "local-ocr", "local-table"), ("sync", str(tmp_path)), "close"]
    assert app.status_var.get().startswith("Indexed added=1")
    assert "PDF OCR=on Tables=on" in app.status_var.get()


def test_cancel_request_stops_next_sync_progress(tmp_path: Path):
    app = app_shell(tmp_path)
    app._set_busy("Indexing...", cancellable=True)

    app.cancel_current()
    allowed = app._sync_progress(
        SyncProgress(
            phase="indexing",
            processed=0,
            total=1,
            relative_path="doc.txt",
        )
    )

    assert allowed is False
    assert app.cancel_requested is True
    assert app.status_var.get() == "Cancel requested; waiting for current step"
    assert app.cancel_button.states == [ui.tk.NORMAL, ui.tk.DISABLED]


def test_cancelled_sync_report_restores_retry_state(tmp_path: Path):
    app = app_shell(tmp_path)
    app.last_retry = lambda: None
    app._set_busy("Indexing...", cancellable=True)

    app._show_sync_report(SyncReport(cancelled=True))

    assert app.status_var.get() == "Indexing cancelled"
    assert app.cancel_button.states[-1] == ui.tk.DISABLED
    assert app.retry_button.states[-1] == ui.tk.NORMAL


def test_retry_last_invokes_previous_action(tmp_path: Path):
    app = app_shell(tmp_path)
    calls = []
    app.last_retry = lambda: calls.append("retry")

    app.retry_last()

    assert calls == ["retry"]


def test_search_retry_reuses_previous_filter_snapshot(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    app.folder_var.set(str(tmp_path))
    app.query_var.set("first query")
    app.top_k_var.set("3")
    run_immediately(app)
    calls = []

    class FakeStore:
        def close(self):
            pass

    class FakeSearchService:
        def __init__(self, settings):
            self.store = FakeStore()

        def search(self, query, **kwargs):
            calls.append((query, kwargs["top_k"]))
            return []

    monkeypatch.setattr(ui, "SearchService", FakeSearchService)

    app.search()
    app.query_var.set("second query")
    app.top_k_var.set("9")
    app.retry_last()

    assert calls == [("first query", 3), ("first query", 3)]


def test_sync_progress_updates_status(tmp_path: Path):
    app = app_shell(tmp_path)

    app._show_sync_progress(
        SyncProgress(
            phase="indexing",
            processed=1,
            total=3,
            relative_path="docs/one.md",
            failed=1,
        )
    )

    assert app.status_var.get() == "Indexing 1/3 docs/one.md failed=1"
    assert app.progress.configured[-1] == {
        "mode": "determinate",
        "maximum": 3,
        "value": 1,
    }


def test_sync_progress_includes_nonzero_counters(tmp_path: Path):
    app = app_shell(tmp_path)

    app._show_sync_progress(
        SyncProgress(
            phase="indexing",
            processed=2,
            total=5,
            relative_path="docs/two.md",
            added=1,
            skipped=1,
        )
    )

    assert app.status_var.get() == "Indexing 2/5 [added=1 skipped=1] docs/two.md"


def test_sync_progress_updates_unit_level_status(tmp_path: Path):
    app = app_shell(tmp_path)

    app._show_sync_progress(
        SyncProgress(
            phase="ocr",
            processed=0,
            total=1,
            relative_path="docs/scanned.pdf",
            unit_processed=2,
            unit_total=5,
            detail="pdf_ocr_text",
        )
    )

    assert (
        app.status_var.get()
        == "OCR 0/1 unit=2/5 pdf_ocr_text docs/scanned.pdf"
    )
    assert app.progress.configured[-1] == {
        "mode": "determinate",
        "maximum": 5,
        "value": 2,
    }


def test_index_report_includes_ocr_table_counters(tmp_path: Path):
    app = app_shell(tmp_path)

    app._show_sync_report(
        SyncReport(
            added=1,
            ocr_attempted=3,
            ocr_succeeded=2,
            ocr_empty=1,
            table_attempted=4,
            table_succeeded=3,
            table_empty=1,
        )
    )

    assert "ocr=2/3 empty=1" in app.status_var.get()
    assert "tables=3/4 empty=1" in app.status_var.get()


def test_index_report_with_failures_warns_user(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    warnings = []
    monkeypatch.setattr(
        ui.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )

    app._show_sync_report(
        SyncReport(
            added=1,
            failed=2,
            failures=[
                SyncFailure(
                    relative_path="docs/broken.pdf",
                    error_type="RuntimeError",
                    message="failed",
                )
            ],
        )
    )

    assert app.status_var.get().startswith("Indexed with errors")
    assert "failed=2" in app.status_var.get()
    assert warnings == [
        (
            "LocalLens",
            "2 files failed during indexing.\n- docs/broken.pdf: RuntimeError",
        )
    ]


def test_run_error_restores_ui_state_and_reports_error(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    errors = []

    def showerror(title, message):
        assert app.progress.stopped == 1
        assert app.action_buttons[0].states[-1] == ui.tk.NORMAL
        errors.append((title, message))

    monkeypatch.setattr(
        ui.messagebox,
        "showerror",
        showerror,
    )

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    monkeypatch.setattr(ui.threading, "Thread", ImmediateThread)

    def fail_job():
        raise RuntimeError("service failed")

    app._run("Working...", fail_job, lambda result: None)
    app.root.run_callbacks()

    assert errors == [("LocalLens", "service failed")]
    assert app.status_var.get() == "Error"
    assert app.progress.started == [12]
    assert app.progress.stopped == 1
    assert app.action_buttons[0].states == [ui.tk.DISABLED, ui.tk.NORMAL]


def test_search_busy_state_does_not_enable_cancel(monkeypatch, tmp_path: Path):
    app = app_shell(tmp_path)
    app.folder_var.set(str(tmp_path))
    app.query_var.set("privacy")

    def hold_run(status, fn, on_success, cancellable=False):
        app._set_busy(status, cancellable=cancellable)

    app._run = hold_run
    monkeypatch.setattr(ui, "SearchService", lambda settings: None)

    app.search()

    assert app.cancel_button.states[-1] == ui.tk.DISABLED


def test_run_error_marks_retry_available_when_action_exists(
    monkeypatch, tmp_path: Path
):
    app = app_shell(tmp_path)
    app.last_retry = lambda: None
    errors = []
    monkeypatch.setattr(
        ui.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
    )

    app._show_error("failed")

    assert errors == [("LocalLens", "failed")]
    assert app.status_var.get() == "Error - retry available"
    assert app.retry_button.states[-1] == ui.tk.NORMAL


def test_success_callback_error_restores_ui_state_and_reports_error(
    monkeypatch, tmp_path: Path
):
    app = app_shell(tmp_path)
    errors = []

    def showerror(title, message):
        assert app.progress.stopped == 1
        assert app.action_buttons[0].states[-1] == ui.tk.NORMAL
        errors.append((title, message))

    monkeypatch.setattr(ui.messagebox, "showerror", showerror)

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    monkeypatch.setattr(ui.threading, "Thread", ImmediateThread)

    def render_failure(result):
        raise RuntimeError(f"{result} render failed")

    app._run("Working...", lambda: "result", render_failure)
    app.root.run_callbacks()

    assert errors == [("LocalLens", "result render failed")]
    assert app.status_var.get() == "Error"
    assert app.progress.started == [12]
    assert app.progress.stopped == 1
    assert app.action_buttons[0].states == [ui.tk.DISABLED, ui.tk.NORMAL]
