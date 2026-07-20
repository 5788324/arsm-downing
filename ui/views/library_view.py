"""Resource library view backed by portable, background-loaded snapshots."""
from __future__ import annotations

import os
import platform
from pathlib import Path
import subprocess
from typing import Any

import flet as ft

from core.library_diagnostics import (
    ANOMALY_LABELS,
    ANOMALY_ORDER,
    classify_library_anomalies,
    flatten_anomaly_groups,
)
from ui.theme import (
    ACCENT_PRIMARY,
    BG_SURFACE_LIGHT,
    ERROR,
    SUCCESS,
    WARNING,
    Styles,
)

LIBRARY_PAGE_SIZE = 20
ANOMALY_DISPLAY_LIMIT = 200
COVER_CANDIDATES = (
    "cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
    "main.jpg", "main.png", "package.jpg", "package.png",
)

# Compatibility map retained for historical diagnostics and any future status
# badges.  The new card view is index-first, but old scripts still import it.
STATUS_LABELS = {
    "completed": ("已完成", SUCCESS),
    "partial": ("部分完成", WARNING),
    "external": ("外部资源", ACCENT_PRIMARY),
    "verified": ("已验证", SUCCESS),
    "missing": ("文件缺失", ERROR),
    "indexed": ("已索引", ACCENT_PRIMARY),
    "metadata_failed": ("元数据失败", ERROR),
    "prepared": ("已准备", ACCENT_PRIMARY),
}


def fmt_size(value: int) -> str:
    size = max(0, int(value or 0))
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.1f} GB"
    if size >= 1_000_000:
        return f"{size / 1_000_000:.0f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.0f} KB"
    return f"{size} B"


class LibraryView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True
        self.padding = 10
        self._current_page = 0
        self._mode = "cards"
        self._anomaly_filter = "__all__"
        self._load_generation = 0

        self.search_input = ft.TextField(
            hint_text="搜索 RJ / 文件夹 / 路径，输入后回车",
            border_radius=10,
            expand=True,
            on_submit=self.on_search,
            on_change=self._on_search_change,
        )
        self.search_button = ft.IconButton(
            icon=ft.Icons.SEARCH,
            tooltip="搜索",
            on_click=self.on_search,
        )
        self.clear_search_button = ft.IconButton(
            icon=ft.Icons.CLEAR,
            tooltip="清空搜索",
            on_click=self.clear_search,
        )
        self.summary_bar = ft.Text("", size=12, color="grey")
        self.page_info = ft.Text("", size=12, color="grey")
        self.loading_text = ft.Text("", size=12, color=ACCENT_PRIMARY)
        self.btn_prev = ft.TextButton(
            content=ft.Text("上一页", color=ACCENT_PRIMARY),
            on_click=lambda e: self._go_page(-1),
        )
        self.btn_next = ft.TextButton(
            content=ft.Text("下一页", color=ACCENT_PRIMARY),
            on_click=lambda e: self._go_page(1),
        )
        self.mode_toggle = ft.Row([], spacing=6)
        self.anomaly_chips = ft.Row([], spacing=4, wrap=True)

        self.grid = ft.GridView(
            expand=True,
            max_extent=280,
            child_aspect_ratio=0.72,
            spacing=12,
            run_spacing=12,
        )
        self.anomaly_list = ft.ListView(expand=True, spacing=4)

        self.content = ft.Column([
            ft.Text("资源库", size=28, weight=ft.FontWeight.BOLD),
            self.summary_bar,
            ft.Row([
                self.search_input,
                self.search_button,
                self.clear_search_button,
            ], spacing=6),
            self.mode_toggle,
            self.anomaly_chips,
            ft.Row([
                self.loading_text,
                ft.Text("", expand=True),
                self.page_info,
                self.btn_prev,
                self.btn_next,
            ], alignment=ft.MainAxisAlignment.END),
            ft.Divider(height=1, color="transparent"),
            self.grid,
            self.anomaly_list,
        ], expand=True, spacing=8)

    def _safe_update(self) -> None:
        try:
            if self.page:
                self.update()
        except Exception:
            pass

    def _build_mode_toggle(self) -> None:
        self.mode_toggle.controls.clear()
        for key, label in (("cards", "索引视图"), ("anomalies", "异常视图")):
            active = self._mode == key
            self.mode_toggle.controls.append(ft.Chip(
                label=ft.Text(label, size=12, color="white"),
                bgcolor=ACCENT_PRIMARY if active else None,
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda e, selected=key: self._set_mode(selected),
            ))

    def _set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._current_page = 0
        self.load_library()

    def _on_search_change(self, _event=None) -> None:
        # Do not run a filesystem/database scan on every keystroke.  Clearing
        # the field refreshes immediately; non-empty queries run on Enter/Search.
        if not (self.search_input.value or "").strip():
            self._current_page = 0
            self.load_library()

    def on_search(self, _event=None) -> None:
        self._current_page = 0
        self.load_library()

    def clear_search(self, _event=None) -> None:
        self.search_input.value = ""
        self._current_page = 0
        self.load_library()

    def _go_page(self, delta: int) -> None:
        target = self._current_page + delta
        if target < 0:
            return
        self._current_page = target
        self.load_library()

    def _configured_roots(self) -> list[str]:
        config = self.app_controller.config
        values = [str(config.output_dir)]
        values.extend(str(path) for path in (getattr(config, "library_paths", []) or []))
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.strip().replace("\\", "/").rstrip("/").casefold()
            if value.strip() and normalized not in seen:
                result.append(value.strip())
                seen.add(normalized)
        return result

    def load_library(self) -> None:
        """Load DB rows and expensive anomaly path checks off the UI thread."""
        self._load_generation += 1
        generation = self._load_generation
        mode = self._mode
        search = (self.search_input.value or "").strip()
        requested_page = self._current_page
        anomaly_filter = self._anomaly_filter
        configured_roots = self._configured_roots()

        self._build_mode_toggle()
        self.loading_text.value = "正在读取资源库…"
        self.grid.visible = mode == "cards"
        self.anomaly_list.visible = mode == "anomalies"
        self.anomaly_chips.visible = mode == "anomalies"
        self.btn_prev.disabled = True
        self.btn_next.disabled = True
        self._safe_update()

        def worker() -> dict[str, Any]:
            try:
                db = self.app_controller.db
                if mode == "cards":
                    initial = db.get_library_page(
                        search=search,
                        offset=max(0, requested_page) * LIBRARY_PAGE_SIZE,
                        limit=LIBRARY_PAGE_SIZE,
                    )
                    total = int(initial.get("total", 0))
                    total_pages = max(
                        1, (total + LIBRARY_PAGE_SIZE - 1) // LIBRARY_PAGE_SIZE
                    )
                    actual_page = min(max(0, requested_page), total_pages - 1)
                    if actual_page != requested_page:
                        initial = db.get_library_page(
                            search=search,
                            offset=actual_page * LIBRARY_PAGE_SIZE,
                            limit=LIBRARY_PAGE_SIZE,
                        )
                    initial.update({
                        "mode": mode,
                        "search": search,
                        "page": actual_page,
                        "total_pages": total_pages,
                    })
                    return initial

                rows = db.get_library_diagnostic_rows()
                groups = classify_library_anomalies(
                    rows.get("works", []),
                    rows.get("library_items", []),
                    configured_roots=configured_roots,
                    search=search,
                )
                selected = flatten_anomaly_groups(groups, anomaly_filter)
                rows.update({
                    "mode": mode,
                    "search": search,
                    "groups": groups,
                    "selected": selected,
                    "filter": anomaly_filter,
                })
                return rows
            except Exception as exc:
                return {
                    "mode": mode,
                    "search": search,
                    "error": str(exc),
                    "items": [],
                    "selected": [],
                    "groups": {},
                    "summary": {},
                    "works_count": 0,
                    "total": 0,
                    "page": 0,
                    "total_pages": 1,
                }

        def apply(snapshot: dict[str, Any]) -> None:
            if generation != self._load_generation:
                return
            self.loading_text.value = ""
            self.grid.controls.clear()
            self.anomaly_list.controls.clear()
            if snapshot.get("error"):
                self.summary_bar.value = "资源库读取失败"
                self.page_info.value = ""
                target = self.grid if snapshot.get("mode") == "cards" else self.anomaly_list
                target.controls.append(ft.Container(
                    padding=30,
                    alignment=ft.alignment.center,
                    content=ft.Text(
                        f"读取失败: {snapshot['error']}", color=ERROR, selectable=True
                    ),
                ))
                self._safe_update()
                return
            if snapshot.get("mode") == "cards":
                self._apply_cards(snapshot)
            else:
                self._apply_anomalies(snapshot)
            self._safe_update()

        self.app_controller.run_blocking(
            worker,
            apply,
            action_label="读取资源库",
        )

    def _summary_text(self, snapshot: dict[str, Any]) -> str:
        summary = snapshot.get("summary", {}) or {}
        return (
            f"下载器记录 {int(snapshot.get('works_count', 0))} · "
            f"已索引 {int(summary.get('total_works', 0))} · "
            f"文件 {int(summary.get('total_files', 0))} · "
            f"容量 {fmt_size(int(summary.get('total_size', 0)))} · "
            f"警告 {int(summary.get('with_warnings', 0))}"
        )

    def _apply_cards(self, snapshot: dict[str, Any]) -> None:
        self._current_page = int(snapshot.get("page", 0))
        total_pages = int(snapshot.get("total_pages", 1))
        total = int(snapshot.get("total", 0))
        search = snapshot.get("search", "")
        self.summary_bar.value = self._summary_text(snapshot)
        self.page_info.value = (
            f"第 {self._current_page + 1}/{total_pages} 页 · {total} 项"
            + (f" · 搜索“{search}”" if search else "")
        )
        self.btn_prev.disabled = self._current_page <= 0
        self.btn_next.disabled = self._current_page + 1 >= total_pages

        items = snapshot.get("items", [])
        if not items:
            self.grid.controls.append(ft.Container(
                alignment=ft.alignment.center,
                padding=40,
                content=ft.Text("没有匹配的资源库记录", color="grey", size=14),
            ))
            return

        for item in items:
            rj_id = item["rj_id"]
            folder_path = item.get("folder_path", "") or ""
            folder_name = item.get("folder_name", rj_id) or rj_id
            display_name = folder_name if len(folder_name) <= 44 else folder_name[:41] + "…"
            cover_src = _resolve_local_cover(folder_path, bool(item.get("has_cover")))
            if not cover_src:
                cover_src = item.get("metadata_cover_url") or None
            cover = _cover_widget(cover_src, 180) if cover_src else _no_cover_widget(180)

            badges: list[ft.Control] = [
                ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=14, color=ACCENT_PRIMARY),
                ft.Text(
                    f"{int(item.get('total_files', 0))} 文件 / "
                    f"{fmt_size(int(item.get('total_size', 0)))}",
                    size=11,
                    color="grey",
                ),
            ]
            if int(item.get("audio_count", 0)) > 0:
                badges.append(_badge(f"{int(item['audio_count'])} 音频", SUCCESS))
            if not item.get("has_cover"):
                badges.append(_badge("无本地封面", WARNING))

            card = ft.Column([
                cover,
                ft.Row(badges, wrap=True, spacing=4),
                ft.Text(
                    display_name,
                    size=13,
                    weight=ft.FontWeight.W_600,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip=folder_name,
                ),
            ], spacing=6)
            container = Styles.glass_container(card, padding=10)
            if folder_path:
                container.tooltip = folder_path
                container.on_click = (
                    lambda e, path=folder_path: self._open_folder(path)
                )
            self.grid.controls.append(container)

    def _build_anomaly_chips(self, groups: dict[str, list[dict]]) -> None:
        self.anomaly_chips.controls.clear()
        total = sum(len(groups.get(key, [])) for key in ANOMALY_ORDER)
        choices = [("__all__", "全部异常", total)] + [
            (key, ANOMALY_LABELS[key], len(groups.get(key, [])))
            for key in ANOMALY_ORDER
        ]
        for key, label, count in choices:
            active = self._anomaly_filter == key
            self.anomaly_chips.controls.append(ft.Chip(
                label=ft.Text(f"{label} ({count})", size=11, color="white"),
                bgcolor=ACCENT_PRIMARY if active else None,
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda e, selected=key: self._set_anomaly_filter(selected),
            ))

    def _set_anomaly_filter(self, key: str) -> None:
        if key == self._anomaly_filter:
            return
        self._anomaly_filter = key
        self.load_library()

    def _apply_anomalies(self, snapshot: dict[str, Any]) -> None:
        groups = snapshot.get("groups", {})
        selected = snapshot.get("selected", [])
        self._build_anomaly_chips(groups)
        self.summary_bar.value = self._summary_text(snapshot)
        shown = min(len(selected), ANOMALY_DISPLAY_LIMIT)
        suffix = "" if shown == len(selected) else f"，仅显示前 {shown} 项"
        search = snapshot.get("search", "")
        self.page_info.value = (
            f"共 {len(selected)} 项异常{suffix}"
            + (f" · 搜索“{search}”" if search else "")
        )
        self.btn_prev.disabled = True
        self.btn_next.disabled = True

        if not selected:
            self.anomaly_list.controls.append(ft.Container(
                padding=30,
                alignment=ft.alignment.center,
                content=ft.Text("当前筛选下没有异常", color=SUCCESS, size=14),
            ))
            return

        last_category = ""
        for anomaly in selected[:ANOMALY_DISPLAY_LIMIT]:
            category = anomaly["category"]
            category_label = ANOMALY_LABELS.get(category, category)
            if self._anomaly_filter == "__all__" and category != last_category:
                last_category = category
                self.anomaly_list.controls.append(ft.Text(
                    f"── {category_label} ({len(groups.get(category, []))}) ──",
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=WARNING,
                ))
            local_path = anomaly.get("local_path") or "无路径"
            title = anomaly.get("title") or ""
            line = (
                f"{anomaly['rj_id']} · {anomaly.get('works_status') or '-'} · "
                f"索引={'是' if anomaly.get('indexed') else '否'} · "
                f"{int(anomaly.get('total_files', 0))} 文件 / "
                f"{fmt_size(int(anomaly.get('total_size', 0)))}\n"
                f"{title}\n{local_path}"
            )
            self.anomaly_list.controls.append(Styles.glass_container(
                ft.Column([
                    ft.Text(category_label, size=11, color=WARNING),
                    ft.Text(line, size=11, selectable=True, font_family="Consolas"),
                ], spacing=3),
                padding=10,
            ))

    def _open_folder(self, path: str) -> None:
        success, message = open_folder(path)
        if not success:
            self.app_controller.show_snack(message)


def _badge(text: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=9, color="white"),
        bgcolor=color,
        border_radius=999,
        padding=ft.padding.symmetric(horizontal=6, vertical=2),
    )


def _resolve_local_cover(folder_path: str, has_cover: bool) -> str | None:
    if not folder_path or not has_cover:
        return None
    root = Path(folder_path)
    if not root.is_dir():
        return None
    for name in COVER_CANDIDATES:
        candidate = root / name
        if candidate.is_file():
            return str(candidate)
    try:
        for child in root.iterdir():
            if (
                child.is_file()
                and child.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                and ("cover" in child.name.lower() or "package" in child.name.lower())
            ):
                return str(child)
    except OSError:
        return None
    return None


def _cover_widget(source: str, height: int = 180) -> ft.Container:
    return ft.Container(
        height=height,
        border_radius=14,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=BG_SURFACE_LIGHT,
        content=ft.Image(src=source, fit=ft.ImageFit.COVER),
    )


def _no_cover_widget(height: int = 180) -> ft.Container:
    return ft.Container(
        height=height,
        border_radius=14,
        bgcolor=ft.Colors.with_opacity(0.55, BG_SURFACE_LIGHT),
        alignment=ft.alignment.center,
        content=ft.Column([
            ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED, color=WARNING, size=36),
            ft.Text("无封面", size=12, color="grey"),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
    )


def open_folder(path: str | Path) -> tuple[bool, str]:
    target = Path(path)
    if not target.exists():
        return False, f"目录不存在: {target}"
    if not target.is_dir():
        return False, f"目标不是目录: {target}"
    try:
        if platform.system() == "Windows":
            os.startfile(target)
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(target)], check=True)
        else:
            subprocess.run(["xdg-open", str(target)], check=True)
    except Exception as exc:
        return False, f"打开目录失败: {exc}"
    return True, str(target)
