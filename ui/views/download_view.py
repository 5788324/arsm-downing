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
from ui.theme import ACCENT_PRIMARY
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
        self.reload_queue_from_database(reset_speed=False)

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
        """Initial synchronous snapshot; called by the base constructor."""
        self._sync_queue_file()
        try:
            model = self.download_service.fetch_queue_page(
                status_filter=self.queue_filter,
                page=self.queue_page,
                page_size=self.queue_page_size,
            )
            self._apply_queue_page(model)
        except Exception as exc:
            logging.error("queue snapshot load failed: %s", exc, exc_info=True)

    def reload_queue_from_database(self, *, reset_speed: bool = False):
        if reset_speed:
            self.global_speed_bps = 0.0
        self.refresh_queue_async(force=True)

    def refresh_queue_async(self, *, reset_page: bool = False, force: bool = False):
        if reset_page:
            self.queue_page = 1
        if (not self._active and not force) or self._queue_refreshing:
            return
        self._queue_refreshing = True
        if hasattr(self, "queue_refresh_btn"):
            self.queue_refresh_btn.disabled = True

        status_filter = self.queue_filter
        page = self.queue_page
        page_size = self.queue_page_size

        def query():
            return self.download_service.fetch_queue_page(
                status_filter=status_filter,
                page=page,
                page_size=page_size,
            )

        def render(result):
            self._queue_refreshing = False
            if hasattr(self, "queue_refresh_btn"):
                self.queue_refresh_btn.disabled = False
            self._apply_queue_page(result)
            self._safe_update(getattr(self, "queue_refresh_btn", None))


        try:
            render(query())
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
        self.queue_list.controls.clear()
        for rj_id in self.active_downloads:
            self.build_queue_item(rj_id, update_list=False)
        if not self.active_downloads:
            self.queue_list.controls.append(
                ft.Container(
                    content=ft.Text("当前筛选没有任务", color="grey"),
                    alignment=ft.alignment.center,
                    padding=30,
                )
            )
        self._update_queue_summary()
        self._update_pagination()
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
            counts = {"active": 0, "queued": 0, "paused": 0, "failed": 0}
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
            f"  完成 {completed}"
            f"  总速度 {self._format_speed(self.global_speed_bps)}"
        )
        self.btn_pause_all.disabled = counts["active"] + counts["queued"] == 0
        self.btn_resume_all.disabled = counts["paused"] + counts["failed"] == 0
        for control in (self.queue_summary, self.btn_pause_all, self.btn_resume_all):
            self._safe_update(control)

    def _get_progress_value(self, item_data: Dict[str, Any]) -> float:
        tracks = item_data.get("tracks", {})
        total = sum(value.get("total", 0) for value in tracks.values())
        if total > 0:
            downloaded = sum(value.get("downloaded", 0) for value in tracks.values())
            return max(0.0, min(1.0, downloaded / total))
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
        snapshot = self.active_downloads.get(rj_id, {}).get("snapshot")
        if isinstance(snapshot, DownloadQueueItem) and snapshot.cover_url:
            work_dir = Path(snapshot.local_path) if snapshot.local_path else None
            if work_dir and work_dir.exists():
                source = super()._resolve_cover_source(rj_id)
                if source:
                    return source
            return snapshot.cover_url
        return super()._resolve_cover_source(rj_id)

    def build_queue_item(self, rj_id: str, update_list: bool = True):
        super().build_queue_item(rj_id, update_list=update_list)
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        snapshot = data.get("snapshot")
        if isinstance(snapshot, DownloadQueueItem) and data.get("title_text"):
            title = snapshot.title or rj_id
            if snapshot.circle:
                title = f"{title}  ·  {snapshot.circle}"
            data["title_text"].value = title
        speed = data.get("last_speed_bps", 0)
        speed_text = data.get("speed_text")
        if speed_text is not None:
            value = self._format_speed(speed) if speed > 0 else ""
            eta = data.get("last_eta")
            if value and eta:
                value += f"  ETA {eta:.0f}s"
            speed_text.value = value

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
        if normalized in {"queued", "downloading", "paused", "failed", "partial", "completed"}:
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
        self._update_queue_summary()

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
                        f"添加 {len(preview.ready)} 项",
                        on_click=lambda _e: self._confirm_preview(dialog, preview),
                    )]
                    if preview.ready else []
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._open_dialog(dialog)

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
        # Base semantics pause and preserve .part; this layer only changes visibility.
        super().cancel_item(rj_id)
        self._transient_rj_ids = [value for value in self._transient_rj_ids if value != rj_id]
        self._update_queue_summary()
