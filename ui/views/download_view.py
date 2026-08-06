"""Service-backed active download queue for ARSM Suite 0.9.0-rc.2.

The release-tested card implementation remains in ``download_view_base``.
This layer replaces per-card SQLite reads with a bounded queue snapshot, adds
pagination and side-effect-free batch preview, and preserves the RC2 speed and
completion behaviour.
"""

from __future__ import annotations

import copy
import logging
import time
from pathlib import Path
from typing import Any, Dict

import flet as ft

import ui.views.download_view_base as base_module
from core.read_models import BatchEnqueuePreview, DownloadQueueItem, DownloadQueuePage
from core.services.download_service import DownloadService
from core.status import WorkStatus
from ui.theme import (ACCENT_PRIMARY, ACCENT_SECONDARY, SUCCESS, WARNING,
                      ERROR, Styles)
from ui.views.download_view_base import DownloadView as BaseDownloadView

QUEUE_FILE = base_module.QUEUE_FILE
platform = base_module.platform
subprocess = base_module.subprocess


class DownloadView(BaseDownloadView):
    """Paged queue UI backed by immutable read models."""

    def __init__(self, app_controller):
        self.global_speed_bps = 0.0
        self._active = True
        self._queue_refreshing = False
        self.queue_filter = "working"
        self.queue_page = 1
        self.queue_page_size = 24
        self.queue_model: DownloadQueuePage | None = None
        self._transient_rj_ids: list[str] = []
        config = app_controller.config
        self.download_service = DownloadService(
            app_controller.db,
            output_dir=config.output_dir,
            library_paths=getattr(config, "library_paths", ()),
        )
        # Issue #19 state MUST exist before base __init__ runs load_queue(),
        # which renders the page and touches these attributes.
        self._selected_rj: str | None = None
        self._card_controls: Dict[str, Any] = {}      # rj_id -> stable card
        self._detail_rows: Dict[str, Any] = {}         # file key -> stable row
        self._detail_key_by_title: Dict[str, str] = {}  # basename -> key (1st)
        self._detail_key_by_track: Dict[str, Dict[str, str]] = {}  # rj->track_id->key
        self._detail_page = 1
        self._detail_page_size = 200
        self._active_ns: Dict[str, str] = {}
        # Issue #3 (review): queue snapshots are fetched + disk-verified off the
        # UI thread; generation drops stale results.
        self._queue_generation = 0
        self._queue_refresh_pending = False
        super().__init__(app_controller)

        self.btn_resume_all.text = "全部继续"
        self.download_btn.text = "预览并添加"
        self.rj_input.hint_text = "支持 RJ 号、纯数字、ASMR.one 链接及批量粘贴"

        # Flet 0.27.6 native FilePicker proved unreliable in the isolated
        # Windows acceptance environment.  Keep the legacy object available to
        # the RC1 base class, but remove it from the active UI path and page
        # overlay.  Batch input now uses an in-app multiline paste dialog that
        # is deterministic, keyboard-friendly and automatable.
        overlay = getattr(self.app_controller.page, "overlay", None)
        if overlay is not None:
            while self.file_picker in overlay:
                overlay.remove(self.file_picker)
        self.batch_btn.text = "批量粘贴"
        self.batch_btn.icon = ft.Icons.CONTENT_PASTE
        self.batch_btn.tooltip = "粘贴多行 RJ、纯数字或 ASMR.one 链接"
        self.batch_btn.on_click = self._open_batch_paste_dialog
        self._batch_paste_dialog = None
        self._batch_paste_input = None

        self.queue_filter_dropdown = ft.Dropdown(
            width=150,
            value=self.queue_filter,
            options=[
                ft.dropdown.Option(key="working", text="活动任务"),
                ft.dropdown.Option(key="active", text="下载中"),
                ft.dropdown.Option(key="queued", text="等待中"),
                ft.dropdown.Option(key="paused", text="已暂停"),
                ft.dropdown.Option(key="failed", text="失败"),
                ft.dropdown.Option(key="completed", text="已完成"),
                ft.dropdown.Option(key="cancelled", text="已取消"),
                ft.dropdown.Option(key="all", text="全部"),
            ],
            on_change=self._on_filter_change,
        )
        self.queue_refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH,
            tooltip="刷新队列",
            on_click=lambda _e: self.refresh_queue_async(),
        )
        self.queue_prev_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT,
            tooltip="上一页",
            on_click=self._previous_page,
        )
        self.queue_next_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT,
            tooltip="下一页",
            on_click=self._next_page,
        )
        self.queue_page_label = ft.Text("第 1 / 1 页", size=12, color="grey")
        toolbar = ft.Row(
            [
                ft.Text("筛选", size=12, color="grey"),
                self.queue_filter_dropdown,
                self.queue_refresh_btn,
                ft.Container(expand=True),
                self.queue_prev_btn,
                self.queue_page_label,
                self.queue_next_btn,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
        )
        # Base layout: file picker, title, input, batch controls, divider,
        # queue heading, queue list.  Insert queue tools before the heading.
        self.content.controls.insert(5, toolbar)

        # ── Issue #19: stable left task list + right file-detail panel. ──
        self.detail_title = ft.Text(
            "作品详情", size=16, weight=ft.FontWeight.W_600, color=ACCENT_PRIMARY)
        self.detail_summary = ft.Text("", size=12, color="grey")
        self.detail_progress = ft.ProgressBar(value=0.0, color=ACCENT_PRIMARY)
        self.detail_header_more = ft.Text("", size=11, color="grey")
        self.detail_prev_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT, tooltip="上一页", on_click=self._detail_prev)
        self.detail_next_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT, tooltip="下一页", on_click=self._detail_next)
        self.detail_scroll = ft.ListView(expand=True, spacing=2, padding=4)
        self.detail_empty = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.FOLDER_OPEN, color="grey", size=44),
                ft.Text("点击左侧任务查看文件详情", color="grey"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            alignment=ft.alignment.center, expand=True, padding=40)
        self.detail_page_bar = ft.Row(
            [self.detail_prev_btn, self.detail_header_more, self.detail_next_btn],
            alignment=ft.MainAxisAlignment.CENTER, spacing=10)

        self.detail_panel = ft.Container(
            expand=True, padding=ft.padding.only(left=12, right=4, top=4, bottom=4),
            content=ft.Column([
                self.detail_title,
                self.detail_summary,
                self.detail_progress,
                ft.Divider(height=6, color="transparent"),
                ft.Container(expand=True, content=self.detail_scroll),
                self.detail_page_bar,
            ], spacing=6, expand=True),
        )

        heading = self.content.controls[4]
        left_pane = ft.Column(
            [heading, toolbar, self.queue_list], expand=True, spacing=6)
        split = ft.Row(
            [left_pane, self.detail_panel], expand=True, spacing=8)
        self.content.controls = [
            self.content.controls[0],   # title
            self.content.controls[1],   # input row
            self.content.controls[2],   # batch/controls row
            self.content.controls[3],   # divider
            split,
        ]
        # NOTE: no reload_queue_from_database() here.  The base constructor
        # already ran load_queue() (which routes through the SAME pipeline as
        # refresh_queue_async), so another call would start a SECOND full
        # fetch + disk-verification query at startup (review #2).

    @staticmethod
    def _sync_queue_file() -> None:
        base_module.QUEUE_FILE = QUEUE_FILE

    def save_queue(self):
        self._sync_queue_file()
        return super().save_queue()

    def set_active(self, active: bool) -> None:
        active = bool(active)
        changed = active != self._active
        self._active = active
        if active and changed:
            self.refresh_queue_async()

    def load_queue(self):
        """Initial queue snapshot; called by the base constructor.

        Routes through the SAME ``_queue_refreshing``/generation pipeline as
        ``refresh_queue_async`` so startup issues exactly ONE fetch + disk
        verification query: any later ``reload_queue_from_database`` request is
        coalesced into that in-flight query instead of starting a second one.
        The DB fetch + stat runs off the UI thread via ``run_blocking``.
        """
        self._sync_queue_file()
        self.refresh_queue_async(force=True)

    def reload_queue_from_database(self, *, reset_speed: bool = False):
        if reset_speed:
            self.global_speed_bps = 0.0
        self.refresh_queue_async(force=True)

    def refresh_queue_async(self, *, reset_page: bool = False, force: bool = False):
        """Fetch + disk-verify the queue OFF the UI thread (review #3).

        ``fetch_queue_page`` + ``apply_disk_verification`` (per-file ``stat``)
        run through ``app_controller.run_blocking`` (``asyncio.to_thread``); the
        result is marshalled back to the UI thread and dropped if a newer
        refresh superseded it (generation token).  At most one query is in
        flight; extra requests are coalesced into one pending relaunch.
        """
        if reset_page:
            self.queue_page = 1
        if not self._active and not force:
            return
        self._queue_generation += 1
        generation = self._queue_generation
        if self._queue_refreshing:
            # A query is already in flight; remember a newer snapshot is wanted
            # and let the in-flight callback relaunch with the latest state.
            self._queue_refresh_pending = True
            return
        self._launch_queue_query(generation)

    def _launch_queue_query(self, generation: int) -> None:
        self._queue_refreshing = True
        self._queue_refresh_pending = False
        if hasattr(self, "queue_refresh_btn"):
            self.queue_refresh_btn.disabled = True

        status_filter = self.queue_filter
        page = self.queue_page
        page_size = self.queue_page_size

        def query():
            return self.download_service.apply_disk_verification(
                self.download_service.fetch_queue_page(
                    status_filter=status_filter,
                    page=page,
                    page_size=page_size,
                ),
                status_filter=status_filter,
            )

        def render(result):
            if generation != self._queue_generation:
                # Superseded by a newer request: never apply a stale snapshot.
                self._queue_refreshing = False
                if self._queue_refresh_pending:
                    self.refresh_queue_async(force=True)
                return
            self._queue_refreshing = False
            self._apply_queue_page(result)
            self._safe_update(getattr(self, "queue_refresh_btn", None))
            if self._queue_refresh_pending:
                self.refresh_queue_async(force=True)

        try:
            self.app_controller.run_blocking(query, render)
        except Exception as exc:
            self._queue_refreshing = False
            if hasattr(self, "queue_refresh_btn"):
                self.queue_refresh_btn.disabled = False
            self.app_controller.show_snack(f"队列读取失败: {exc}")

    @staticmethod
    def _enum_for_item(item: DownloadQueueItem) -> WorkStatus:
        return {
            "active": WorkStatus.DOWNLOADING,
            "queued": WorkStatus.QUEUED,
            "paused": WorkStatus.PAUSED,
            "failed": WorkStatus.FAILED,
            "completed": WorkStatus.COMPLETED,
            "cancelled": WorkStatus.CANCELLED,
            "partial": WorkStatus.PARTIAL,
        }.get(item.queue_state, WorkStatus.normalize(item.work_status))

    def _apply_queue_page(self, model: DownloadQueuePage) -> None:
        previous = self.active_downloads
        model_ids = {item.rj_id for item in model.items}
        self._transient_rj_ids = [
            value for value in self._transient_rj_ids if value not in model_ids
        ]
        current: Dict[str, Dict[str, Any]] = {}
        for item in model.items:
            data = previous.get(item.rj_id, {})
            data.setdefault("tracks", {})
            data.update(
                status=item.ui_status,
                snapshot=item,
                control=None,
                last_time=data.get("last_time", time.time()),
                last_bytes=data.get("last_bytes", 0),
                cache_hit=data.get("cache_hit", False),
                _derived_enum=self._enum_for_item(item),
            )
            if item.current_file and not data.get("current_track"):
                data["current_track"] = item.current_file
            current[item.rj_id] = data

        if model.page == 1 and self.queue_filter == "working":
            remaining = max(0, model.page_size - len(current))
            for rj_id in self._transient_rj_ids[:remaining]:
                if rj_id in current:
                    continue
                current[rj_id] = previous.get(rj_id, {
                    "status": "准备中...",
                    "tracks": {},
                    "control": None,
                    "last_time": time.time(),
                    "last_bytes": 0,
                    "cache_hit": False,
                })

        self.active_downloads = current
        self.queue_model = model
        self.queue_page = model.page
        self._render_queue_page()

    def _render_queue_page(self) -> None:
        """Issue #19: incremental, order-stable render.

        Card Controls are kept per RJ and reused across refreshes; only their
        field values change.  The ListView is re-ordered with the SAME control
        instances (no clear + full rebuild), so cards never flash or swap.
        """
        ordered = list(self.active_downloads.keys())
        if not ordered:
            self.queue_list.controls.clear()
            self.queue_list.controls.append(
                ft.Container(
                    content=ft.Text("当前筛选没有任务", color="grey"),
                    alignment=ft.alignment.center,
                    padding=30,
                )
            )
        else:
            # Reuse stable controls; create only for new RJs.
            for rj_id in ordered:
                if rj_id not in self._card_controls:
                    self.build_queue_item(rj_id, update_list=False)
                else:
                    self._update_compact_card(rj_id)
            # Drop cards for RJs that left the page/filter.
            stale = [r for r in self._card_controls if r not in set(ordered)]
            for rj_id in stale:
                self._card_controls.pop(rj_id, None)
            self.queue_list.controls[:] = [
                self._card_controls[rj_id] for rj_id in ordered
                if rj_id in self._card_controls
            ]
        self._update_queue_summary()
        self._update_pagination()
        self._render_detail_panel_if_selected()
        self._safe_update(self.queue_list)

    def _on_filter_change(self, event):
        self.queue_filter = getattr(event.control, "value", None) or "working"
        self.refresh_queue_async(reset_page=True)

    def _previous_page(self, _event):
        if self.queue_page > 1:
            self.queue_page -= 1
            self.refresh_queue_async()

    def _next_page(self, _event):
        page_count = self.queue_model.page_count if self.queue_model else 1
        if self.queue_page < page_count:
            self.queue_page += 1
            self.refresh_queue_async()

    def _update_pagination(self):
        if not hasattr(self, "queue_page_label"):
            return
        page_count = self.queue_model.page_count if self.queue_model else 1
        self.queue_page_label.value = f"第 {self.queue_page} / {page_count} 页"
        self.queue_prev_btn.disabled = self.queue_page <= 1
        self.queue_next_btn.disabled = self.queue_page >= page_count
        for control in (self.queue_page_label, self.queue_prev_btn, self.queue_next_btn):
            self._safe_update(control)

    @staticmethod
    def _safe_update(control) -> None:
        if control is None:
            return
        try:
            if control.page:
                control.update()
        except Exception:
            pass

    def _set_batch_controls_busy(self):
        self.btn_pause_all.disabled = True
        self.btn_resume_all.disabled = True
        self._safe_update(self.btn_pause_all)
        self._safe_update(self.btn_resume_all)

    def _batch_pause(self):
        self._set_batch_controls_busy()
        self.app_controller.pause_all_downloads()

    def _batch_resume(self):
        self._set_batch_controls_busy()
        self.app_controller.resume_all_downloads()

    @staticmethod
    def _format_speed(speed_bps: float) -> str:
        speed = max(0.0, float(speed_bps or 0.0))
        if speed >= 1024 ** 3:
            return f"{speed / 1024 ** 3:.2f} GB/s"
        if speed >= 1024 ** 2:
            return f"{speed / 1024 ** 2:.1f} MB/s"
        if speed >= 1024:
            return f"{speed / 1024:.0f} KB/s"
        return f"{speed:.0f} B/s"

    def _update_queue_summary(self, _visible_items=None):
        if self.queue_model is None:
            counts = {"active": 0, "queued": 0, "paused": 0, "failed": 0, "cancelled": 0}
            for data in self.active_downloads.values():
                state = self.normalize_status(data.get("status", ""))
                if state in {"downloading", "resuming"}:
                    counts["active"] += 1
                elif state in counts:
                    counts[state] += 1
            total = len(self.active_downloads)
            completed = 0
        else:
            summary = self.queue_model.summary
            counts = {
                "active": summary.active_tasks,
                "queued": summary.queued_tasks + len(self._transient_rj_ids),
                "paused": summary.paused_tasks,
                "failed": summary.failed_tasks,
                "cancelled": summary.cancelled_tasks,
            }
            total = summary.total_tasks + len(self._transient_rj_ids)
            completed = summary.completed_tasks
        if counts["active"] == 0:
            self.global_speed_bps = 0.0
        shown = self.queue_model.total_items if self.queue_model else len(self.active_downloads)
        self.queue_summary.value = (
            f"当前筛选 {shown} / 全部 {total}"
            f"  下载中 {counts['active']}"
            f"  排队 {counts['queued']}"
            f"  暂停 {counts['paused']}"
            f"  失败 {counts['failed']}"
            f"  已取消 {counts['cancelled']}"
            f"  完成 {completed}"
            f"  总速度 {self._format_speed(self.global_speed_bps)}"
        )
        self.btn_pause_all.disabled = counts["active"] + counts["queued"] == 0
        self.btn_resume_all.disabled = counts["paused"] + counts["failed"] == 0
        for control in (self.queue_summary, self.btn_pause_all, self.btn_resume_all):
            self._safe_update(control)

    @staticmethod
    def _live_known_totals(item_data: Dict[str, Any]) -> tuple[int, int]:
        """Sum (downloaded, total) over track_id-keyed LIVE progress.

        Unknown-size files (``total <= 0``) never enter either the numerator
        or the denominator, and duplicate filenames stay separate because the
        live cache is keyed by track_id (not the bare title).
        """
        live = item_data.get("_live_tracks")
        if not live:
            return 0, 0
        downloaded = 0
        total = 0
        for info in live.values():
            expected = max(0, int(info.get("total", 0) or 0))
            if expected <= 0:
                continue
            total += expected
            downloaded += min(max(0, int(info.get("downloaded", 0) or 0)), expected)
        return downloaded, total

    def _get_progress_value(self, item_data: Dict[str, Any]) -> float:
        """Single authoritative overall progress for BOTH card and detail.

        Live track_id-keyed known-size progress wins once it exists; the disk
        snapshot is only the baseline before live data is established, so a
        resuming work's bar moves instead of sitting on the last scan.
        """
        live_downloaded, live_total = self._live_known_totals(item_data)
        if live_total > 0:
            return max(0.0, min(1.0, live_downloaded / live_total))
        snapshot = item_data.get("snapshot")
        if isinstance(snapshot, DownloadQueueItem):
            return snapshot.progress
        return 0.0

    def _find_work_dir(self, rj_id: str) -> Path | None:
        snapshot = self.active_downloads.get(rj_id, {}).get("snapshot")
        if isinstance(snapshot, DownloadQueueItem) and snapshot.local_path:
            return Path(snapshot.local_path)
        return super()._find_work_dir(rj_id)

    def _resolve_cover_source(self, rj_id: str):
        """Never hand a remote URL to Flet; only use the core-managed local cache."""
        return super()._resolve_cover_source(rj_id)

    def build_queue_item(self, rj_id: str, update_list: bool = True):
        """Ensure a stable compact card exists for ``rj_id`` and refresh its
        field values.  Never recreates the Control for an existing RJ."""
        container = self._card_controls.get(rj_id)
        if container is None:
            container = self._make_compact_card(rj_id)
            self._card_controls[rj_id] = container
        self._update_compact_card(rj_id)
        data = self.active_downloads.get(rj_id)
        if data:
            data["control"] = container
        if update_list:
            self._safe_update(container)

    def _make_compact_card(self, rj_id: str):
        """Build one stable card: cover, title/circle, status, ONE progress bar,
        downloaded/total, speed/ETA and per-state action buttons."""
        data = self.active_downloads.get(rj_id, {})
        title_text = ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=16,
                             selectable=True, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        status_text = ft.Text("", size=12, weight=ft.FontWeight.W_600)
        size_text = ft.Text("", size=11, color="grey")
        speed_text = ft.Text("", size=11, color=ACCENT_SECONDARY)
        prog_bar = ft.ProgressBar(value=0.0, color=ACCENT_PRIMARY, expand=True)
        pct_text = ft.Text("0%", size=11, color="grey")
        progress_row = ft.Row([prog_bar, pct_text], spacing=6,
                              vertical_alignment=ft.CrossAxisAlignment.CENTER)
        actions_row = ft.Row(spacing=0)

        main_info = ft.Column([
            ft.Row([title_text], spacing=0),
            ft.Row([status_text], spacing=0),
            actions_row,
            ft.Row([size_text, ft.Container(expand=True), speed_text], spacing=4,
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            progress_row,
        ], spacing=3, expand=True)

        def on_click(_e, r=rj_id):
            self._select_rj(r)

        tile = ft.Container(
            on_click=on_click,
            content=ft.Row([
                self._build_cover(rj_id, width=52, height=52),
                ft.Container(main_info, expand=True,
                             padding=ft.padding.only(left=10, right=10)),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
        )
        container = Styles.glass_container(tile, padding=12)
        container.data = rj_id
        for ref, value in (("title_text", title_text), ("status_text", status_text),
                           ("size_text", size_text), ("speed_text", speed_text),
                           ("prog_bar", prog_bar), ("pct_text", pct_text),
                           ("actions_row", actions_row)):
            data[ref] = value
        return container

    def _update_compact_card(self, rj_id: str) -> None:
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        container = self._card_controls.get(rj_id)
        if container is None:
            return
        snapshot = data.get("snapshot")
        title = getattr(snapshot, "title", None) if isinstance(
            snapshot, DownloadQueueItem) else None
        if title:
            human = title if title != rj_id else rj_id
            if getattr(snapshot, "circle", None):
                human = f"{human}  ·  {snapshot.circle}"
            data["title_text"].value = human
        status = data.get("status", "")
        ns = self.normalize_status(status)
        cache = " [缓存]" if data.get("cache_hit") else ""
        colors = {"downloading": SUCCESS, "queued": ACCENT_SECONDARY,
                  "paused": WARNING, "failed": ERROR, "cancelled": WARNING,
                  "completed": SUCCESS, "metadata_failed": ERROR,
                  "no_pending": WARNING, "duplicate": "grey",
                  "partial": WARNING}
        data["status_text"].value = status + cache
        data["status_text"].color = colors.get(ns, ACCENT_PRIMARY)

        prog = self._get_progress_value(data)
        # Once live progress exists it wins (a resuming work's bar must move,
        # not sit on the last disk scan).  Only when there is no live data do
        # we let terminal display obey disk verification — and if no disk
        # verification ran at all, trust the DB terminal label.
        live_downloaded, live_total = self._live_known_totals(data)
        has_live = live_total > 0
        if not has_live and isinstance(snapshot, DownloadQueueItem):
            if snapshot.verified_progress is None and ns in {"completed", "verified"}:
                prog = 1.0
        data["prog_bar"].value = prog
        data["pct_text"].value = f"{prog * 100:.0f}%"

        # Only swap the action buttons when the status bucket changes.
        if ns != self._active_ns.get(rj_id):
            self._active_ns[rj_id] = ns
            data["actions_row"].controls = self._build_compact_actions(ns, rj_id)

        # Display known-size verified bytes/total when available (unknown-size
        # files are excluded from both), otherwise verified bytes vs DB total.
        if isinstance(snapshot, DownloadQueueItem):
            if snapshot.verified_known_bytes is not None:
                downloaded = snapshot.verified_known_bytes
                total = snapshot.verified_expected_bytes or 0
            else:
                verified = snapshot.verified_bytes
                downloaded = verified if verified is not None else snapshot.downloaded_bytes
                total = snapshot.total_bytes
        else:
            downloaded = total = 0
        data["size_text"].value = (
            f"{self._format_bytes(downloaded)} / {self._format_bytes(total)}"
        ) if (total or downloaded) else ""

        speed = data.get("last_speed_bps", 0)
        value = self._format_speed(speed) if speed > 0 else ""
        eta = data.get("last_eta")
        if value and eta:
            value += f"  ETA {eta:.0f}s"
        data["speed_text"].value = value

        # Selection highlight: accent bar on the left edge of the glass card.
        selected = rj_id == self._selected_rj
        edge = ACCENT_PRIMARY if selected else ft.Colors.with_opacity(0.2, "white")
        container.border = ft.Border(
            left=ft.BorderSide(3, edge),
            top=ft.BorderSide(1, ft.Colors.with_opacity(0.2, "white")),
            right=ft.BorderSide(1, ft.Colors.with_opacity(0.2, "white")),
            bottom=ft.BorderSide(1, ft.Colors.with_opacity(0.2, "white")),
        )

    def _build_compact_actions(self, ns: str, rj_id: str) -> list:
        """One action set per state (review #6): a card never shows both
        "暂停" and "继续" at once."""
        actions = []
        push = actions.append

        def open_btn(tooltip="打开目录"):
            return ft.IconButton(
                icon=ft.Icons.FOLDER_OPEN, tooltip=tooltip,
                icon_color=ACCENT_SECONDARY,
                on_click=lambda e, r=rj_id: self._open_work_dir(r))

        def remove_btn(tooltip="移除"):
            return ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, tooltip=tooltip,
                icon_color=ERROR,
                on_click=lambda e, r=rj_id: self.cancel_item(r))

        if ns in {"downloading", "queued", "resuming"}:
            push(ft.IconButton(icon=ft.Icons.PAUSE, tooltip="暂停",
                               icon_color=ACCENT_PRIMARY,
                               on_click=lambda e, r=rj_id: self.toggle_pause(r)))
            push(open_btn())
            push(remove_btn())
        elif ns == "paused":
            push(ft.IconButton(icon=ft.Icons.PLAY_ARROW, tooltip="继续下载",
                               icon_color=SUCCESS,
                               on_click=lambda e, r=rj_id: self.toggle_pause(r)))
            push(open_btn())
            push(remove_btn())
        elif ns == "failed":
            push(ft.IconButton(icon=ft.Icons.REPLAY, tooltip="重试下载",
                               icon_color=ACCENT_PRIMARY,
                               on_click=lambda e, r=rj_id: self._retry_failed(r)))
            push(open_btn())
            push(remove_btn())
        elif ns in {"metadata_failed", "no_pending"}:
            push(ft.IconButton(icon=ft.Icons.REFRESH, tooltip="重新准备",
                               icon_color=ACCENT_PRIMARY,
                               on_click=lambda e, r=rj_id: self._retry_prepare(r)))
            push(open_btn())
            push(remove_btn())
        elif ns == "partial":
            push(ft.IconButton(icon=ft.Icons.REFRESH, tooltip="重新准备补全",
                               icon_color=WARNING,
                               on_click=lambda e, r=rj_id: self._retry_prepare(r)))
            push(open_btn())
            push(remove_btn("清理"))
        elif ns == "duplicate":
            push(ft.IconButton(icon=ft.Icons.FORCE_GRAPH_3, tooltip="仍然下载",
                               icon_color=WARNING,
                               on_click=lambda e, r=rj_id: self._force_download(r)))
            push(remove_btn("清理"))
        elif ns == "cancelled":
            push(ft.IconButton(icon=ft.Icons.REPLAY, tooltip="继续已取消任务",
                               icon_color=SUCCESS,
                               on_click=lambda e, r=rj_id:
                                   self.app_controller.resume_cancelled_download(r)))
            push(open_btn())
        return actions

    @staticmethod
    def _format_bytes(size: int) -> str:
        size = max(0, int(size or 0))
        if size >= 1024 ** 3:
            return f"{size / 1024 ** 3:.2f} GB"
        if size >= 1024 ** 2:
            return f"{size / 1024 ** 2:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B"

    # ══════════════════════════════════════════════
    #  Issue #19: selection + right-side file detail panel
    # ══════════════════════════════════════════════
    def _select_rj(self, rj_id: str) -> None:
        if rj_id == self._selected_rj and self.detail_scroll.controls:
            return
        width = getattr(getattr(self.app_controller, "page", None), "width", None)
        if width is not None and width < 900:
            # Narrow window: degrade to the detail dialog instead of the panel.
            self._selected_rj = rj_id
            self.show_detailed_progress(rj_id)
            return
        self._selected_rj = rj_id
        self._detail_page = 1
        self._render_detail_panel(rj_id)
        for rid in list(self._card_controls):
            self._update_compact_card(rid)
        self._safe_update(self.detail_panel)

    def _render_detail_panel_if_selected(self) -> None:
        if self._selected_rj and self._selected_rj in self.active_downloads:
            self._render_detail_panel(self._selected_rj)
        elif self._selected_rj:
            self._selected_rj = None
            self.detail_scroll.controls.clear()
            self.detail_summary.value = ""
            self.detail_progress.value = None
            self.detail_header_more.value = ""
            self._safe_update(self.detail_panel)

    def _file_details(self, rj_id: str) -> list:
        """File tree rows for the right panel.

        Keys are normalized relative paths (never bare titles) so duplicate
        filenames cannot collide.  Live in-memory progress is matched to the
        matching DB row (by download id first, then by basename) and never
        appended as a duplicate top-level node.  Per-file status, failure reason
        and a ``.part`` recovery marker are derived from the download state — no
        disk ``stat`` happens on the UI thread (review #3 / #6).
        """
        data = self.active_downloads.get(rj_id, {})
        snapshot = data.get("snapshot")
        root = None
        if isinstance(snapshot, DownloadQueueItem) and snapshot.local_path:
            try:
                root = Path(snapshot.local_path).resolve()
            except OSError:
                root = Path(snapshot.local_path)

        seen: dict = {}
        rows: list = []
        db_rows = self._db_file_rows(rj_id)
        for db in db_rows:
            local = str(db.get("local_path") or "")
            rel = self._relative_path(local, root) or [str(db.get("track_title") or "")]
            key = self._unique_key(seen, "/".join(rel))
            rows.append({
                "key": key, "rel": rel,
                "dl_id": str(db.get("id") or ""),
                "track_id": None,
                "title": str(db.get("track_title") or rel[-1]),
                "status": str(db.get("status") or ""),
                "error": str(db.get("error") or ""),
                "downloaded": int(db.get("downloaded_bytes") or 0),
                "total": int(db.get("total_bytes") or 0),
                "has_part": self._implies_part(
                    str(db.get("status") or ""),
                    int(db.get("downloaded_bytes") or 0),
                    int(db.get("total_bytes") or 0)),
            })

        # Live in-memory progress overlays the DB rows for the active RJ.
        # Prefer the track_id-keyed cache; fall back to the title-keyed one
        # used by the base view (and tests).
        live_tracks = data.get("_live_tracks") or {}
        if not live_tracks:
            for title, info in data.get("tracks", {}).items():
                live_tracks[title] = {
                    "track_id": None, "title": title,
                    "downloaded": int(info.get("downloaded", 0) or 0),
                    "total": int(info.get("total", 0) or 0),
                    "status": str(info.get("status", "")),
                }

        self._detail_key_by_track[rj_id] = {}
        by_basename: dict = {}
        for i, row in enumerate(rows):
            by_basename.setdefault(row["title"], []).append(i)
        matched_rows: set = set()
        make_dl_id = getattr(getattr(self.app_controller, "orc", None),
                             "_make_dl_id", None)
        if make_dl_id is None:
            try:
                from core.orchestrator import Orchestrator
                make_dl_id = Orchestrator._make_dl_id
            except Exception:
                make_dl_id = None
        for track_id, live in live_tracks.items():
            title = str(live.get("title") or track_id)
            candidates = by_basename.get(title, [])
            match = None
            if len(candidates) == 1:
                match = candidates[0]
            elif make_dl_id is not None:
                # Duplicate basenames: correlate through the deterministic
                # download id (derived from track_id + local_path basename).
                for idx in candidates:
                    if idx in matched_rows:
                        continue
                    row = rows[idx]
                    try:
                        candidate = make_dl_id(
                            rj_id, track_id, Path(row["rel"][-1]), title)
                    except Exception:
                        candidate = None
                    if candidate and candidate == row["dl_id"]:
                        match = idx
                        break
            if match is None:
                # Safety net: never append a duplicate tree node — fold into an
                # unmatched existing row with the same basename.
                for idx in candidates:
                    if idx not in matched_rows:
                        match = idx
                        break
            if match is not None:
                idx = match
                matched_rows.add(idx)
                rows[idx].update(
                    status=str(live.get("status", rows[idx].get("status", ""))),
                    downloaded=int(live.get("downloaded", 0) or 0),
                    total=int(live.get("total", 0) or 0),
                    track_id=track_id,
                )
                if track_id:
                    self._detail_key_by_track[rj_id][track_id] = rows[idx]["key"]
            else:
                rel = [title]
                key = self._unique_key(seen, "/".join(rel))
                rows.append({
                    "key": key, "rel": rel, "dl_id": "", "track_id": track_id,
                    "title": title,
                    "status": str(live.get("status", "")),
                    "error": "",
                    "downloaded": int(live.get("downloaded", 0) or 0),
                    "total": int(live.get("total", 0) or 0),
                    "has_part": False,
                })
                if track_id:
                    self._detail_key_by_track[rj_id][track_id] = key
        return rows

    def _db_file_rows(self, rj_id: str) -> list:
        """One indexed SELECT for the selected RJ's download rows (no stats)."""
        try:
            cursor = self.download_service.connection.execute(
                "SELECT id, track_title, status, downloaded_bytes, total_bytes, "
                "COALESCE(local_path, '') AS local_path, "
                "COALESCE(error, '') AS error "
                "FROM downloads WHERE rj_id = ?", (rj_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    @staticmethod
    def _relative_path(local: str, root) -> list | None:
        if not root or not local:
            return None
        try:
            path = Path(local).resolve()
            return list(path.relative_to(root).parts)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _unique_key(seen: dict, rel: str) -> str:
        rel = rel or "unknown"
        count = seen.get(rel, 0)
        seen[rel] = count + 1
        return rel if count == 0 else f"{rel}#{count}"

    @staticmethod
    def _implies_part(status: str, downloaded: int, total: int) -> bool:
        """A resumable partial is stored in ``.part`` for these states."""
        return (str(status).lower() in {"downloading", "paused", "resuming",
                                        "queued", "failed"}
                and downloaded > 0 and (total <= 0 or downloaded < total))

    def _render_detail_panel(self, rj_id: str) -> None:
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        snapshot = data.get("snapshot")
        if isinstance(snapshot, DownloadQueueItem):
            human = snapshot.title if snapshot.title != rj_id else rj_id
            if snapshot.circle:
                human = f"{human}  ·  {snapshot.circle}"
            self.detail_title.value = human
            file_count = snapshot.file_count
            if snapshot.verified_known_bytes is not None:
                total = snapshot.verified_expected_bytes or 0
                downloaded = snapshot.verified_known_bytes
            else:
                verified = snapshot.verified_bytes
                downloaded = verified if verified is not None else snapshot.downloaded_bytes
                total = snapshot.total_bytes
        else:
            self.detail_title.value = rj_id
            total = downloaded = file_count = 0
        prog = self._get_progress_value(data)
        self.detail_summary.value = (
            f"{data.get('status', '')}  ·  {file_count} 个文件  ·  "
            f"{self._format_bytes(downloaded)} / {self._format_bytes(total)}")
        self.detail_progress.value = prog

        details = self._file_details(rj_id)
        page_size = max(1, int(self._detail_page_size))
        start = (self._detail_page - 1) * page_size
        page_files = details[start:start + page_size]
        self.detail_header_more.value = (
            f"{start + 1}–{start + len(page_files)} / {len(details)} 个文件"
            if details else "暂无文件")
        self.detail_prev_btn.disabled = self._detail_page <= 1
        self.detail_next_btn.disabled = start + page_size >= len(details)

        # Build display entries: folder headers + file rows (directory tree).
        entries: list[tuple] = []
        seen_folders: set = set()
        for offset, detail in enumerate(page_files):
            rel = detail["rel"]
            for depth in range(1, len(rel)):
                folder = "/".join(rel[:depth])
                if folder in seen_folders:
                    continue
                seen_folders.add(folder)
                entries.append(("folder", {
                    "key": f"folder:{folder}", "title": rel[depth - 1],
                    "depth": depth,
                }))
            entries.append(("file", detail))

        controls: list = []
        for kind, payload in entries:
            key = payload["key"]
            row = self._detail_rows.get(key)
            if row is None:
                row = self._make_detail_row(kind)
                self._detail_rows[key] = row
            if kind == "folder":
                self._update_folder_row(key, payload)
            else:
                self._update_detail_row(key, payload)
                # First match wins for the title→key fallback; duplicate titles
                # are resolved through _detail_key_by_track by track_id instead.
                self._detail_key_by_title.setdefault(payload["title"], key)
            controls.append(row)
        self.detail_scroll.controls[:] = controls

    def _make_detail_row(self, kind: str = "file"):
        if kind == "folder":
            return ft.Row([
                ft.Text("", size=10, color="grey"),
                ft.Text("", size=11, color=ACCENT_SECONDARY,
                        weight=ft.FontWeight.W_600, expand=True),
            ], spacing=6)
        return ft.Row([
            ft.Text("", size=10, color="grey"),
            ft.Text("", size=11, color=ACCENT_SECONDARY, max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS, expand=True),
            ft.Text("", size=10),
            ft.ProgressBar(value=0.0, bar_height=3, width=110,
                           color=ACCENT_PRIMARY),
            ft.Text("", size=10, color="grey"),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _update_folder_row(self, key: str, detail: dict) -> None:
        row = self._detail_rows.get(key)
        if row is None:
            return
        indent = "  " * max(0, int(detail.get("depth", 1)) - 1)
        row.controls[0].value = indent + "▸"
        row.controls[1].value = detail["title"]

    def _update_detail_row(self, key: str, detail: dict) -> None:
        row = self._detail_rows.get(key)
        if row is None:
            return
        depth = len(detail.get("rel", [detail["title"]]))
        row.controls[0].value = "  " * max(0, depth - 1)
        row.controls[1].value = detail["title"]
        status = detail.get("status", "")
        label = status
        if detail.get("has_part"):
            label += " · .part"
        error = str(detail.get("error") or "")
        if error:
            label += " · " + error[:28]
        row.controls[2].value = label
        if status in {"completed", "verified"}:
            row.controls[2].color = SUCCESS
        elif status in {"failed", "metadata_failed", "no_pending"}:
            row.controls[2].color = ERROR
        elif status in {"paused", "cancelled"}:
            row.controls[2].color = WARNING
        else:
            row.controls[2].color = ACCENT_SECONDARY
        total = int(detail.get("total", 0) or 0)
        downloaded = int(detail.get("downloaded", 0) or 0)
        prog = min(1.0, downloaded / total) if total > 0 else 0.0
        row.controls[3].value = prog
        row.controls[4].value = f"{prog * 100:.0f}%"

    def _detail_prev(self, _event=None):
        if self._detail_page > 1:
            self._detail_page -= 1
            if self._selected_rj:
                self._render_detail_panel(self._selected_rj)
                self._safe_update(self.detail_panel)

    def _detail_next(self, _event=None):
        if self._selected_rj:
            self._detail_page += 1
            self._render_detail_panel(self._selected_rj)
            self._safe_update(self.detail_panel)

    def _remove_queue_item(self, rj_id: str, *, save: bool = True):
        self._transient_rj_ids = [value for value in self._transient_rj_ids if value != rj_id]
        self.active_downloads.pop(rj_id, None)
        # The durable snapshot is stale until the next DB refresh.  Use the
        # remaining in-memory page for immediate button/summary correctness.
        self.queue_model = None
        self._render_queue_page()
        if save:
            self.save_queue()

    def update_work_status(self, rj_id: str, status: str):
        normalized = self.normalize_status(status)
        if normalized in {"queued", "downloading", "paused", "failed", "partial", "completed", "cancelled"}:
            self._transient_rj_ids = [
                value for value in self._transient_rj_ids if value != rj_id
            ]
        super().update_work_status(rj_id, status)
        if status == "Completed":
            self._remove_queue_item(rj_id)
            return
        if self._active:
            self._update_queue_summary()

    def update_track_progress(self, event):
        if not self._active:
            self.global_speed_bps = event.global_speed_bps
            return
        card_event = copy.copy(event)
        card_event.global_speed_bps = event.work_speed_bps
        super().update_track_progress(card_event)
        self.global_speed_bps = event.global_speed_bps
        # Maintain a track_id-keyed live cache so duplicate filenames in
        # different directories each update their own row (review #3).
        data = self.active_downloads.get(event.rj_id)
        if data is not None:
            live = data.setdefault("_live_tracks", {})
            live[event.track_id or event.track_title] = {
                "track_id": event.track_id,
                "title": event.track_title,
                "downloaded": event.downloaded_bytes,
                "total": event.total_bytes,
                "status": event.status,
            }
        self._update_queue_summary()
        if self._selected_rj == event.rj_id:
            self._live_update_detail_row(event)

    def _live_update_detail_row(self, event):
        """Resolve the live event to its stable row: track_id first, then the
        unique-title fallback.  Duplicate titles never overwrite each other."""
        row = None
        track_map = self._detail_key_by_track.get(event.rj_id)
        if track_map and event.track_id:
            key = track_map.get(event.track_id)
            if key:
                row = self._detail_rows.get(key)
        if row is None and event.track_title:
            key = self._detail_key_by_title.get(event.track_title)
            if key:
                row = self._detail_rows.get(key)
        if row is not None:
            total = max(0, int(event.total_bytes or 0))
            downloaded = max(0, int(event.downloaded_bytes or 0))
            prog = min(1.0, downloaded / total) if total > 0 else 0.0
            status = event.status
            row.controls[2].value = status
            row.controls[2].color = (
                SUCCESS if status in {"completed", "verified"}
                else ERROR if status in {"failed", "metadata_failed", "no_pending"}
                else WARNING if status in {"paused", "cancelled"}
                else ACCENT_SECONDARY)
            row.controls[3].value = prog
            row.controls[4].value = f"{prog * 100:.0f}%"
            self._safe_update(row)
        data = self.active_downloads.get(event.rj_id)
        if data:
            self.detail_progress.value = self._get_progress_value(data)
            self._safe_update(self.detail_progress)

    def _open_batch_paste_dialog(self, _event=None):
        """Open an in-app multiline batch input dialog.

        This deliberately does not invoke the operating-system file picker.
        Closing this dialog has no database, queue, filesystem or network side
        effects.
        """
        text_input = ft.TextField(
            label="批量粘贴 RJ",
            hint_text=(
                "每行一个或使用空格、逗号、分号分隔；支持 RJ01583845、"
                "1583845 和 https://asmr.one/work/RJ01583845"
            ),
            multiline=True,
            min_lines=8,
            max_lines=16,
            autofocus=True,
        )
        dialog = ft.AlertDialog(
            title=ft.Text("批量添加 RJ"),
            content=ft.Container(
                content=ft.Column(
                    [
                        text_input,
                        ft.Text(
                            "点击“预览”只进行分类检查；确认前不会写数据库、"
                            "创建目录或启动下载。",
                            size=12,
                            color="grey",
                        ),
                    ],
                    spacing=8,
                    tight=True,
                ),
                width=640,
            ),
            actions=[
                ft.TextButton(
                    "取消",
                    on_click=lambda _e: self._close_batch_paste_dialog(dialog),
                ),
                ft.TextButton(
                    "预览",
                    on_click=lambda _e: self._submit_batch_paste(dialog, text_input),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._batch_paste_input = text_input
        self._batch_paste_dialog = dialog
        self._open_dialog(dialog)
        return dialog

    def _open_dialog(self, dialog) -> None:
        """Show a dialog through Flet's supported page-level API."""
        page = self.app_controller.page
        opener = getattr(page, "open", None)
        if callable(opener):
            opener(dialog)
            return
        page.dialog = dialog
        dialog.open = True
        page.update()

    def _close_dialog(self, dialog) -> None:
        """Close a dialog through the matching Flet API."""
        page = self.app_controller.page
        closer = getattr(page, "close", None)
        if callable(closer):
            closer(dialog)
            return
        dialog.open = False
        page.update()

    def _close_batch_paste_dialog(self, dialog) -> None:
        self._close_dialog(dialog)
        if self._batch_paste_dialog is dialog:
            self._batch_paste_dialog = None
            self._batch_paste_input = None

    def _submit_batch_paste(self, dialog, text_input) -> None:
        text = str(getattr(text_input, "value", "") or "")
        self._close_batch_paste_dialog(dialog)
        if not text.strip():
            self.app_controller.show_snack("请先粘贴一个或多个 RJ 号")
            return
        self.process_input(text)

    @staticmethod
    def _preview_group(label: str, values, limit: int = 12) -> str:
        values = list(values)
        if not values:
            return f"{label}：0"
        shown = "、".join(values[:limit])
        suffix = f"，另有 {len(values) - limit} 项" if len(values) > limit else ""
        return f"{label}：{len(values)}\n{shown}{suffix}"

    def process_input(self, text: str):
        # ``active_downloads`` is a rendered-page cache.  It also contains
        # failed and review cards, so it must not determine preview priority.
        # Only the orchestrator's live runtime sets are "当前活动"; persisted
        # rows are classified by DownloadService as queue/history/review.
        active_ids: set[str] = set()
        orchestrator = getattr(self.app_controller, "orc", None)
        if orchestrator is not None:
            active_ids.update(getattr(orchestrator, "active_tasks", {}).keys())
            active_ids.update(getattr(orchestrator, "queued_rj_ids", set()))
            active_ids.update(getattr(orchestrator, "preparing_rj_ids", set()))
            active_ids.update(getattr(orchestrator, "resuming_rj_ids", set()))
        try:
            preview = self.download_service.preview_enqueue(
                text,
                active_rj_ids=active_ids,
            )
        except Exception as exc:
            logging.error("batch RJ preview failed", exc_info=True)
            self.app_controller.show_snack(f"RJ 预览失败: {exc}")
            return
        if preview.submitted_count == 0:
            self.app_controller.show_snack("没有识别到 RJ 号")
            return
        if len(preview.ready) == 1 and not preview.requires_confirmation:
            self._enqueue_preview(preview)
            return
        self._show_batch_preview(preview)

    def _show_batch_preview(self, preview: BatchEnqueuePreview):
        sections = [
            self._preview_group("可添加", preview.ready),
            self._preview_group("格式无效", preview.invalid_tokens),
            self._preview_group("输入内重复", preview.duplicate_input),
            self._preview_group("当前活动", preview.already_active),
            self._preview_group("下载队列已存在", preview.already_in_queue),
            self._preview_group("资源库已存在", preview.already_in_library),
            self._preview_group("历史已完成", preview.already_completed),
            self._preview_group("需要复核", preview.needs_review),
        ]
        reasons = preview.reasons or {}
        cancelled = tuple(
            rj_id for rj_id in preview.needs_review
            if str(reasons.get(rj_id, "")).startswith("已取消任务")
        )
        dialog = ft.AlertDialog(
            title=ft.Text("批量 RJ 预览"),
            content=ft.Container(
                content=ft.Text("\n\n".join(sections), selectable=True),
                width=620,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda _e: self._close_preview(dialog)),
                *(
                    [ft.TextButton(
                        f"继续 {len(cancelled)} 个已取消任务",
                        on_click=lambda _e: self._resume_cancelled_preview(dialog, cancelled),
                    )] if cancelled else []
                ),
                *(
                    [ft.TextButton(
                        f"添加 {len(preview.ready)} 项",
                        on_click=lambda _e: self._confirm_preview(dialog, preview),
                    )] if preview.ready else []
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._open_dialog(dialog)

    def _resume_cancelled_preview(self, dialog, rj_ids) -> None:
        self._close_preview(dialog)
        for rj_id in rj_ids:
            if rj_id not in self._transient_rj_ids:
                self._transient_rj_ids.append(rj_id)
            self.active_downloads[rj_id] = {
                "status": "恢复中...", "tracks": {}, "control": None,
                "last_time": time.time(), "last_bytes": 0, "cache_hit": False,
            }
            self.app_controller.resume_cancelled_download(rj_id)
        self._render_queue_page()

    def _close_preview(self, dialog):
        self._close_dialog(dialog)

    def _confirm_preview(self, dialog, preview: BatchEnqueuePreview):
        self._close_preview(dialog)
        self._enqueue_preview(preview)

    def _enqueue_preview(self, preview: BatchEnqueuePreview):
        if not preview.ready:
            self.app_controller.show_snack("没有可添加的任务")
            return
        self.queue_filter = "working"
        self.queue_page = 1
        if hasattr(self, "queue_filter_dropdown"):
            self.queue_filter_dropdown.value = "working"
        for rj_id in preview.ready:
            if rj_id not in self._transient_rj_ids:
                self._transient_rj_ids.append(rj_id)
            self.active_downloads[rj_id] = {
                "status": "准备中...",
                "tracks": {},
                "control": None,
                "last_time": time.time(),
                "last_bytes": 0,
                "cache_hit": False,
            }
            self.app_controller.start_download(rj_id)
        self._render_queue_page()
        self.save_queue()
        self.app_controller.show_snack(f"已提交 {len(preview.ready)} 个任务")

    def on_file_selected(self, event):
        if not event.files:
            return
        try:
            with open(event.files[0].path, "r", encoding="utf-8") as handle:
                self.process_input(handle.read())
        except Exception as exc:
            self.app_controller.show_snack(f"读取文件失败: {exc}")

    def toggle_pause(self, rj_id: str):
        super().toggle_pause(rj_id)
        self._update_queue_summary()

    def _retry_failed(self, rj_id: str):
        super()._retry_failed(rj_id)
        self._update_queue_summary()

    def _force_download(self, rj_id: str):
        super()._force_download(rj_id)
        self._update_queue_summary()

    def _retry_prepare(self, rj_id: str):
        super()._retry_prepare(rj_id)
        self._update_queue_summary()

    def cancel_item(self, rj_id: str):
        # Base semantics now persist a true cancelled state.
        super().cancel_item(rj_id)
        self._transient_rj_ids = [value for value in self._transient_rj_ids if value != rj_id]
        self._update_queue_summary()
