"""P6 Library UI MVP — reads library_items table via LibraryVault only."""
import flet as ft
import os, platform, subprocess
from pathlib import Path
from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR

LIBRARY_PAGE_SIZE = 30

FILTER_OPTIONS = [
    ("__all__", "All"),
    ("has_audio", "With Audio"),
    ("missing_cover", "No Cover"),
    ("warnings", "Warnings"),
]

def safe_update(control):
    try:
        if control and hasattr(control, 'page') and control.page:
            control.update()
    except Exception:
        pass

def fmt_size(b):
    if b >= 1_000_000_000: return f"{b/1_000_000_000:.1f} GB"
    if b >= 1_000_000: return f"{b/1_000_000:.0f} MB"
    if b >= 1_000: return f"{b/1_000:.0f} KB"
    return f"{b} B"


class LibraryView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True; self.padding = 10

        self._current_page = 0; self._current_filter = "__all__"
        self._summary = {}

        self.search_input = ft.TextField(hint_text="Search RJ / folder...", border_radius=10, expand=True,
                                         on_change=self.on_search, on_submit=self.on_search)

        self.filter_chips = ft.Row([], wrap=True, spacing=5)
        self.summary_bar = ft.Text("", size=12, color="grey")
        self.page_info = ft.Text("", size=12, color="grey")
        self.btn_prev = ft.TextButton(content=ft.Text("Prev", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(-1))
        self.btn_next = ft.TextButton(content=ft.Text("Next", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(1))

        self.grid = ft.GridView(expand=True, runs_count=4, max_extent=220,
                                child_aspect_ratio=0.85, spacing=8, run_spacing=8)

        self.content = ft.Column([
            ft.Text("Resource Library", size=28, weight=ft.FontWeight.BOLD),
            self.summary_bar,
            ft.Row([self.search_input], spacing=10),
            ft.Container(content=self.filter_chips, padding=5),
            ft.Row([ft.Text("", expand=True), self.page_info, self.btn_prev, self.btn_next],
                   alignment=ft.MainAxisAlignment.END),
            ft.Divider(height=1, color="transparent"),
            self.grid,
        ], expand=True)

    def _refresh_summary(self):
        try:
            self._summary = self.app_controller.db.get_library_summary()
            self.summary_bar.value = (
                f"Total: {self._summary.get('total_works',0)} works, "
                f"{self._summary.get('total_files',0)} files, "
                f"{fmt_size(self._summary.get('total_size',0))} | "
                f"Audio: {self._summary.get('with_audio',0)} | "
                f"Cover: {self._summary.get('with_cover',0)} | "
                f"Warnings: {self._summary.get('with_warnings',0)}"
            )
        except Exception:
            self.summary_bar.value = "Library not available"

    def _build_filter_chips(self):
        self.filter_chips.controls.clear()
        for key, label in FILTER_OPTIONS:
            is_active = self._current_filter == key
            chip = ft.Chip(label=ft.Text(label, size=12, color="white"),
                           bgcolor=ACCENT_PRIMARY if is_active else None,
                           shape=ft.RoundedRectangleBorder(radius=10),
                           on_click=lambda e, k=key: self._on_filter_chip(k))
            self.filter_chips.controls.append(chip)

    def _on_filter_chip(self, key):
        self._current_filter = key; self._current_page = 0
        self.load_library()

    def _go_page(self, delta):
        new_page = self._current_page + delta
        if new_page < 0: return
        self._current_page = new_page; self.load_library()

    def load_library(self):
        self._refresh_summary()
        self._build_filter_chips()
        self.grid.controls.clear()

        fa = self._current_filter == "has_audio"
        fc = self._current_filter == "missing_cover"
        fw = self._current_filter == "warnings"
        search = self.search_input.value or ""
        offset = self._current_page * LIBRARY_PAGE_SIZE

        items = self.app_controller.db.get_library_items(
            search=search, offset=offset, limit=LIBRARY_PAGE_SIZE,
            filter_audio=fa, filter_cover=fc, filter_warnings=fw)
        total = self.app_controller.db.count_library_items(
            search=search, filter_audio=fa, filter_cover=fc, filter_warnings=fw)
        total_pages = max(1, (total + LIBRARY_PAGE_SIZE - 1) // LIBRARY_PAGE_SIZE)

        for item in items:
            rj_id = item["rj_id"]
            total_files = item.get("total_files", 0)
            total_size = item.get("total_size", 0)
            audio_count = item.get("audio_count", 0)
            has_audio = item.get("has_audio", 0)
            has_cover = item.get("has_cover", 0)
            folder_path = item.get("folder_path", "")
            folder_name = item.get("folder_name", rj_id)
            warnings_raw = item.get("warnings_json", "[]")

            # Simplify folder name display
            display_name = folder_name
            if len(display_name) > 30:
                display_name = display_name[:28] + ".."

            # Warning count
            try:
                warn_list = __import__('json').loads(warnings_raw) if warnings_raw else []
                warn_count = len(warn_list)
            except Exception:
                warn_count = 0

            badges = [
                ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=12, color=ACCENT_PRIMARY),
                ft.Text(f"{total_files}f / {fmt_size(total_size)}", size=10, color="grey"),
            ]
            if audio_count > 0:
                badges.append(ft.Container(content=ft.Text(f"{audio_count} audio", size=9, color="white"),
                                           bgcolor=SUCCESS, border_radius=4,
                                           padding=ft.padding.symmetric(horizontal=4, vertical=1)))
            if not has_cover:
                badges.append(ft.Container(content=ft.Text("no cover", size=9, color="white"),
                                           bgcolor=WARNING, border_radius=4,
                                           padding=ft.padding.symmetric(horizontal=4, vertical=1)))
            if warn_count > 0:
                badges.append(ft.Container(content=ft.Text(f"{warn_count}w", size=9, color="white"),
                                           bgcolor=ERROR, border_radius=4,
                                           padding=ft.padding.symmetric(horizontal=4, vertical=1)))

            card = ft.Column([
                ft.Row(badges, wrap=True, spacing=3),
                ft.Text(display_name, size=11, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                        color="white" if has_audio else "grey"),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=3)

            container = Styles.glass_container(card, padding=8)
            if folder_path:
                container.on_click = lambda e, p=folder_path: self.open_folder(p)
            self.grid.controls.append(container)

        start = offset + 1 if items else 0
        end = offset + len(items)
        self.page_info.value = f"Page {self._current_page + 1}/{total_pages} ({start}-{end} of {total})"
        self.btn_prev.disabled = self._current_page == 0
        self.btn_next.disabled = (self._current_page + 1) >= total_pages
        safe_update(self.grid); safe_update(self.page_info); safe_update(self.btn_prev); safe_update(self.btn_next)

    def on_search(self, e=None):
        self._current_page = 0; self.load_library()

    def open_folder(self, path_str):
        path = Path(path_str)
        if path.exists():
            try:
                if platform.system() == "Windows": os.startfile(path)
                elif platform.system() == "Darwin": subprocess.run(["open", path])
                else: subprocess.run(["xdg-open", path])
            except Exception: pass
