"""P6 Library UI MVP ? reads library_items table via LibraryVault only."""
import json
import os
import platform
import subprocess
from pathlib import Path

import flet as ft

from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR, BG_SURFACE_LIGHT

LIBRARY_PAGE_SIZE = 30
STATUS_LABELS = {
    "completed": ("Completed", SUCCESS),
    "partial": ("Partial", WARNING),
    "external": ("External", ACCENT_PRIMARY),
    "verified": ("Verified", SUCCESS),
    "missing": ("Missing", ERROR),
}
FILTER_OPTIONS = [
    ("__all__", "\u5168\u90e8"),
    ("has_audio", "\u6709\u97f3\u9891"),
    ("missing_cover", "\u65e0\u5c01\u9762"),
    ("warnings", "\u6709\u8b66\u544a"),
]
COVER_CANDIDATES = (
    "cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
    "main.jpg", "main.png", "package.jpg", "package.png",
)


def safe_update(control):
    try:
        if control and hasattr(control, "page") and control.page:
            control.update()
    except Exception:
        pass


def fmt_size(b):
    if b >= 1_000_000_000:
        return f"{b/1_000_000_000:.1f} GB"
    if b >= 1_000_000:
        return f"{b/1_000_000:.0f} MB"
    if b >= 1_000:
        return f"{b/1_000:.0f} KB"
    return f"{b} B"


class LibraryView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True
        self.padding = 10

        self._current_page = 0
        self._current_filter = "__all__"
        self._summary = {}

        self.search_input = ft.TextField(
            hint_text="\u641c\u7d22 RJ / \u6587\u4ef6\u5939...",
            border_radius=10,
            expand=True,
            on_change=self.on_search,
            on_submit=self.on_search,
        )

        self.filter_chips = ft.Row([], wrap=True, spacing=6)
        self.summary_bar = ft.Text("", size=12, color="grey")
        self.page_info = ft.Text("", size=12, color="grey")
        self.btn_prev = ft.TextButton(content=ft.Text("\u4e0a\u4e00\u9875", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(-1))
        self.btn_next = ft.TextButton(content=ft.Text("\u4e0b\u4e00\u9875", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(1))

        self.grid = ft.GridView(
            expand=True,
            max_extent=260,
            child_aspect_ratio=0.72,
            spacing=12,
            run_spacing=12,
            padding=ft.padding.only(bottom=16),
        )

        self.content = ft.Column([
            ft.Text("\u8d44\u6e90\u5e93", size=28, weight=ft.FontWeight.BOLD),
            self.summary_bar,
            ft.Row([self.search_input], spacing=10),
            ft.Container(content=self.filter_chips, padding=ft.padding.only(top=4, bottom=4)),
            ft.Row([
                ft.Text("\u5c01\u9762\u4f18\u5148\u5c55\u793a\uff0c\u70b9\u51fb\u5361\u7247\u6253\u5f00\u76ee\u5f55", size=12, color="grey"),
                ft.Container(expand=True),
                self.page_info,
                self.btn_prev,
                self.btn_next,
            ], alignment=ft.MainAxisAlignment.END),
            self.grid,
        ], expand=True, spacing=12)

    def _refresh_summary(self):
        try:
            self._summary = self.app_controller.db.get_library_summary()
            self.summary_bar.value = (
                f"\u5171 {self._summary.get('total_works', 0)} \u4e2a\u4f5c\u54c1, "
                f"{self._summary.get('total_files', 0)} \u6587\u4ef6, "
                f"{fmt_size(self._summary.get('total_size', 0))} | "
                f"\u97f3\u9891: {self._summary.get('with_audio', 0)} | "
                f"\u5c01\u9762: {self._summary.get('with_cover', 0)} | "
                f"\u8b66\u544a: {self._summary.get('with_warnings', 0)}"
            )
        except Exception:
            self.summary_bar.value = "Library not available"

    def _build_filter_chips(self):
        self.filter_chips.controls.clear()
        for key, label in FILTER_OPTIONS:
            is_active = self._current_filter == key
            chip = ft.Chip(
                label=ft.Text(label, size=12, color="white"),
                bgcolor=ACCENT_PRIMARY if is_active else None,
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda e, k=key: self._on_filter_chip(k),
            )
            self.filter_chips.controls.append(chip)

    def _on_filter_chip(self, key):
        self._current_filter = key
        self._current_page = 0
        self.load_library()

    def _go_page(self, delta):
        new_page = self._current_page + delta
        if new_page < 0:
            return
        self._current_page = new_page
        self.load_library()

    def _resolve_cover_source(self, folder_path: str, has_cover: int, rj_id: str = ""):
        # 1. Local disk scan (fastest, no proxy)
        if folder_path and has_cover:
            root = Path(folder_path)
            if root.exists():
                for name in COVER_CANDIDATES:
                    candidate = root / name
                    if candidate.exists():
                        return str(candidate)
                try:
                    for child in root.iterdir():
                        if child.is_file() and child.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                            lower_name = child.name.lower()
                            if "cover" in lower_name or "package" in lower_name or "main" in lower_name:
                                return str(child)
                except Exception:
                    pass

        # 2. Metadata cache fallback (works for works without local cover files)
        if rj_id:
            try:
                cached = self.app_controller.db.get_metadata_cache(rj_id)
                if cached and cached.get("cover_url"):
                    return cached["cover_url"]
            except Exception:
                pass
        return None

    def _build_cover(self, folder_path: str, has_cover: int, rj_id: str = ""):
        src = self._resolve_cover_source(folder_path, has_cover, rj_id)
        if src:
            return ft.Container(
                height=180,
                border_radius=14,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                bgcolor=BG_SURFACE_LIGHT,
                content=ft.Image(src=src, fit=ft.ImageFit.COVER),
            )
        return ft.Container(
            height=180,
            border_radius=14,
            bgcolor=ft.colors.with_opacity(0.55, BG_SURFACE_LIGHT),
            alignment=ft.alignment.center,
            content=ft.Column([
                ft.Icon(ft.icons.IMAGE_NOT_SUPPORTED_OUTLINED, color=WARNING, size=36),
                ft.Text("\u65e0\u5c01\u9762", size=12, color="grey"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
        )

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
            search=search,
            offset=offset,
            limit=LIBRARY_PAGE_SIZE,
            filter_audio=fa,
            filter_cover=fc,
            filter_warnings=fw,
        )
        total = self.app_controller.db.count_library_items(
            search=search,
            filter_audio=fa,
            filter_cover=fc,
            filter_warnings=fw,
        )
        total_pages = max(1, (total + LIBRARY_PAGE_SIZE - 1) // LIBRARY_PAGE_SIZE)

        for item in items:
            rj_id = item["rj_id"]
            total_files = item.get("total_files", 0)
            total_size = item.get("total_size", 0)
            audio_count = item.get("audio_count", 0)
            has_cover = item.get("has_cover", 0)
            folder_path = item.get("folder_path", "")
            folder_name = item.get("folder_name", rj_id)
            warnings_raw = item.get("warnings_json", "[]")

            display_name = folder_name if len(folder_name) <= 36 else folder_name[:33] + "..."
            try:
                warn_list = json.loads(warnings_raw) if warnings_raw else []
                warn_count = len(warn_list)
            except Exception:
                warn_count = 0

            badge_controls = [
                ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=14, color=ACCENT_PRIMARY),
                ft.Text(f"{total_files}f / {fmt_size(total_size)}", size=11, color="grey"),
            ]
            if audio_count > 0:
                badge_controls.append(
                    ft.Container(
                        content=ft.Text(f"{audio_count} \u97f3\u9891", size=9, color="white"),
                        bgcolor=SUCCESS,
                        border_radius=999,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    )
                )
            if not has_cover:
                badge_controls.append(
                    ft.Container(
                        content=ft.Text("no cover", size=9, color="white"),
                        bgcolor=WARNING,
                        border_radius=999,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    )
                )
            if warn_count > 0:
                badge_controls.append(
                    ft.Container(
                        content=ft.Text(f"{warn_count}w", size=9, color="white"),
                        bgcolor=ERROR,
                        border_radius=999,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    )
                )

            card = ft.Column([
                self._build_cover(folder_path, has_cover, rj_id),
                ft.Row(badge_controls, wrap=True, spacing=4),
                ft.Text(display_name, size=13, weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=8)

            container = Styles.glass_container(card, padding=10)
            if folder_path:
                container.on_click = lambda e, p=folder_path: self.open_folder(p)
            self.grid.controls.append(container)

        start = offset + 1 if items else 0
        end = offset + len(items)
        self.page_info.value = f"Page {self._current_page + 1}/{total_pages} ({start}-{end} of {total})"
        self.btn_prev.disabled = self._current_page == 0
        self.btn_next.disabled = (self._current_page + 1) >= total_pages
        try:
            if self.grid.page: self.grid.update()
            if self.page_info.page: self.page_info.update()
            if self.btn_prev.page: self.btn_prev.update()
            if self.btn_next.page: self.btn_next.update()
        except Exception:
            pass

    def on_search(self, e=None):
        self._current_page = 0
        self.load_library()

    def open_folder(self, path_str):
        path = Path(path_str)
        if path.exists():
            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.run(["open", path])
                else:
                    subprocess.run(["xdg-open", path])
            except Exception:
                pass
