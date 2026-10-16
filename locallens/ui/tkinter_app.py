from __future__ import annotations

from dataclasses import replace
import os
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from locallens.core.config import Settings
from locallens.ingestion.fingerprint import root_id_for_path
from locallens.ingestion.scanner import SUPPORTED_EXTENSIONS
from locallens.indexing.sync_service import SyncService
from locallens.retrieval.filters import normalize_path_prefix, normalize_top_k
from locallens.retrieval.search_service import SearchService


EMPTY_RESULT_ROW = ("", "", "", "", "No results")


def normalize_ext_filter(value: str) -> str | None:
    ext = value.strip().lower()
    if not ext:
        return None
    return ext if ext.startswith(".") else f".{ext}"


def normalize_modality_filter(value: str) -> str | None:
    return None if value == "all" else value


def normalize_top_k_filter(value: str) -> int:
    return normalize_top_k(value)


def normalize_path_prefix_filter(value: str) -> str | None:
    return normalize_path_prefix(value) or None


def result_row(item) -> tuple[str, str, str, str, str]:
    return (
        f"{item.score:.4f}",
        _result_type_label(item),
        item.relative_path,
        str(item.page_no or ""),
        item.snippet,
    )


def selected_result_path(
    root_path: Path | None,
    results: list,
    selected_index: int,
) -> Path | None:
    if root_path is None or selected_index < 0 or selected_index >= len(results):
        return None
    relative_path = Path(results[selected_index].relative_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return None
    root = root_path.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


class LocalLensApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = Settings.from_env()
        self.last_results = []
        self.result_root_path: Path | None = None
        self.action_buttons = []
        self.cancel_requested = False
        self.last_retry = None
        self.cancel_button = None
        self.retry_button = None
        self.root.title("LocalLens")
        self.root.geometry("1120x720")
        self.root.minsize(860, 560)

        self.folder_var = tk.StringVar()
        self.query_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.modality_var = tk.StringVar(value="all")
        self.ext_var = tk.StringVar()
        self.top_k_var = tk.StringVar(value="10")
        self.path_prefix_var = tk.StringVar()
        self.pdf_ocr_var = tk.BooleanVar(value=self.settings.pdf_ocr_mode == "local-ocr")
        self.pdf_table_var = tk.BooleanVar(
            value=self.settings.pdf_table_mode == "local-table"
        )

        self._build_layout()

    def _build_layout(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        folder_row = ttk.Frame(frame)
        folder_row.pack(fill=tk.X)
        ttk.Entry(folder_row, textvariable=self.folder_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        folder_button = ttk.Button(folder_row, text="Folder", command=self.choose_folder)
        index_button = ttk.Button(folder_row, text="Index", command=self.index_folder)
        reindex_button = ttk.Button(folder_row, text="Reindex", command=self.index_folder)
        purge_button = ttk.Button(folder_row, text="Purge", command=self.purge)
        folder_button.pack(side=tk.LEFT, padx=(8, 0))
        index_button.pack(side=tk.LEFT, padx=(8, 0))
        reindex_button.pack(side=tk.LEFT, padx=(8, 0))
        purge_button.pack(side=tk.LEFT, padx=(8, 0))
        self.action_buttons.extend(
            [folder_button, index_button, reindex_button, purge_button]
        )

        options_row = ttk.Frame(frame)
        options_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(options_row, text="PDF opt-in").pack(side=tk.LEFT)
        ttk.Checkbutton(
            options_row,
            text="OCR",
            variable=self.pdf_ocr_var,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(
            options_row,
            text="Tables",
            variable=self.pdf_table_var,
        ).pack(side=tk.LEFT, padx=(8, 0))

        search_row = ttk.Frame(frame)
        search_row.pack(fill=tk.X, pady=(10, 8))
        ttk.Entry(search_row, textvariable=self.query_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Label(search_row, text="Modality").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Combobox(
            search_row,
            textvariable=self.modality_var,
            values=("all", "text", "image"),
            width=8,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(search_row, text="Extension").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(search_row, textvariable=self.ext_var, width=10).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Label(search_row, text="Top-K").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Spinbox(
            search_row,
            textvariable=self.top_k_var,
            from_=1,
            to=100,
            width=6,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(search_row, text="Path prefix").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(search_row, textvariable=self.path_prefix_var, width=18).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        search_button = ttk.Button(search_row, text="Search", command=self.search)
        search_button.pack(side=tk.LEFT, padx=(8, 0))
        open_button = ttk.Button(search_row, text="Open File", command=self.open_selected)
        open_button.pack(side=tk.LEFT, padx=(8, 0))
        self.cancel_button = ttk.Button(
            search_row, text="Cancel", command=self.cancel_current
        )
        self.cancel_button.pack(side=tk.LEFT, padx=(8, 0))
        self.retry_button = ttk.Button(search_row, text="Retry", command=self.retry_last)
        self.retry_button.pack(side=tk.LEFT, padx=(8, 0))
        self.action_buttons.append(search_button)
        self.action_buttons.append(open_button)
        self.cancel_button.configure(state=tk.DISABLED)
        self.retry_button.configure(state=tk.DISABLED)

        columns = ("score", "modality", "path", "page", "snippet")
        self.results = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        self.results.heading("score", text="Score")
        self.results.heading("modality", text="Type")
        self.results.heading("path", text="Path")
        self.results.heading("page", text="Page")
        self.results.heading("snippet", text="Snippet")
        self.results.column("score", width=82, stretch=False, anchor=tk.E)
        self.results.column("modality", width=82, stretch=False)
        self.results.column("path", width=270)
        self.results.column("page", width=64, stretch=False, anchor=tk.CENTER)
        self.results.column("snippet", width=560)
        self.results.bind("<Double-1>", self.open_selected)
        self.results.pack(fill=tk.BOTH, expand=True)

        bottom = ttk.Frame(frame)
        bottom.pack(fill=tk.X, pady=(8, 0))
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=180)
        self.progress.pack(side=tk.LEFT)
        ttk.Label(bottom, textvariable=self.status_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0)
        )

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory()
        if selected:
            self.folder_var.set(selected)

    def index_folder(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("LocalLens", "Select a folder first.")
            return
        settings = self._index_settings()
        self.last_retry = lambda folder=folder, settings=settings: self._index_with(
            folder, settings
        )
        self._index_with(folder, settings)

    def _index_with(self, folder: str, settings: Settings) -> None:
        status = f"Indexing... {_pdf_option_summary(settings)}"

        def job():
            service = SyncService(settings)
            try:
                return service.sync_folder(folder, progress_callback=self._sync_progress)
            finally:
                service.store.close()

        self._run(status, job, self._show_sync_report, cancellable=True)

    def search(self) -> None:
        query = self.query_var.get().strip()
        if not query:
            messagebox.showwarning("LocalLens", "Enter a search query.")
            return
        modality = normalize_modality_filter(self.modality_var.get())
        ext = normalize_ext_filter(self.ext_var.get())
        try:
            top_k = normalize_top_k_filter(self.top_k_var.get())
            path_prefix = normalize_path_prefix_filter(self.path_prefix_var.get())
        except ValueError as exc:
            messagebox.showwarning("LocalLens", str(exc))
            return
        if ext and ext not in SUPPORTED_EXTENSIONS:
            messagebox.showwarning("LocalLens", f"Unsupported extension filter: {ext}")
            return
        folder = self.folder_var.get().strip()
        root_path = Path(folder).resolve() if folder else None
        root_id = root_id_for_path(root_path) if root_path else None
        self.last_retry = (
            lambda query=query,
            top_k=top_k,
            modality=modality,
            ext=ext,
            path_prefix=path_prefix,
            root_path=root_path,
            root_id=root_id: self._search_with(
                query,
                top_k,
                modality,
                ext,
                path_prefix,
                root_path,
                root_id,
            )
        )
        self._search_with(query, top_k, modality, ext, path_prefix, root_path, root_id)

    def _search_with(
        self,
        query: str,
        top_k: int,
        modality: str | None,
        ext: str | None,
        path_prefix: str | None,
        root_path: Path | None,
        root_id: str | None,
    ) -> None:
        self.result_root_path = None
        self.last_results = []
        self.results.delete(*self.results.get_children())

        def job():
            service = SearchService(self.settings)
            try:
                return service.search(
                    query,
                    top_k=top_k,
                    modality=modality,
                    root_id=root_id,
                    ext=ext,
                    path_prefix=path_prefix,
                )
            finally:
                service.store.close()

        def on_success(results):
            self.result_root_path = root_path
            self._show_results(results)

        self._run("Searching...", job, on_success)

    def purge(self) -> None:
        if not messagebox.askyesno("LocalLens", "Remove local index data?"):
            return

        def job():
            service = SyncService(self.settings)
            try:
                service.purge()
                return "Purged"
            finally:
                service.store.close()

        self._run("Purging...", job, lambda result: self._set_status(str(result)))

    def cancel_current(self) -> None:
        self.cancel_requested = True
        self.status_var.set("Cancel requested; waiting for current step")
        if self.cancel_button is not None:
            self.cancel_button.configure(state=tk.DISABLED)

    def retry_last(self) -> None:
        if self.last_retry is not None:
            self.last_retry()

    def open_selected(self, _event=None) -> None:
        selected = self.results.selection()
        if not selected:
            return
        try:
            index = self.results.index(selected[0])
        except Exception:
            messagebox.showerror("LocalLens", "Selected result is no longer available.")
            return
        if index >= len(self.last_results):
            return
        path = selected_result_path(self.result_root_path, self.last_results, index)
        if path is None:
            messagebox.showerror("LocalLens", "Could not resolve result path.")
            return
        if not path.exists():
            messagebox.showerror("LocalLens", f"File not found: {path.name}")
            return
        try:
            os.startfile(path)
        except OSError:
            messagebox.showerror("LocalLens", f"Could not open file: {path.name}")

    def _run(self, status: str, fn, on_success, cancellable: bool = False) -> None:
        self._set_busy(status, cancellable=cancellable)

        def job():
            try:
                result = fn()
                self.root.after(
                    0, lambda: self._finish_success(on_success, result)
                )
            except Exception as exc:
                error_message = str(exc)
                self.root.after(0, lambda: self._show_error(error_message))

        threading.Thread(target=job, daemon=True).start()

    def _finish_success(self, on_success, result) -> None:
        try:
            on_success(result)
        except Exception as exc:
            self._show_error(str(exc))

    def _show_error(self, message: str) -> None:
        status = "Error - retry available" if self.last_retry is not None else "Error"
        self._set_status(status)
        messagebox.showerror("LocalLens", message)

    def _show_sync_report(self, report) -> None:
        if report.cancelled:
            self._set_status("Indexing cancelled")
            return
        status = (
            "Indexed "
            f"added={report.added} updated={report.updated} "
            f"deleted={report.deleted} skipped={report.skipped} "
            f"excluded={report.excluded} failed={report.failed}"
        )
        if report.ocr_attempted or report.table_attempted or report.vlm_attempted:
            status = (
                f"{status} "
                f"ocr={report.ocr_succeeded}/{report.ocr_attempted}"
                f" empty={report.ocr_empty} "
                f"tables={report.table_succeeded}/{report.table_attempted}"
                f" empty={report.table_empty} "
                f"vlm={report.vlm_succeeded}/{report.vlm_attempted}"
                f" empty={report.vlm_empty} failed={report.vlm_failed}"
            )
        status = f"{status} {_pdf_option_summary(self._index_settings())}"
        if report.failed:
            status = f"Indexed with errors {status.removeprefix('Indexed ')}"
        self._set_status(status)
        if report.failed:
            details = "\n".join(
                f"- {failure.relative_path}: {failure.error_type}"
                for failure in report.failures[:5]
            )
            suffix = f"\n{details}" if details else ""
            messagebox.showwarning(
                "LocalLens",
                f"{report.failed} files failed during indexing.{suffix}",
            )

    def _sync_progress(self, progress) -> None:
        if self.cancel_requested:
            return False
        self.root.after(0, lambda: self._show_sync_progress(progress))
        return True

    def _show_sync_progress(self, progress) -> None:
        if progress.phase == "complete":
            return
        phase_label = {
            "scan": "Scanning",
            "indexing": "Indexing",
            "extracting": "Extracting",
            "embedding": "Embedding",
            "ocr": "OCR",
            "table": "Table",
            "upserting": "Saving",
            "indexed": "Indexed",
            "skipped": "Skipped",
            "failed": "Failed",
            "deleted": "Deleted",
        }.get(progress.phase, progress.phase.title())
        path = f" {progress.relative_path}" if progress.relative_path else ""
        unit = ""
        if progress.unit_total:
            detail = f" {progress.detail}" if progress.detail else ""
            unit = f" unit={progress.unit_processed}/{progress.unit_total}{detail}"
        counters = _progress_counter_summary(progress)
        failed = f" failed={progress.failed}" if progress.failed else ""
        self.status_var.set(
            f"{phase_label} {progress.processed}/{progress.total}"
            f"{unit}{counters}{path}{failed}"
        )
        maximum = progress.unit_total or progress.total
        value = progress.unit_processed if progress.unit_total else progress.processed
        self.progress.configure(
            mode="determinate",
            maximum=max(maximum, 1),
            value=value,
        )

    def _show_results(self, results) -> None:
        self.last_results = list(results)
        self.results.delete(*self.results.get_children())
        if not results:
            self.results.insert("", tk.END, values=EMPTY_RESULT_ROW)
            self._set_status("0 results")
            return
        for item in results:
            self.results.insert("", tk.END, values=result_row(item))
        self._set_status(f"{len(results)} results")

    def _set_busy(self, status: str, cancellable: bool = False) -> None:
        self.cancel_requested = False
        self.status_var.set(status)
        _set_widget_state(self.action_buttons, tk.DISABLED)
        if self.retry_button is not None:
            self.retry_button.configure(state=tk.DISABLED)
        if self.cancel_button is not None:
            self.cancel_button.configure(state=tk.NORMAL if cancellable else tk.DISABLED)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

    def _set_status(self, status: str) -> None:
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0)
        _set_widget_state(self.action_buttons, tk.NORMAL)
        if self.cancel_button is not None:
            self.cancel_button.configure(state=tk.DISABLED)
        if self.retry_button is not None and self.last_retry is not None:
            self.retry_button.configure(state=tk.NORMAL)
        self.status_var.set(status)

    def _index_settings(self) -> Settings:
        return replace(
            self.settings,
            pdf_ocr_mode="local-ocr" if self.pdf_ocr_var.get() else "off",
            pdf_table_mode="local-table" if self.pdf_table_var.get() else "off",
        )


def main() -> None:
    root = tk.Tk()
    LocalLensApp(root)
    root.mainloop()


def _set_widget_state(widgets, state: str) -> None:
    for widget in widgets:
        widget.configure(state=state)


def _pdf_option_summary(settings: Settings) -> str:
    ocr = "on" if settings.pdf_ocr_mode == "local-ocr" else "off"
    tables = "on" if settings.pdf_table_mode == "local-table" else "off"
    return f"PDF OCR={ocr} Tables={tables}"


def _result_type_label(item) -> str:
    unit_type = getattr(item, "unit_type", "")
    return f"{item.modality}/{unit_type}" if unit_type else item.modality


def _progress_counter_summary(progress) -> str:
    counters = {
        "added": progress.added,
        "updated": progress.updated,
        "deleted": progress.deleted,
        "skipped": progress.skipped,
        "excluded": progress.excluded,
    }
    parts = [f"{name}={value}" for name, value in counters.items() if value]
    return f" [{' '.join(parts)}]" if parts else ""
