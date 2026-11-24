"""Resource library view backed by portable, background-loaded snapshots."""
from __future__ import annotations

import csv
import os
from collections import Counter
from datetime import datetime
from functools import lru_cache
import platform
import re
from pathlib import Path
import subprocess
from typing import Any
import time

import flet as ft

from core.library_diagnostics import (
    ANOMALY_LABELS,
    ANOMALY_ORDER,
    classify_library_anomalies,
    filter_anomaly_groups,
    flatten_anomaly_groups,
)
from core.library_assets import (
    apply_subtitles, clear_subtitle_catalog_cache, fill_mp3_tags, inspect_album_assets,
    subtitle_candidates,
)
from core.media_assets import find_local_cover, get_cover_thumbnail
from core.paths import app_path
from ui.theme import (
    ACCENT_PRIMARY,
    ACCENT_SECONDARY,
    BG_SURFACE_LIGHT,
    ERROR,
    SUCCESS,
    WARNING,
    Styles,
)

LIBRARY_PAGE_SIZE = 20
FILE_PREVIEW_LIMIT = 200
ANOMALY_DISPLAY_LIMIT = 40

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
        self._category = "all"
        self._sort = "size_desc"
        self._load_generation = 0
        self._detail_generation = 0
        self._selected_rj_id = ''
        self._layout = "grid"
        self._collection = ""
        self._tag = ""
        self._anomaly_snapshot = []
        self._anomaly_cache = None
        self._last_page = 1


        self.search_input = ft.TextField(
            hint_text="搜索 RJ、作品名、社团、声优或标签",
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
        self.category_chips = ft.Row([], spacing=4, wrap=True, expand=True)
        self.layout_button = ft.IconButton(
            icon=ft.Icons.VIEW_LIST_OUTLINED, tooltip="切换列表或卡片",
            on_click=self._toggle_layout,
        )
        self.collection_dropdown = ft.Dropdown(
            label="合集", width=150, dense=True, visible=False, on_change=self._select_collection,
        )
        self.refresh_button = ft.IconButton(
            icon=ft.Icons.REFRESH, tooltip="刷新资源库", on_click=self._refresh_library,
        )
        self.backfill_button = ft.TextButton(
            "补录已下载", icon=ft.Icons.ADD_TO_PHOTOS_OUTLINED, visible=False,
            on_click=self._backfill_completed,
        )
        self.export_anomalies = ft.TextButton(
            "导出异常", icon=ft.Icons.DOWNLOAD_OUTLINED, visible=False,
            on_click=self._export_anomaly_rows,
        )
        self.sort_dropdown = ft.Dropdown(
            value=self._sort,
            width=180,
            dense=True,
            text_size=12,
            options=[
                ft.dropdown.Option("size_desc", "按容量"),
                ft.dropdown.Option("files_desc", "按文件数"),
                ft.dropdown.Option("name_asc", "按文件夹名"),
                ft.dropdown.Option("rj_desc", "按 RJ 编号"),
                ft.dropdown.Option("admitted_desc", "按入库时间"),
                ft.dropdown.Option("release_desc", "按 DLsite 发售时间"),
            ],
            on_change=self._set_sort,
        )
        self.anomaly_chips = ft.Row([], spacing=4, wrap=True)
        self.tag_filter = ft.Chip(label=ft.Text(""), visible=False,
                                  on_delete=lambda _: self._set_tag(""))

        self.grid = ft.GridView(
            expand=True,
            max_extent=280,
            child_aspect_ratio=0.72,
            spacing=12,
            run_spacing=12,
        )
        self.work_list = ft.ListView(expand=True, spacing=7, visible=False)
        self.anomaly_list = ft.ListView(expand=True, spacing=4)
        self.detail_panel = Styles.glass_container(
            ft.Column([
                ft.Icon(ft.Icons.TOUCH_APP_OUTLINED, color=ACCENT_PRIMARY, size=34),
                ft.Text("选择一张专辑", size=16, weight=ft.FontWeight.BOLD),
                ft.Text("右侧会显示作品元数据与文件列表。", size=12, color="grey"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            padding=18,
            width=370,
            expand=False,
        )
        self.library_body = ft.Row([self.grid, self.work_list, self.detail_panel], expand=True, spacing=14)

        self.content = ft.Column([
            ft.Text("资源库", size=28, weight=ft.FontWeight.BOLD),
            self.summary_bar,
            ft.Row([
                self.search_input,
                self.search_button,
                self.clear_search_button, self.refresh_button,
            ], spacing=6),
            self.mode_toggle,
            ft.Row([self.category_chips, self.collection_dropdown, self.layout_button,
                    self.sort_dropdown, self.backfill_button, self.export_anomalies],
                   alignment=ft.MainAxisAlignment.END),
            self.anomaly_chips,
            self.tag_filter,
            ft.Row([
                self.loading_text,
                ft.Text("", expand=True),
                self.page_info,
                self.btn_prev,
                self.btn_next,
            ], alignment=ft.MainAxisAlignment.END),
            ft.Divider(height=1, color="transparent"),
            self.library_body,
            self.anomaly_list,
        ], expand=True, spacing=8)

        self._active = False

    def set_active(self, active: bool) -> None:
        changed = bool(active) != self._active
        self._active = bool(active)
        if not self._active:
            # Invalidate any worker result that was started while visible.
            self._load_generation += 1
        elif changed:
            self.load_library()

    def _safe_update(self) -> None:
        try:
            if self.page:
                self.update()
        except Exception:
            pass

    def _build_mode_toggle(self) -> None:
        self.mode_toggle.controls.clear()
        for key, label in (("cards", "全部作品"), ("attention", "待补齐"),
                           ("subtitles", "字幕待下载"), ("cloud", "云盘"),
                           ("anomalies", "异常")):
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
        self._category = {"attention": "needs_attention", "cloud": "cloud_archived"}.get(mode, "all")
        self._current_page = 0
        self.load_library()

    def _scan_asset_checks(self, _event=None) -> None:
        def work():
            db = self.app_controller.db
            checked = []
            skipped = 0
            for rid, folder in db.library_asset_roots():
                try:
                    path = Path(folder)
                    if not path.is_dir():
                        skipped += 1
                        continue
                    result = inspect_album_assets(path, rid, "", verify_audio=False)
                    checked.append((rid, folder, len(result.mp3_tasks)))
                except (OSError, ValueError):
                    skipped += 1
            db.save_library_asset_checks(checked)
            return len(checked), skipped
        self.loading_text.value = "正在盘点本地 MP3 标签，大型媒体库需要一些时间…"
        self._safe_update()
        def done(result):
            self.app_controller.show_snack(f"已盘点 {result[0]} 部，跳过 {result[1]} 部")
            self.load_library()
        self.app_controller.run_blocking(work, done, action_label="盘点 MP3 标签")

    def _build_category_chips(self) -> None:
        self.category_chips.controls.clear()
        choices = (
            ("all", "全部作品"),
            ("audio", "有音频"),
            ("missing_cover", "无本地封面"),
            ("warnings", "有警告"),
            ("completed", "已完成"),
            ("postprocess_pending", "待后处理"),
            ("favorite", "收藏"),
            ("recent", "最近播放"),
            ("collection", "自定义合集"),
        )
        if self._mode == "attention":
            choices = (("needs_attention", "全部待补齐"), ("missing_lrc", "缺 LRC"),
                       ("postprocess_pending", "待后处理"), ("missing_cover", "缺封面"),
                       ("missing_tags", "缺 MP3 标签"))
        if self._mode == "cloud":
            choices = (("cloud_archived", "全部归档"), ("cloud_only", "仅云端"),
                       ("cloud_and_local", "本地和云端"), ("cloud_path_missing", "归档位置待补填"))
        for key, label in choices:
            self.category_chips.controls.append(ft.Chip(
                label=ft.Text(label, size=11, color="white"),
                bgcolor=ACCENT_PRIMARY if self._category == key else None,
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda e, selected=key: self._set_category(selected),
            ))

        if self._mode == "attention":
            self.category_chips.controls.append(
                ft.TextButton("盘点 MP3 标签", on_click=self._scan_asset_checks))

    def _set_category(self, category: str) -> None:
        if category == self._category:
            return
        self._category = category
        self._current_page = 0
        self.load_library()

    def _toggle_layout(self, _event=None) -> None:
        self._layout = "list" if self._layout == "grid" else "grid"
        self.layout_button.icon = (ft.Icons.GRID_VIEW_OUTLINED
                                   if self._layout == "list" else ft.Icons.VIEW_LIST_OUTLINED)
        self.load_library()

    def _select_collection(self, _event=None) -> None:
        self._collection = str(self.collection_dropdown.value or "")
        self._current_page = 0
        self.load_library()

    def focus_album(self, rj_id: str) -> None:
        self._mode = "cards"
        self._category = "all"
        self._tag = ""
        self.search_input.value = rj_id
        self._current_page = 0
        self._open_after_load = rj_id
        self.load_library()

    def _set_tag(self, tag: str) -> None:
        self._tag = tag
        if tag:
            self._mode = "cards"
            self._category = "all"
            self.search_input.value = ""
        self._current_page = 0
        self.load_library()

    def _tag_button(self, tag: str) -> ft.Container:
        badge = _badge(tag, ACCENT_SECONDARY)
        badge.tooltip = f"筛选标签：{tag}"
        badge.on_click = lambda _, selected=tag: self._set_tag(selected)
        return badge

    def _set_sort(self, _event=None) -> None:
        selected = str(self.sort_dropdown.value or "size_desc")
        if selected == self._sort:
            return
        self._sort = selected
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

    def _refresh_library(self, _event=None) -> None:
        self._anomaly_cache = None
        _card_disk_state.cache_clear()
        clear_subtitle_catalog_cache()
        self.load_library()

    def load_library(self) -> None:
        """Load DB rows and expensive anomaly path checks off the UI thread."""
        self._load_generation += 1
        generation = self._load_generation
        mode = self._mode
        search = (self.search_input.value or "").strip()
        requested_page = self._current_page
        anomaly_filter = self._anomaly_filter
        category = self._category
        sort = self._sort
        configured_roots = self._configured_roots()
        archive_dir = getattr(self.app_controller.config, "subtitle_archive_dir", "")
        collection = self._collection
        tag = self._tag if mode not in {"subtitles", "anomalies"} else ""
        show_results = mode != "anomalies"
        layout = self._layout
        roots_key = tuple(configured_roots)
        cached_anomalies = self._anomaly_cache

        self._build_mode_toggle()
        self._build_category_chips()
        self.tag_filter.visible = bool(tag)
        self.tag_filter.label.value = f"标签：{tag}"
        self.loading_text.value = "正在读取资源库…"
        self.grid.visible = show_results and self._layout == "grid"
        self.work_list.visible = show_results and self._layout == "list"
        self.anomaly_list.visible = not show_results
        self.anomaly_chips.visible = not show_results
        self.export_anomalies.visible = not show_results
        self.backfill_button.visible = not show_results
        self.category_chips.visible = show_results and mode != "subtitles"
        self.sort_dropdown.visible = show_results and mode != "subtitles"
        self.layout_button.visible = show_results
        self.collection_dropdown.visible = category == "collection" and mode == "cards"
        self.library_body.visible = show_results
        self.detail_panel.visible = show_results and mode != "subtitles"
        self.btn_prev.disabled = True
        self.btn_next.disabled = True
        self._safe_update()

        def worker() -> dict[str, Any]:
            try:
                db = self.app_controller.db
                if mode == "subtitles":
                    ids = subtitle_candidates(archive_dir, db.known_library_work_ids(), search)
                    pages = max(1, (len(ids) + LIBRARY_PAGE_SIZE - 1) // LIBRARY_PAGE_SIZE)
                    page = min(requested_page, pages - 1)
                    start = page * LIBRARY_PAGE_SIZE
                    return {"mode": "cards", "search": search, "category": "subtitle_queue",
                            "page": page, "total": len(ids), "total_pages": pages,
                            "items": [{"rj_id": rid, "subtitle_only": True}
                                      for rid in ids[start:start + LIBRARY_PAGE_SIZE]],
                            "summary": db.get_library_summary()}
                if show_results:
                    extra = {"collection": collection} if category == "collection" else {}
                    if tag:
                        extra["tag"] = tag
                    initial = db.get_library_page(
                        search=search,
                        offset=max(0, requested_page) * LIBRARY_PAGE_SIZE,
                        limit=LIBRARY_PAGE_SIZE,
                        category=category,
                        sort=sort, **extra,
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
                            category=category,
                            sort=sort, **extra,
                        )
                    if layout == "list":
                        for item in initial.get("items", ()):
                            folder = str(item.get("folder_path") or "")
                            item["folder_available"] = not folder or Path(folder).is_dir()
                    initial.update({
                        "mode": "cards",
                        "search": search,
                        "collections": db.library_collection_names() if category == "collection" else [],
                        "category": category,
                        "tag": tag,
                        "sort": sort,
                        "page": actual_page,
                        "total_pages": total_pages,
                    })
                    return initial

                cached_result = None
                if (cached_anomalies and cached_anomalies[0] == roots_key
                        and time.monotonic() < cached_anomalies[1]):
                    _, _, rows, all_groups = cached_anomalies
                else:
                    rows = db.get_library_diagnostic_rows()
                    if rows.get("error"):
                        return {**rows, "mode": mode}
                    all_groups = classify_library_anomalies(
                        rows.get("works", []), rows.get("library_items", []),
                        configured_roots=configured_roots,
                    )
                    rows = {"summary": rows.get("summary", {}),
                            "works_count": rows.get("works_count", 0)}
                    cached_result = (roots_key, time.monotonic() + 20, rows, all_groups)
                groups = filter_anomaly_groups(all_groups, search) if search else all_groups
                rows = dict(rows)
                if cached_result is not None:
                    rows["anomaly_cache"] = cached_result
                selected = flatten_anomaly_groups(groups, anomaly_filter)
                rows.update({
                    "mode": mode,
                    "search": search,
                    "groups": groups,
                    "selected": selected,
                    "filter": anomaly_filter,
                    "page": requested_page,
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
            self.work_list.controls.clear()
            self.anomaly_list.controls.clear()
            if snapshot.get("error"):
                self.summary_bar.value = "资源库读取失败"
                self.page_info.value = ""
                target = self._results_control() if show_results else self.anomaly_list
                target.controls.append(ft.Container(
                    padding=30,
                    alignment=ft.alignment.center,
                    content=ft.Text(
                        f"读取失败: {snapshot['error']}", color=ERROR, selectable=True
                    ),
                ))
                self._safe_update()
                return
            cover_slots = {}
            if snapshot.get("mode") == "cards":
                cover_slots = self._apply_cards(snapshot)
            else:
                if snapshot.get("anomaly_cache"):
                    self._anomaly_cache = snapshot["anomaly_cache"]
                self._apply_anomalies(snapshot)
            self._safe_update()
            self._load_card_covers(generation, snapshot.get("items", []), cover_slots)

        self.app_controller.run_blocking(
            worker,
            apply,
            action_label="读取资源库",
        )

    def _summary_text(self, snapshot: dict[str, Any]) -> str:
        summary = snapshot.get("summary", {}) or {}
        return (
            f"本地 {int(summary.get('local_works', 0))} 部 / {fmt_size(summary.get('local_bytes', 0))} · "
            f"云盘 {int(summary.get('cloud_archived', 0))} 部 / {fmt_size(summary.get('cloud_bytes', 0))} · "
            f"下载器记录 {int(snapshot.get('works_count', 0))} · "
            f"已索引 {int(summary.get('total_works', 0))} · "
            f"文件 {int(summary.get('total_files', 0))} · "
            f"容量 {fmt_size(int(summary.get('total_size', 0)))} · "
            f"云盘资源 {int(summary.get('cloud_archived', 0))} · "
            f"警告 {int(summary.get('with_warnings', 0))}"
        )

    def _results_control(self):
        return self.work_list if self._layout == "list" else self.grid

    def _reset_detail(self) -> None:
        self._selected_rj_id = ""
        self._detail_generation += 1
        self.detail_panel.content = ft.Text("选择专辑查看音轨、字幕与文件", size=13)

    def _apply_cards(self, snapshot: dict[str, Any]) -> dict[str, tuple[ft.Container, ft.Row]]:
        cover_slots: dict[str, tuple[ft.Container, ft.Row]] = {}
        self._current_page = int(snapshot.get("page", 0))
        total_pages = int(snapshot.get("total_pages", 1))
        total = int(snapshot.get("total", 0))
        search = snapshot.get("search", "")
        category = snapshot.get("category", "all")
        sort = snapshot.get("sort", "size_desc")
        category_label = {
            "all": "全部作品", "audio": "有音频", "missing_cover": "无本地封面", "warnings": "有警告",
            "completed": "已完成", "postprocess_pending": "待后处理", "cloud_archived": "云盘资源",
        }.get(category, "全部作品")
        sort_label = {
            "size_desc": "容量", "files_desc": "文件数", "name_asc": "文件夹名", "rj_desc": "RJ 编号",
            "admitted_desc": "入库时间", "release_desc": "DLsite 发售时间",
        }.get(sort, "容量")
        self.summary_bar.value = self._summary_text(snapshot)
        self.page_info.value = (
            f"第 {self._current_page + 1}/{total_pages} 页 · {total} 项"
            + (f" · 搜索“{search}”" if search else "")
            + (f" · {category_label} · 按{sort_label}" if category != "all" or sort != "size_desc" else "")
        )
        self.btn_prev.disabled = self._current_page <= 0
        self.btn_next.disabled = self._current_page + 1 >= total_pages

        items = snapshot.get("items", [])
        result = self._results_control()
        if category == "collection":
            names = snapshot.get("collections", [])
            self.collection_dropdown.options = [ft.dropdown.Option(name, name) for name in names]
            self.collection_dropdown.value = self._collection or None
        self.detail_panel.visible = bool(items) and category != "subtitle_queue"
        if self._selected_rj_id and not any(x["rj_id"] == self._selected_rj_id for x in items):
            self._reset_detail()
        if not items:
            has_query = bool(search or snapshot.get("tag")) or category != "all"
            message = "没有匹配的资源库记录" if has_query else "资源库还是空的"
            controls: list[ft.Control] = [
                ft.Icon(ft.Icons.LIBRARY_MUSIC_OUTLINED, size=42, color=ACCENT_PRIMARY),
                ft.Text(message, color="grey", size=14),
            ]
            navigate = getattr(self.app_controller, "navigate_to_view", None)
            if not has_query and callable(navigate):
                controls.extend([
                    ft.Text("先在设置中添加仓库目录，再到系统工具扫描索引。",
                            color="grey", size=12),
                    ft.ElevatedButton(
                        "去设置仓库目录", icon=ft.Icons.SETTINGS,
                        on_click=lambda _e: navigate(3),
                    ),
                ])
            result.controls.append(ft.Container(
                alignment=ft.alignment.center,
                padding=40,
                content=ft.Column(controls,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=10),
            ))
            return cover_slots

        for item in items:
            rj_id = item["rj_id"]
            if item.get("subtitle_only"):
                result.controls.append(Styles.glass_container(ft.Column([
                    ft.Text(rj_id, weight=ft.FontWeight.BOLD),
                    ft.Row([_badge("有字幕包", ACCENT_PRIMARY), _badge("未入库", WARNING)]),
                    ft.TextButton("下载专辑", icon=ft.Icons.DOWNLOAD,
                                  on_click=lambda _, rid=rj_id: self.app_controller.start_download(rid)),
                ], spacing=4), padding=12))
                continue
            folder_path = item.get("folder_path", "") or ""
            folder_name = item.get("folder_name", rj_id) or rj_id
            display_name = folder_name if len(folder_name) <= 44 else folder_name[:41] + "…"
            cover = (ft.Container(height=180, bgcolor=BG_SURFACE_LIGHT, border_radius=14)
                     if self._layout == "grid" else None)

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
            if self._layout == "list" and not item.get("has_cover"):
                badges.append(_badge("无封面", WARNING))
            if item.get("archived_at"):
                badges.append(_badge("云盘资源", ACCENT_SECONDARY))
                if not folder_path:
                    badges.append(_badge("仅云端", BG_SURFACE_LIGHT))
            postprocess_status = str(item.get("postprocess_status") or "unknown")
            if (str(item.get("work_status") or "") == "completed"
                    and postprocess_status in {"completed", "not_required"}):
                badges.append(_badge("已完成", SUCCESS))
            elif folder_path and str(item.get("work_status") or "") == "completed":
                badges.append(_badge("待后处理", WARNING))

            if item.get("missing_lrc"):
                badges.append(_badge(f"缺 LRC {item['missing_lrc']}", WARNING))
            if item.get("missing_tags"):
                badges.append(_badge(f"缺 MP3 标签 {item['missing_tags']}", WARNING))
            if item.get("ignored_files"):
                badges.append(_badge(f"跳过 {item['ignored_files']} 个文件", BG_SURFACE_LIGHT))
            if folder_path and item.get("folder_available") is False:
                badges.append(_badge("目录暂不可用", WARNING))
            label = ft.Text(display_name, size=13, weight=ft.FontWeight.W_600, max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS, tooltip=folder_name)
            labels = ft.Row(badges, wrap=True, spacing=4)
            if cover is not None:
                cover_slots[rj_id] = (cover, labels)
                card = ft.Column([cover, labels, label], spacing=6)
            else:
                tag_buttons = [self._tag_button(tag) for tag in item.get("card_tags", [])]
                card = ft.Column([labels, label], spacing=5)
                if tag_buttons:
                    card.controls.append(ft.Row(tag_buttons, wrap=True, spacing=4))
            container = Styles.glass_container(card, padding=10)
            container.on_click = lambda e, selected=rj_id: self.select_album(selected)
            container.tooltip = f"查看 {rj_id} 的详情"
            result.controls.append(container)
        target = getattr(self, "_open_after_load", "")
        self._open_after_load = ""
        if target and any(row["rj_id"] == target for row in items):
            self.select_album(target)
        return cover_slots

    def _load_card_covers(self, generation: int, items: list[dict],
                          slots: dict[str, tuple[ft.Container, ft.Row]]) -> None:
        if not slots:
            return

        def worker():
            results = {}
            for item in items:
                if generation != self._load_generation:
                    break
                rid = item["rj_id"]
                if rid in slots:
                    results[rid] = _card_disk_state(
                        str(item.get("folder_path") or ""),
                        str(item.get("archive_cover_path") or ""),
                        str(item.get("scanned_at") or ""),
                        int(time.monotonic() // 30),
                    )
            return results

        def apply(results):
            if generation != self._load_generation:
                return
            for rid, (available, source) in results.items():
                slot, labels = slots[rid]
                slot.content = _cover_widget(source) if source else _no_cover_widget()
                if not source:
                    labels.controls.append(_badge("无封面", WARNING))
                if not available:
                    labels.controls.append(_badge("目录暂不可用", WARNING))
            self._safe_update()

        self.app_controller.run_blocking(worker, apply, action_label="加载专辑封面")

    def select_album(self, rj_id: str) -> None:
        """Select a poster and load its read-only detail off the UI thread."""
        self._selected_rj_id = str(rj_id or "").strip().upper()
        selected_rj = self._selected_rj_id
        self._detail_generation += 1
        generation = self._detail_generation
        self.detail_panel.content = ft.Container(
            padding=24,
            alignment=ft.alignment.center,
            content=ft.Column([
                ft.ProgressRing(width=24, height=24, stroke_width=2),
                ft.Text("正在读取专辑详情…", size=12, color=ACCENT_PRIMARY),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
        )
        self._safe_update()

        def worker() -> dict[str, Any]:
            detail = self.app_controller.db.get_library_detail(selected_rj)
            if not detail:
                return {"error": "未找到这张专辑的索引记录"}
            folder_path = str(detail.get("folder_path") or "")
            if folder_path and Path(folder_path).is_dir():
                detail["files"] = collect_file_preview(folder_path, FILE_PREVIEW_LIMIT)
                detail["asset_pending"] = True
                reader = getattr(self.app_controller.db, "get_downloads_by_rj", None)
                if callable(reader):
                    detail["incomplete"] = [
                        (row["track_title"], row["status"], row["error"])
                        for row in reader(selected_rj)
                        if row["status"] in {"failed", "paused", "ignored"}]
            elif detail.get("archived_at"):
                detail["files"] = {"items": [], "cloud_only": True}
            else:
                detail["files"] = {"items": [], "error": "本地专辑目录不存在"}
            detail["cover_source"] = _resolve_local_cover(
                folder_path, str(detail.get("archive_cover_path") or ""),
            )
            return detail

        def apply(detail: dict[str, Any]) -> None:
            if generation != self._detail_generation or not self._active:
                return
            self.detail_panel.content = self._detail_content(detail)
            self._safe_update()
            if not detail.get("asset_pending"):
                return

            def inspect():
                try:
                    return {"assets": inspect_album_assets(
                        Path(detail["folder_path"]).resolve(), selected_rj,
                        getattr(self.app_controller.config, "subtitle_archive_dir", ""))}
                except (OSError, ValueError) as exc:
                    return {"asset_error": str(exc)}

            def apply_assets(result):
                if generation != self._detail_generation or not self._active:
                    return
                updated = {**detail, **result, "asset_pending": False}
                self.detail_panel.content = self._detail_content(updated)
                self._safe_update()

            self.app_controller.run_blocking(inspect, apply_assets, action_label="检查专辑歌词和标签")

        self.app_controller.run_blocking(worker, apply, action_label="读取专辑详情")

    def _detail_content(self, detail: dict[str, Any]) -> ft.Control:
        if detail.get("error"):
            return ft.Container(padding=22, alignment=ft.alignment.center,
                content=ft.Text(str(detail["error"]), color=ERROR, size=13))
        rj_id = str(detail.get("rj_id") or "")
        folder_path = str(detail.get("folder_path") or "")
        title = str(detail.get("metadata_title") or detail.get("work_title") or detail.get("folder_name") or rj_id)
        circle = str(detail.get("metadata_circle") or detail.get("work_circle") or "未知社团")
        cover_source = detail.get("cover_source")
        # Keep the detail panel on the local-cover-only boundary.
        cover = _cover_widget(cover_source, 156) if cover_source else _no_cover_widget(156)
        metadata = detail.get("metadata_json") if isinstance(detail.get("metadata_json"), dict) else {}
        tags = list(dict.fromkeys([*_metadata_tags(metadata), *detail.get("album_tags", [])]))
        voice_actors = _metadata_voice_actors(metadata)
        files_snapshot = detail.get("files") or {}
        entries = files_snapshot.get("items") or []
        file_rows = [
            ft.Row([
                ft.Icon(_file_icon(entry.get("kind", "other")), size=15, color=ACCENT_SECONDARY),
                ft.Column([
                    ft.Text(entry.get("path", ""), size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(fmt_size(int(entry.get("size", 0))), size=10, color="grey"),
                ], expand=True, spacing=1),
            ], spacing=8)
            for entry in entries
        ] or [ft.Text(
            "云端归档记录；本地媒体已移除" if files_snapshot.get("cloud_only")
            else "未发现可显示的文件",
            size=12, color="grey",
        )]
        if files_snapshot.get("error"):
            file_rows = [ft.Text(str(files_snapshot["error"]), size=12, color=ERROR)]
        if files_snapshot.get("truncated"):
            file_rows.insert(0, ft.Text(
                f"仅显示前 {FILE_PREVIEW_LIMIT} 项；完整作品含 {int(detail.get('total_files', 0))} 个文件。",
                size=11, color=WARNING,
            ))
        badge_controls = [
            _badge(f"{int(detail.get('audio_count', 0))} 音频", SUCCESS),
            _badge(f"{int(detail.get('total_files', 0))} 文件", ACCENT_PRIMARY),
            _badge(fmt_size(int(detail.get('total_size', 0))), ACCENT_SECONDARY),
        ]
        if detail.get("archived_at"):
            badge_controls.append(_badge("云盘资源", ACCENT_SECONDARY))
            if not folder_path:
                badge_controls.append(_badge("仅云端", BG_SURFACE_LIGHT))
        if folder_path and str(detail.get("work_status") or "") == "completed":
            postprocess_status = str(detail.get("postprocess_status") or "unknown")
            badge_controls.append(_badge(
                "已完成" if postprocess_status in {"completed", "not_required"}
                else "待后处理",
                SUCCESS if postprocess_status in {"completed", "not_required"}
                else WARNING,
            ))
        badges = ft.Row(badge_controls, wrap=True, spacing=5)
        tag_row = ft.Row([self._tag_button(tag) for tag in tags], wrap=True, spacing=4, visible=bool(tags))
        return ft.Column([
            ft.Row([
                ft.Text("专辑详情", size=17, weight=ft.FontWeight.BOLD, expand=True),
                ft.IconButton(icon=ft.Icons.CONTENT_COPY_OUTLINED, tooltip="复制 RJ 编号",
                              on_click=lambda e, value=rj_id: self._copy_text(value, "RJ 编号")),
                ft.IconButton(icon=ft.Icons.CONTENT_COPY_OUTLINED, tooltip="复制专辑路径",
                              on_click=lambda e, value=folder_path: self._copy_text(value, "专辑路径"),
                              disabled=not bool(folder_path)),
                ft.IconButton(icon=ft.Icons.FOLDER_OPEN_OUTLINED, tooltip="打开专辑文件夹",
                              on_click=lambda e, path=folder_path: self._open_folder(path),
                              disabled=not bool(folder_path)),
            ], spacing=2),
            cover,
            ft.Text(title, size=14, weight=ft.FontWeight.W_600, max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS, tooltip=title),
            ft.Text(f"{rj_id} · {circle}", size=12, color=ACCENT_PRIMARY),
            *([ft.Text("声优：" + "、".join(voice_actors), size=11, color="grey")]
              if voice_actors else []),
            badges,
            tag_row,
            *([ft.Text(
                "归档位置：" + str(detail.get("archive_remote_path") or "未填写")
                + (" · " + str(detail.get("archive_provider")) if detail.get("archive_provider") else ""),
                size=11, color=ACCENT_SECONDARY, selectable=True,
            )] if detail.get("archived_at") else []),
            *self._album_actions(detail),
            ft.Divider(height=10),
            ft.Text("文件列表", size=14, weight=ft.FontWeight.BOLD),
            ft.ListView(file_rows, spacing=7, expand=True),
        ], spacing=8, expand=True)
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
        self._current_page = 0
        self.load_library()

    def _apply_anomalies(self, snapshot: dict[str, Any]) -> None:
        groups = snapshot.get("groups", {})
        selected = snapshot.get("selected", [])
        self._build_anomaly_chips(groups)
        self.summary_bar.value = self._summary_text(snapshot)
        self._anomaly_snapshot = selected
        pages = max(1, (len(selected) + ANOMALY_DISPLAY_LIMIT - 1) // ANOMALY_DISPLAY_LIMIT)
        page = max(0, min(int(snapshot.get("page", 0)), pages - 1))
        self._current_page = page
        search = snapshot.get("search", "")
        self.page_info.value = (
            f"第 {page + 1}/{pages} 页 · 共 {len(selected)} 项异常"
            + (f" · 搜索“{search}”" if search else "")
        )
        self.btn_prev.disabled = page == 0
        self.btn_next.disabled = page + 1 >= pages
        offset = page * ANOMALY_DISPLAY_LIMIT
        if not selected:
            self.anomaly_list.controls.append(ft.Container(
                padding=30,
                alignment=ft.alignment.center,
                content=ft.Text("当前筛选下没有异常", color=SUCCESS, size=14),
            ))
            return

        last_category = ""
        for anomaly in selected[offset:offset + ANOMALY_DISPLAY_LIMIT]:
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
                + (f"{int(anomaly.get('total_files', 0))} 文件 / "
                   f"{fmt_size(int(anomaly.get('total_size', 0)))}\n" if anomaly.get("indexed")
                   else "尚未统计文件\n") +
                f"{title}\n{local_path}"
            )
            self.anomaly_list.controls.append(Styles.glass_container(
                ft.Column([
                    ft.Text(category_label, size=11, color=WARNING),
                    ft.Text(line, size=11, selectable=True, font_family="Consolas"),
                    ft.Row([
                        ft.TextButton("打开目录", on_click=lambda _, path=local_path: self._open_folder(path)),
                        *([ft.TextButton("补录索引", on_click=lambda _, row=anomaly: self._index_anomaly(row))]
                          if category == "configured_root_not_indexed" else []),
                    ]),
                ], spacing=3),
                padding=10,
            ))

    def _backfill_completed(self, _event=None) -> None:
        def work():
            db = self.app_controller.db
            db.backup_library_catalog(app_path(".local_backups"))
            return db.backfill_downloaded_library(self._configured_roots())
        def done(result):
            self.app_controller.show_snack(
                f"已补录 {result['indexed']} 部，跳过 {len(result['skipped'])} 部")
            self.load_library()
        self._confirm("补录已下载专辑", [
            ft.Text("先备份数据库，再补录有音频且没有进行中任务的专辑。")],
            lambda: self.app_controller.run_blocking(work, done, action_label="补录已下载专辑"))

    def _export_anomaly_rows(self, _event=None) -> None:
        rows = list(self._anomaly_snapshot)
        if not rows:
            self.app_controller.show_snack("当前筛选没有可导出的异常")
            return
        def worker():
            directory = app_path("reports")
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"library-anomalies-{datetime.now():%Y%m%d-%H%M%S-%f}.csv"
            keys = ["rj_id", "category", "local_path", "works_status"]
            with target.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            return target
        self.app_controller.run_blocking(
            worker, lambda target: self.app_controller.show_snack(f"已导出 {target}"),
            action_label="导出异常")

    def _index_anomaly(self, row: dict) -> None:
        def worker():
            return self.app_controller.db.index_local_album(
                row["rj_id"], row["local_path"], self._configured_roots())
        self.app_controller.run_blocking(
            worker, lambda _: self.focus_album(row["rj_id"]), action_label="补录专辑索引")

    def _album_actions(self, detail: dict) -> list[ft.Control]:
        rid = detail["rj_id"]
        db = self.app_controller.db
        actions = []
        if hasattr(db, "set_library_favorite"):
            favorite = bool(detail.get("favorite"))
            actions.extend([
                ft.TextButton("取消收藏" if favorite else "收藏",
                              on_click=lambda _: self._album_action(
                                  rid, lambda: db.set_library_favorite(rid, not favorite), "更新收藏")),
                ft.TextButton("管理合集", on_click=lambda _: self._collection_dialog(rid)),
            ])
        if detail.get("archived_at") and hasattr(db, "update_cloud_archive_location"):
            actions.append(ft.TextButton("编辑云盘位置",
                                         on_click=lambda _: self._cloud_location_dialog(detail)))
        assets = detail.get("assets")
        note = []
        if assets:
            root = Path(detail["folder_path"]).resolve()
            if assets.audio:
                actions.append(ft.TextButton("播放专辑", icon=ft.Icons.PLAY_ARROW,
                                             on_click=lambda _: self._choose_playback_version(rid, root, assets.audio)))
            if assets.subtitles:
                actions.append(ft.TextButton("预览字幕匹配",
                                             on_click=lambda _: self._subtitle_dialog(rid, root, assets)))
            if assets.mp3_tasks:
                actions.append(ft.TextButton(f"补写 {len(assets.mp3_tasks)} 首 MP3 标签",
                                             on_click=lambda _: self._tag_dialog(rid, root, assets)))
            versions = Counter(
                path.relative_to(root).parent.as_posix() for path in assets.audio)
            version_text = " · ".join(f"{name if name != '.' else '根目录'} {count} 首"
                                      for name, count in versions.most_common(6))
            note.extend([
                ft.Text(f"本机字幕包 {assets.archives} · 可补 LRC {len(assets.subtitles)} · "
                        f"匹配待确认 {assets.unmatched}", size=11),
                ft.Text(version_text, size=11, tooltip=version_text) if version_text else ft.Text(""),
            ])
        incomplete = detail.get("incomplete") or []
        if incomplete:
            items = [ft.Text(f"{title} · {status} · {error or '无详情'}", size=11, selectable=True)
                     for title, status, error in incomplete]
            actions.append(ft.TextButton(
                f"查看异常与跳过项 ({len(items)})",
                on_click=lambda _: self._confirm("未完成文件", items)))
        if detail.get("asset_pending"):
            note.append(ft.Text("正在检查音轨、字幕和 MP3 标签…", size=11))
        if detail.get("asset_error"):
            note.append(ft.Text("素材盘点失败：" + detail["asset_error"], size=11, color=WARNING))
        return [ft.Row(actions, wrap=True, spacing=3), *note] if actions or note else []

    def _album_action(self, rid, worker, label):
        def done(result):
            self.app_controller.show_snack(f"{label}完成" + (f" · {result} 项" if type(result) is int else ""))
            self.select_album(rid)
        self.app_controller.run_blocking(worker, done, action_label=label)

    def _confirm(self, title, rows, callback=None):
        if not self.page:
            return
        dialog = ft.AlertDialog(
            modal=True, title=ft.Text(title),
            content=ft.Container(width=550, height=min(340, 48 + len(rows) * 22),
                                 content=ft.ListView(rows, spacing=4)),
        )
        def close(_event):
            self.page.close(dialog)
        dialog.actions = [ft.TextButton("关闭" if callback is None else "取消", on_click=close)]
        if callback:
            def accept(event):
                close(event)
                callback()
            dialog.actions.append(ft.FilledButton("应用", on_click=accept))
        self.page.open(dialog)

    def _subtitle_dialog(self, rid, root, assets):
        rows = [ft.Text(f"{item.source} → {item.destination.relative_to(root)}",
                        size=12, selectable=True) for item in assets.subtitles]
        if assets.unmatched:
            rows.insert(0, ft.Text(f"{assets.unmatched} 项匹配不明确，已留待手动核对", color=WARNING))
        def work():
            db = self.app_controller.db
            result = apply_subtitles(db, rid, root, assets)
            db.index_local_album(rid, root, self._configured_roots())
            return result
        self._confirm("字幕匹配预览", rows, lambda: self._album_action(rid, work, "补齐 LRC"))

    def _tag_dialog(self, rid, root, assets):
        rows = [ft.Text("先备份原 MP3，再补写缺少的标签。")]
        rows.extend(ft.Text(f"{path.name} · {'歌词 ' if lyric else ''}{'封面' if cover else ''}", size=12)
                    for path, lyric, cover in assets.mp3_tasks)
        def work():
            db = self.app_controller.db
            result = fill_mp3_tags(db, rid, root, assets, app_path(".local_backups", "mp3-tags"))
            db.index_local_album(rid, root, self._configured_roots())
            remaining = inspect_album_assets(root, rid, "")
            db.save_library_asset_checks([(rid, str(root), len(remaining.mp3_tasks))])
            return result
        self._confirm("补写 MP3 标签", rows, lambda: self._album_action(rid, work, "补写 MP3 标签"))

    def _cloud_location_dialog(self, detail):
        if not self.page:
            return
        rid = detail["rj_id"]
        location = ft.TextField(label="云盘归档位置",
                                value=str(detail.get("archive_remote_path") or ""),
                                max_length=2048)
        dialog = ft.AlertDialog(title=ft.Text("编辑云盘位置"), content=location)
        def save(_event):
            self.page.close(dialog)
            self._album_action(rid, lambda: self.app_controller.db.update_cloud_archive_location(
                rid, location.value or ""), "保存归档位置")
        dialog.actions = [ft.TextButton("取消", on_click=lambda _: self.page.close(dialog)),
                          ft.FilledButton("保存", on_click=save)]
        self.page.open(dialog)

    def _collection_dialog(self, rid):
        if not self.page:
            return
        field = ft.TextField(label="合集名称", max_length=48)
        dialog = ft.AlertDialog(title=ft.Text("管理自定义合集"), content=field)
        def save(remove):
            name = (field.value or "").strip()
            if name:
                self.page.close(dialog)
                self._album_action(rid, lambda: self.app_controller.db.set_library_collection(
                    rid, name, remove=remove), "更新合集")
        dialog.actions = [
            ft.TextButton("取消", on_click=lambda _: self.page.close(dialog)),
            ft.TextButton("从合集移出", on_click=lambda _: save(True)),
            ft.FilledButton("加入合集", on_click=lambda _: save(False)),
        ]
        self.page.open(dialog)

    def _choose_playback_version(self, rid, root, audio):
        versions = {}
        for path in audio:
            versions.setdefault(path.parent.relative_to(root).as_posix(), []).append(path)
        if len(versions) == 1:
            self._play_album(rid, audio)
            return
        if not self.page:
            return
        dialog = ft.AlertDialog(title=ft.Text("选择播放版本"))
        def play(paths):
            self.page.close(dialog)
            self._play_album(rid, paths)
        dialog.content = ft.Container(width=460, height=min(320, 45 * len(versions)),
            content=ft.ListView([ft.TextButton(
                f"{name if name != '.' else '根目录'} · {len(paths)} 首",
                on_click=lambda _, selected=tuple(paths): play(selected))
                for name, paths in sorted(versions.items())]))
        dialog.actions = [ft.TextButton("取消", on_click=lambda _: self.page.close(dialog)),
                          ft.TextButton("播放全部音轨", on_click=lambda _: play(audio))]
        self.page.open(dialog)

    def _play_album(self, rid, audio):
        def work():
            directory = app_path("library_playlists")
            directory.mkdir(parents=True, exist_ok=True)
            playlist = directory / f"{rid}.m3u8"
            def track_order(path):
                return (str(path.parent).casefold(), [
                    (0, int(part)) if part.isdigit() else (1, part.casefold())
                    for part in re.split(r"(\d+)", path.name)
                ])
            ordered = sorted((path for path in audio if path.is_file()), key=track_order)
            if not ordered:
                raise ValueError("没有可打开的本地音频")
            playlist.write_text("#EXTM3U\n" + "\n".join(map(str, ordered)) + "\n", encoding="utf8")
            try:
                if platform.system() == "Windows":
                    os.startfile(str(playlist))
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", str(playlist)])
                else:
                    subprocess.Popen(["xdg-open", str(playlist)])
            except OSError:
                if platform.system() != "Windows":
                    raise
                os.startfile(str(ordered[0]))
            self.app_controller.db.set_library_last_played(rid)
        self._album_action(rid, work, "打开播放器")

    def _open_folder(self, path: str) -> None:
        success, message = open_folder(path)
        if not success:
            self.app_controller.show_snack(message)

    def _copy_text(self, value: str, label: str) -> None:
        if not value:
            self.app_controller.show_snack(f"{label}为空，无法复制")
            return
        try:
            if self.page:
                self.page.set_clipboard(value)
            self.app_controller.show_snack(f"已复制{label}")
        except Exception as exc:
            self.app_controller.show_snack(f"复制{label}失败：{exc}")


def collect_file_preview(folder_path: str, limit: int = FILE_PREVIEW_LIMIT) -> dict[str, Any]:
    """Enumerate at most ``limit`` files for a detail panel, never a full scan."""
    root = Path(folder_path)
    if not root.is_dir():
        return {"items": [], "truncated": False, "error": "专辑文件夹不存在或无法访问"}
    preview: list[dict[str, Any]] = []
    try:
        for current, directories, names in os.walk(root):
            directories.sort(key=str.casefold)
            names.sort(key=str.casefold)
            for name in names:
                candidate = Path(current) / name
                try:
                    size = candidate.stat().st_size
                except OSError:
                    size = 0
                preview.append({
                    "path": str(candidate.relative_to(root)).replace("\\", "/"),
                    "size": size,
                    "kind": _file_kind(candidate.suffix),
                })
                if len(preview) > max(1, int(limit)):
                    return {"items": preview[:-1], "truncated": True}
    except OSError as exc:
        return {"items": preview, "truncated": False, "error": f"读取文件列表失败: {exc}"}
    return {"items": preview, "truncated": False}


def _file_kind(suffix: str) -> str:
    extension = str(suffix or "").lower()
    if extension in {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac"}:
        return "audio"
    if extension in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return "image"
    if extension in {".mp4", ".mkv", ".webm", ".avi"}:
        return "video"
    return "other"


def _file_icon(kind: str):
    return {
        "audio": ft.Icons.AUDIOTRACK_OUTLINED,
        "image": ft.Icons.IMAGE_OUTLINED,
        "video": ft.Icons.MOVIE_OUTLINED,
    }.get(kind, ft.Icons.INSERT_DRIVE_FILE_OUTLINED)


def _metadata_tags(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("tags") or metadata.get("tag") or []
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        raw = [raw]
    tags: list[str] = []
    for item in raw:
        value = item.get("name") if isinstance(item, dict) else item
        value = str(value or "").strip()
        if value and value not in tags:
            tags.append(value)
    return tags

def _metadata_voice_actors(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("vas") or metadata.get("voice_actors") or []
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        raw = [raw]
    names: list[str] = []
    for item in raw:
        value = item.get("name") if isinstance(item, dict) else item
        value = str(value or "").strip()
        if value and value not in names:
            names.append(value)
    return names


def _badge(text: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=9, color="white"),
        bgcolor=color,
        border_radius=999,
        padding=ft.padding.symmetric(horizontal=6, vertical=2),
    )


@lru_cache(maxsize=512)
def _card_disk_state(folder_path: str, archive_cover_path: str,
                     scanned_at: str, interval: int) -> tuple[bool, str | None]:
    available = not folder_path or Path(folder_path).is_dir()
    source = _resolve_local_cover(folder_path if available else "", archive_cover_path)
    thumbnail = get_cover_thumbnail(source) if source else None
    return available, str(thumbnail) if thumbnail else None


def _resolve_local_cover(folder_path: str, archive_cover_path: str = "") -> str | None:
    if folder_path:
        cover = find_local_cover(folder_path)
        if cover:
            return str(cover)
    cached = Path(archive_cover_path) if archive_cover_path else None
    return str(cached) if cached and cached.is_file() else None


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
