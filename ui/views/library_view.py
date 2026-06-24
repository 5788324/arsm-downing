import flet as ft
import os
import platform
import subprocess
from pathlib import Path

from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR

LIBRARY_PAGE_SIZE = 30

STATUS_LABELS = {
    "completed": ("已完成", SUCCESS),
    "partial": ("部分完成", WARNING),
    "prepared": ("已就绪", ACCENT_PRIMARY),
    "external": ("外部资源", ACCENT_PRIMARY),
    "indexed": ("已索引", ACCENT_PRIMARY),
    "missing": ("文件缺失", ERROR),
    "verified": ("已验证", SUCCESS),
    "metadata_failed": ("元数据失败", ERROR),
    None: ("", "grey"),
}

# Display order for filter tabs (top-level categories)
FILTER_TAB_ORDER = [
    ("__all__", "全部"),
    ("completed", "已完成"),
    ("partial", "部分完成"),
    ("external", "外部资源"),
    ("verified", "已验证"),
    ("missing", "文件缺失"),
]


def safe_update(control):
    """Update a Flet control only if it's mounted on a page."""
    try:
        if control and hasattr(control, 'page') and control.page:
            control.update()
    except Exception:
        pass


class LibraryView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True
        self.padding = 10

        self._current_page = 0
        self._current_filter = "__all__"
        self._status_counts = {}

        self.search_input = ft.TextField(
            hint_text="搜索库 (支持作品名或社团)...",
            border_radius=10, expand=True,
            on_change=self.on_search,
            on_submit=self.on_search,
        )

        # ── Status filter chips ──
        self.filter_chips = ft.Row([], wrap=True, spacing=5)

        # ── Page info ──
        self.page_info = ft.Text("", size=12, color="grey")

        # ── Pagination controls (text buttons for flet compat) ──
        self.btn_prev = ft.TextButton(
            content=ft.Text("◀ 上一页", color=ACCENT_PRIMARY),
            on_click=lambda e: self._go_page(-1))
        self.btn_next = ft.TextButton(
            content=ft.Text("下一页 ▶", color=ACCENT_PRIMARY),
            on_click=lambda e: self._go_page(1))

        # ── Grid (scrollable, no aspect ratio for better display) ──
        self.grid = ft.GridView(
            expand=True, runs_count=5, max_extent=200,
            child_aspect_ratio=0.8, spacing=10, run_spacing=10,
        )

        self.content = ft.Column(
            [
                ft.Text("您的资源库", size=32, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=self.search_input,
                    padding=10),
                ft.Container(
                    content=self.filter_chips,
                    padding=5),
                ft.Row([
                    ft.Text("", expand=True),  # spacer
                    self.page_info,
                    self.btn_prev,
                    self.btn_next,
                ], alignment=ft.MainAxisAlignment.END),
                ft.Divider(height=1, color="transparent"),
                self.grid,
            ],
            expand=True,
        )

    # ── Status counts ──
    def _refresh_counts(self):
        """Fetch live status counts from DB."""
        try:
            self._status_counts = self.app_controller.db.count_library_by_status()
        except Exception:
            self._status_counts = {"__total__": 0}

    # ── Filter chips ──
    def _build_filter_chips(self):
        """Build filter chip row from current counts."""
        self.filter_chips.controls.clear()

        for key, label in FILTER_TAB_ORDER:
            count = 0
            if key == "__all__":
                count = self._status_counts.get("__total__", 0)
            else:
                count = self._status_counts.get(key, 0)

            chip_text = f"{label} ({count})"
            is_active = self._current_filter == key
            chip = ft.Chip(
                label=ft.Text(chip_text, size=12, color="white"),
                bgcolor=ACCENT_PRIMARY if is_active else None,
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda e, k=key: self._on_filter_chip(k),
            )
            self.filter_chips.controls.append(chip)

    def _on_filter_chip(self, key: str):
        self._current_filter = key
        self._current_page = 0
        self.load_library(self.search_input.value)

    def _go_page(self, delta: int):
        new_page = self._current_page + delta
        if new_page < 0:
            return
        self._current_page = new_page
        self.load_library(self.search_input.value)

    # ── Main load ──
    def load_library(self, query=""):
        self._refresh_counts()
        self._build_filter_chips()

        self.grid.controls.clear()

        status_filter = "" if self._current_filter == "__all__" else self._current_filter
        offset = self._current_page * LIBRARY_PAGE_SIZE

        results = self.app_controller.db.search(
            query, offset=offset, limit=LIBRARY_PAGE_SIZE,
            status_filter=status_filter)

        # Get total for this filter for page info
        total_key = "__total__" if self._current_filter == "__all__" else self._current_filter
        total_for_filter = self._status_counts.get(total_key, len(results))
        total_pages = max(1, (total_for_filter + LIBRARY_PAGE_SIZE - 1)
                          // LIBRARY_PAGE_SIZE) if LIBRARY_PAGE_SIZE > 0 else 1

        for row in results:
            rj_id = row["rj_id"]
            title = row["title"] or rj_id
            circle = row["circle"] or ""
            local_path = row["local_path"]
            cover_url = (
                row["cover_url"] if "cover_url" in row.keys() else None)
            status = (
                row["status"] if "status" in row.keys() else "completed")

            label, color = STATUS_LABELS.get(
                status, STATUS_LABELS[None])

            # Show cover or icon
            image_control = (
                ft.Image(src=cover_url, width=150, height=150,
                         fit=ft.ImageFit.COVER, border_radius=10)
                if cover_url
                else ft.Icon(ft.icons.LIBRARY_MUSIC, size=100,
                             color=ACCENT_PRIMARY)
            )

            # Status badge row
            status_badges = [
                ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=13),
            ]
            if label:
                status_badges.append(
                    ft.Container(
                        content=ft.Text(label, size=9, color="white"),
                        bgcolor=color, border_radius=4,
                        padding=ft.padding.symmetric(
                            horizontal=6, vertical=2),
                    )
                )

            card = ft.Column([
                image_control,
                ft.Row(status_badges, wrap=True),
                ft.Text(title, size=11, max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(circle, size=9, color="grey", max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], alignment=ft.MainAxisAlignment.CENTER,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=4)

            container = Styles.glass_container(card, padding=8)
            container.on_click = lambda e, p=local_path: self.open_folder(p)
            self.grid.controls.append(container)

        # Update page info
        start = offset + 1 if results else 0
        end = offset + len(results)
        self.page_info.value = (
            f"第 {self._current_page + 1}/{total_pages} 页 "
            f"({start}-{end} / 共 {total_for_filter} 个)")
        self.btn_prev.disabled = self._current_page == 0
        self.btn_next.disabled = (
            self._current_page + 1 >= total_pages)

        safe_update(self.grid)
        safe_update(self.page_info)
        safe_update(self.btn_prev)
        safe_update(self.btn_next)

    def on_search(self, e):
        self._current_page = 0
        self.load_library(self.search_input.value)

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
