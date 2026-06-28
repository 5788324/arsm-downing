import json
import os
import platform
import subprocess
from pathlib import Path

import flet as ft

from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR, BG_SURFACE_LIGHT

LIBRARY_PAGE_SIZE = 24
E_ROOT = r"E:\arsm"
OLD_ROOT = r"C:\Users\YANG\Music\arsm.one"
FAKE_RJ = {"RJ00000000", "RJ00123456"}
ALIAS_RJ = {"RJ00323125", "RJ323125"}
COVER_CANDIDATES = (
    "cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
    "main.jpg", "main.png", "package.jpg", "package.png",
)
ANOMALY_LABELS = {
    "all": "\u5168\u90e8\u5f02\u5e38",
    "fake_or_test": "\u6d4b\u8bd5RJ",
    "alias": "\u522b\u540dRJ",
    "missing_path": "\u8def\u5f84\u4e22\u5931",
    "not_indexed": "E\u76d8\u672a\u7d22\u5f15",
    "old_root": "\u65e7\u5e93\u6b8b\u7559",
    "empty_directory": "\u7a7a\u76ee\u5f55",
    "no_images": "\u65e0\u56fe\u7247",
    "path_mismatch": "\u8def\u5f84\u4e0d\u5339\u914d",
}
WARNING_LABELS = {
    "no_images": "\u65e0\u56fe\u7247",
    "empty_directory": "\u7a7a\u76ee\u5f55",
    "path_mismatch_with_works_local_path": "\u8def\u5f84\u4e0d\u5339\u914d",
}


def fmt_size(num):
    num = int(num or 0)
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f} GB"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.0f} MB"
    if num >= 1_000:
        return f"{num / 1_000:.0f} KB"
    return f"{num} B"


def row_get(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        value = row.get(key, default)
        return default if value is None else value
    try:
        value = row[key]
    except Exception:
        return default
    return default if value is None else value


def is_on_e(path):
    return bool(path) and str(path).replace("\\", "/").startswith(E_ROOT.replace("\\", "/"))


def is_old_lib(path):
    return bool(path) and str(path).replace("\\", "/").startswith(OLD_ROOT.replace("\\", "/"))


class LibraryView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True
        self.padding = 10
        self._current_page = 0
        self._mode = "cards"
        self._anomaly_filter = "all"
        self._items = []
        self._lib_ids = set()

        self.search_input = ft.TextField(
            hint_text="\u641c\u7d22 RJ / \u6587\u4ef6\u5939...",
            border_radius=8,
            expand=True,
            on_change=self.on_search,
            on_submit=self.on_search,
        )
        self.summary_bar = ft.Text("", size=12, color="grey")
        self.page_info = ft.Text("", size=12, color="grey")
        self.btn_prev = ft.TextButton(content=ft.Text("\u4e0a\u4e00\u9875", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(-1))
        self.btn_next = ft.TextButton(content=ft.Text("\u4e0b\u4e00\u9875", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(1))
        self.mode_toggle = ft.Row(spacing=8)
        self.anomaly_filter_row = ft.Row(spacing=6, wrap=True)
        self.grid = ft.GridView(expand=True, max_extent=300, child_aspect_ratio=1.18, spacing=12, run_spacing=12)

        self.content = ft.Column([
            ft.Text("\u8d44\u6e90\u5e93", size=28, weight=ft.FontWeight.BOLD),
            self.summary_bar,
            ft.Row([self.search_input], spacing=10),
            self.mode_toggle,
            self.anomaly_filter_row,
            ft.Row([ft.Text("", expand=True), self.page_info, self.btn_prev, self.btn_next], alignment=ft.MainAxisAlignment.END),
            ft.Divider(height=1, color="transparent"),
            self.grid,
        ], expand=True, spacing=8)

    def _copy_rj(self, rj_id):
        try:
            self.app_controller.page.set_clipboard(rj_id)
            self.app_controller.show_snack(f"\u5df2\u590d\u5236 {rj_id}")
        except Exception:
            pass

    def _build_mode_toggle(self):
        self.mode_toggle.controls.clear()
        for key, label in [("cards", "\u8d44\u6e90\u5e93"), ("anomalies", "\u5f02\u5e38")]:
            self.mode_toggle.controls.append(self._chip(label, self._mode == key, lambda e, k=key: self._set_mode(k)))

    def _build_anomaly_filters(self, counts):
        self.anomaly_filter_row.controls.clear()
        self.anomaly_filter_row.visible = self._mode == "anomalies"
        if self._mode != "anomalies":
            return
        for key in ["all", "alias", "missing_path", "not_indexed", "old_root", "empty_directory", "no_images", "path_mismatch"]:
            count = sum(counts.values()) if key == "all" else counts.get(key, 0)
            if key != "all" and count <= 0:
                continue
            label = f"{ANOMALY_LABELS[key]} {count}"
            self.anomaly_filter_row.controls.append(self._chip(label, self._anomaly_filter == key, lambda e, k=key: self._set_anomaly_filter(k)))

    def _chip(self, label, active, handler):
        return ft.Chip(
            label=ft.Text(label, size=12, color="white"),
            bgcolor=ACCENT_PRIMARY if active else None,
            shape=ft.RoundedRectangleBorder(radius=8),
            on_click=handler,
        )

    def _set_mode(self, mode):
        self._mode = mode
        self._current_page = 0
        self.load_library()

    def _set_anomaly_filter(self, key):
        self._anomaly_filter = key
        self._current_page = 0
        self.load_library()

    def on_search(self, e=None):
        self._current_page = 0
        self.load_library()

    def _go_page(self, delta):
        next_page = self._current_page + delta
        if next_page < 0:
            return
        self._current_page = next_page
        self.load_library()

    def load_library(self):
        self._build_mode_toggle()
        db = self.app_controller.db
        lib_summary = db.get_library_summary()
        self.summary_bar.value = (
            f"\u5171 {lib_summary.get('total_works', 0)} \u4e2a\u7d22\u5f15 | \u97f3\u9891 {lib_summary.get('with_audio', 0)} "
            f"| \u5c01\u9762 {lib_summary.get('with_cover', 0)} | \u8b66\u544a {lib_summary.get('with_warnings', 0)}"
        )

        self.grid.controls.clear()
        counts = {}
        if self._mode == "cards":
            self._items = self._load_card_items(db)
        else:
            all_items = self._load_anomaly_items(db)
            counts = self._count_anomaly_categories(all_items)
            self._items = all_items if self._anomaly_filter == "all" else [item for item in all_items if item["category"] == self._anomaly_filter]
        self._build_anomaly_filters(counts)

        total = len(self._items)
        total_pages = max(1, (total + LIBRARY_PAGE_SIZE - 1) // LIBRARY_PAGE_SIZE)
        if self._current_page >= total_pages:
            self._current_page = max(0, total_pages - 1)
        start = self._current_page * LIBRARY_PAGE_SIZE
        end = start + LIBRARY_PAGE_SIZE
        page_items = self._items[start:end]

        self.page_info.value = f"\u7b2c {self._current_page + 1}/{total_pages} \u9875 ({start + 1 if total else 0}-{min(end, total)} / {total})"
        self.btn_prev.disabled = self._current_page == 0
        self.btn_next.disabled = self._current_page + 1 >= total_pages

        for item in page_items:
            self.grid.controls.append(self._build_library_card(db, item) if self._mode == "cards" else self._build_anomaly_card(db, item))

        try:
            for control in (self.grid, self.summary_bar, self.page_info, self.mode_toggle, self.anomaly_filter_row):
                if control.page:
                    control.update()
        except Exception:
            pass

    def _load_card_items(self, db):
        search = self.search_input.value.strip()
        return [dict(item) for item in db.get_library_items(search=search)]

    def _load_anomaly_items(self, db):
        works = {row["rj_id"]: row for row in db.conn.execute("SELECT * FROM works").fetchall()}
        self._lib_ids = set(row[0] for row in db.conn.execute("SELECT rj_id FROM library_items").fetchall())
        anomalies = []
        search = self.search_input.value.strip().lower()

        for rj_id, work in works.items():
            lib_item = lib_data_get(db, rj_id)
            warnings = parse_warnings(lib_item)
            local_path = row_get(work, "local_path", "")
            category = None
            if rj_id in FAKE_RJ:
                category = "fake_or_test"
            elif rj_id in ALIAS_RJ:
                category = "alias"
            elif local_path and not os.path.exists(local_path):
                category = "missing_path"
            elif is_on_e(local_path) and rj_id not in self._lib_ids:
                category = "not_indexed"
            elif is_old_lib(local_path):
                category = "old_root"
            elif "empty_directory" in warnings:
                category = "empty_directory"
            elif "no_images" in warnings:
                category = "no_images"
            elif "path_mismatch_with_works_local_path" in warnings:
                category = "path_mismatch"
            if not category:
                continue

            title = row_get(work, "title", rj_id)
            if search and search not in rj_id.lower() and search not in str(title).lower() and search not in str(local_path).lower():
                continue
            anomalies.append({
                "rj_id": rj_id,
                "category": category,
                "reason": ANOMALY_LABELS.get(category, category),
                "work": dict(work),
                "lib_item": lib_item,
                "warnings": warnings,
            })
        order = {"fake_or_test": 0, "alias": 1, "missing_path": 2, "not_indexed": 3, "old_root": 4, "empty_directory": 5, "no_images": 6, "path_mismatch": 7}
        anomalies.sort(key=lambda item: (order.get(item["category"], 99), item["rj_id"]))
        return anomalies

    def _count_anomaly_categories(self, items):
        counts = {}
        for item in items:
            counts[item["category"]] = counts.get(item["category"], 0) + 1
        return counts

    def _build_header_row(self, rj_id, meta_text, badge=None):
        controls = [ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=15, color=ACCENT_PRIMARY, selectable=True), ft.Text(meta_text, size=11, color="grey")]
        if badge:
            controls.append(badge)
        controls.append(ft.IconButton(icon=ft.icons.CONTENT_COPY, icon_color="white70", tooltip="\u590d\u5236RJ\u7f16\u53f7", on_click=lambda e, rid=rj_id: self._copy_rj(rid)))
        return ft.Row(controls, wrap=True, spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _build_library_card(self, db, item):
        rj_id = row_get(item, "rj_id", "")
        total_files = row_get(item, "total_files", 0)
        total_size = row_get(item, "total_size", 0)
        audio_count = row_get(item, "audio_count", 0)
        has_cover = row_get(item, "has_cover", 0)
        folder_path = row_get(item, "folder_path", "")
        folder_name = row_get(item, "folder_name", rj_id)
        cover_src = _resolve_local_cover(folder_path, has_cover, rj_id, db) or _remote_cover_fallback(rj_id, db)
        badge = _pill(f"{audio_count} \u97f3\u9891", SUCCESS) if audio_count else None
        body = ft.Column([
            _cover_widget(cover_src, height=150) if cover_src else _no_cover_widget(150),
            self._build_header_row(rj_id, f"{total_files}f / {fmt_size(total_size)}", badge),
            ft.Text(folder_name, size=13, weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=6)
        card = Styles.glass_container(body, padding=10)
        if folder_path:
            card.on_click = lambda e, p=folder_path: open_folder(p)
        return card

    def _build_anomaly_card(self, db, item):
        work = item["work"]
        rj_id = item["rj_id"]
        local_path = row_get(work, "local_path", "")
        title = row_get(work, "title", rj_id)
        size_bytes = row_get(work, "size_bytes", 0)
        status = row_get(work, "status", "")
        warnings = item.get("warnings", [])
        reason = item["reason"]
        lib_item = item.get("lib_item") or {}
        cover_src = _resolve_local_cover(local_path, lib_item.get("has_cover", 0), rj_id, db) or _remote_cover_fallback(rj_id, db)
        warning_text = " | ".join(localize_warning(w) for w in warnings[:3]) if warnings else reason
        danger = item["category"] in {"missing_path", "empty_directory", "path_mismatch"}
        body = ft.Column([
            _cover_widget(cover_src, height=150) if cover_src else _no_cover_widget(150),
            self._build_header_row(rj_id, fmt_size(size_bytes), _pill(reason, ERROR if danger else WARNING)),
            ft.Text(title, size=13, weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(f"{status} | {warning_text}", size=11, color="white70", max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=6)
        card = Styles.glass_container(body, padding=10)
        if local_path:
            card.on_click = lambda e, p=local_path: open_folder(p)
        return card


def _pill(text, color):
    return ft.Container(content=ft.Text(text, size=9, color="white"), bgcolor=color, border_radius=999, padding=ft.padding.symmetric(horizontal=6, vertical=2))


def _resolve_local_cover(folder_path, has_cover, rj_id, db):
    if not folder_path:
        return None
    root = Path(folder_path)
    if not root.exists() or not root.is_dir():
        return None
    for name in COVER_CANDIDATES:
        candidate = root / name
        if candidate.exists():
            return str(candidate)
    try:
        for child in root.iterdir():
            if child.is_file() and child.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                if "cover" in child.name.lower() or "package" in child.name.lower() or "main" in child.name.lower():
                    return str(child)
    except Exception:
        pass
    return None


def _remote_cover_fallback(rj_id, db):
    try:
        cached = db.get_metadata_cache(rj_id)
        if cached and cached.get("cover_url"):
            return cached["cover_url"]
    except Exception:
        pass
    return None


def _cover_widget(src, height=150):
    return ft.Container(height=height, border_radius=8, clip_behavior=ft.ClipBehavior.HARD_EDGE, bgcolor=BG_SURFACE_LIGHT, content=ft.Image(src=src, fit=ft.ImageFit.COVER))


def _no_cover_widget(height=150):
    return ft.Container(height=height, border_radius=8, bgcolor=ft.colors.with_opacity(0.55, BG_SURFACE_LIGHT), alignment=ft.alignment.center, content=ft.Column([ft.Icon(ft.icons.IMAGE_NOT_SUPPORTED_OUTLINED, color=WARNING, size=30), ft.Text("\u65e0\u5c01\u9762", size=12, color="grey")], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6))


def lib_data_get(db, rj_id):
    try:
        row = db.conn.execute("SELECT * FROM library_items WHERE rj_id=?", (rj_id,)).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def parse_warnings(item):
    try:
        return json.loads(item.get("warnings_json", "[]") or "[]") if item else []
    except Exception:
        return []


def localize_warning(text):
    return WARNING_LABELS.get(text, text)


def open_folder(path_str):
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
