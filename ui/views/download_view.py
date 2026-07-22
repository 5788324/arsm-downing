import flet as ft
import logging
import os
import platform
import subprocess
import json
import time
from typing import Dict, Any, Optional
from pathlib import Path

from ui.theme import Styles, ACCENT_PRIMARY, ACCENT_SECONDARY, SUCCESS, WARNING, ERROR, BG_SURFACE_LIGHT
from core.status import WorkStatus
from core.orchestrator import Orchestrator
from core.download_queue import (
    BatchRjPreview,
    DownloadQueuePage,
    DownloadQueueQueryService,
    DownloadTaskSnapshot,
)
from core.paths import app_path

QUEUE_FILE = app_path("queue.json")


class DownloadView(ft.Container):
    COVER_CANDIDATES = (
        "cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
        "main.jpg", "main.png", "package.jpg", "package.png",
    )

    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True
        self.padding = 10

        self.queue_query = DownloadQueueQueryService(self.app_controller.db)
        self.queue_filter = "working"
        self.queue_page = 1
        self.queue_page_size = 24
        self.queue_model: Optional[DownloadQueuePage] = None
        self._visible_rj_ids: set[str] = set()
        self._transient_rj_ids: list[str] = []
        self._queue_refreshing = False
        self.active_downloads: Dict[str, Dict[str, Any]] = {}

        self.rj_input = ft.TextField(
            label="输入 RJ 号（例如 RJ01603020）",
            hint_text="粘贴一个或多个 RJ 号；支持空格、换行、逗号和分号",
            border_color=ACCENT_PRIMARY,
            focused_border_color=SUCCESS,
            border_radius=10,
            expand=True,
            on_submit=self.on_download_submit,
        )
        self.download_btn = ft.ElevatedButton(
            "预览并添加",
            icon=ft.Icons.DOWNLOAD,
            style=ft.ButtonStyle(
                bgcolor=ACCENT_PRIMARY,
                color="white",
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.all(20),
            ),
            on_click=self.on_download_submit,
        )
        self.file_picker = ft.FilePicker(on_result=self.on_file_selected)
        self.batch_btn = ft.ElevatedButton(
            "批量导入文件",
            icon=ft.Icons.FOLDER_OPEN,
            style=ft.ButtonStyle(
                bgcolor=BG_SURFACE_LIGHT,
                color="white",
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.all(20),
            ),
            on_click=lambda _: self.file_picker.pick_files(
                allowed_extensions=["txt"]
            ),
        )
        self.btn_pause_all = ft.ElevatedButton(
            "全部暂停",
            icon=ft.Icons.PAUSE_CIRCLE,
            style=ft.ButtonStyle(
                bgcolor=WARNING,
                color="white",
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            on_click=lambda _e: self._batch_pause(),
        )
        self.btn_resume_all = ft.ElevatedButton(
            "全部开始",
            icon=ft.Icons.PLAY_CIRCLE,
            style=ft.ButtonStyle(
                bgcolor=SUCCESS,
                color="white",
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            on_click=lambda _e: self._batch_resume(),
        )

        self.queue_filter_dropdown = ft.Dropdown(
            width=150,
            value="working",
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
        self.queue_summary = ft.Text("", size=12, color="grey")
        self.queue_page_label = ft.Text("第 1 / 1 页", size=12, color="grey")
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
        self.queue_refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH,
            tooltip="刷新队列",
            on_click=lambda _e: self.refresh_queue_async(),
        )
        self.queue_list = ft.ListView(
            expand=True,
            spacing=8,
            auto_scroll=False,
        )

        controls_row = ft.Row(
            [
                self.btn_pause_all,
                self.btn_resume_all,
                ft.Container(expand=True),
                ft.Text("筛选", size=12, color="grey"),
                self.queue_filter_dropdown,
                self.queue_refresh_btn,
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        pagination_row = ft.Row(
            [
                self.queue_prev_btn,
                self.queue_page_label,
                self.queue_next_btn,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=4,
        )

        self.content = ft.Column(
            [
                self.file_picker,
                ft.Text("下载中心", size=32, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [self.rj_input, self.download_btn, self.batch_btn],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                controls_row,
                ft.Divider(height=6, color="transparent"),
                ft.Row(
                    [
                        ft.Text(
                            "下载队列",
                            size=18,
                            weight=ft.FontWeight.W_500,
                            color=ACCENT_PRIMARY,
                        ),
                        ft.Container(expand=True),
                        self.queue_summary,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.queue_list,
                pagination_row,
            ],
            expand=True,
            spacing=6,
        )

        self.load_queue()

    def save_queue(self):
        try:
            dump_data = {}
            for rj, data in self.active_downloads.items():
                dump_data[rj] = {
                    "status": data["status"],
                    "tracks": data.get("tracks", {})
                }
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(dump_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_queue(self):
        """Load one paged SQLite read model without per-card DB queries."""
        try:
            model = self.queue_query.fetch_page(
                status_filter=self.queue_filter,
                page=self.queue_page,
                page_size=self.queue_page_size,
            )
            self._apply_queue_page(model)
        except Exception as exc:
            logging.error("load_queue failed: %s", exc, exc_info=True)
            self.app_controller.show_snack(f"队列读取失败: {exc}")

    def refresh_queue_async(self, *, reset_page: bool = False):
        if reset_page:
            self.queue_page = 1
        if self._queue_refreshing:
            return
        self._queue_refreshing = True
        self.queue_refresh_btn.disabled = True
        try:
            if self.queue_refresh_btn.page:
                self.queue_refresh_btn.update()
        except Exception:
            pass

        status_filter = self.queue_filter
        page = self.queue_page
        page_size = self.queue_page_size

        def _query():
            try:
                return (
                    True,
                    self.queue_query.fetch_page(
                        status_filter=status_filter,
                        page=page,
                        page_size=page_size,
                    ),
                )
            except Exception as exc:
                logging.error(
                    "refresh_queue_async failed: %s", exc, exc_info=True
                )
                return False, exc

        def _render(result):
            self._queue_refreshing = False
            self.queue_refresh_btn.disabled = False
            ok, payload = result
            if ok:
                self._apply_queue_page(payload)
            else:
                self.app_controller.show_snack(f"队列读取失败: {payload}")
            try:
                if self.queue_refresh_btn.page:
                    self.queue_refresh_btn.update()
            except Exception:
                pass

        self.app_controller.run_blocking(
            _query,
            _render,
            action_label="刷新下载队列",
        )

    def _apply_queue_page(self, model: DownloadQueuePage):
        self.queue_model = model
        self.queue_page = model.page
        model_ids = {item.rj_id for item in model.items}
        self._transient_rj_ids = [
            rj_id for rj_id in self._transient_rj_ids
            if rj_id not in model_ids
        ]

        visible_ids = [item.rj_id for item in model.items]
        if self.queue_filter == "working" and model.page == 1:
            remaining = max(0, model.page_size - len(visible_ids))
            visible_ids.extend(self._transient_rj_ids[:remaining])
        self._visible_rj_ids = set(visible_ids)
        for rj_id, data in self.active_downloads.items():
            if rj_id not in self._visible_rj_ids:
                for key in (
                    "control", "title_text", "status_text",
                    "speed_text", "prog_bar",
                ):
                    data.pop(key, None)

        snapshots = {item.rj_id: item for item in model.items}
        for rj_id in visible_ids:
            data = self.active_downloads.setdefault(
                rj_id,
                {
                    "status": "队列中",
                    "tracks": {},
                    "control": None,
                    "last_time": time.time(),
                    "last_bytes": 0,
                    "cache_hit": False,
                },
            )
            snapshot = snapshots.get(rj_id)
            if snapshot is not None:
                data["snapshot"] = snapshot
                data["status"] = snapshot.ui_status
                data["_derived_enum"] = {
                    "active": WorkStatus.DOWNLOADING,
                    "queued": WorkStatus.QUEUED,
                    "paused": WorkStatus.PAUSED,
                    "failed": WorkStatus.FAILED,
                    "completed": WorkStatus.COMPLETED,
                }.get(snapshot.queue_state, WorkStatus.normalize(snapshot.work_status))

        self._render_visible_queue()

    def _render_visible_queue(self):
        self.queue_list.controls.clear()
        ordered_ids = []
        if self.queue_model is not None:
            ordered_ids.extend(
                item.rj_id for item in self.queue_model.items
                if item.rj_id in self._visible_rj_ids
            )
        ordered_ids.extend(
            rj_id for rj_id in self._transient_rj_ids
            if rj_id in self._visible_rj_ids and rj_id not in ordered_ids
        )
        for rj_id in ordered_ids:
            if rj_id in self.active_downloads:
                self.build_queue_item(rj_id, update_list=False)
        if not ordered_ids:
            self.queue_list.controls.append(
                ft.Container(
                    content=ft.Text(
                        "当前筛选没有任务",
                        color="grey",
                        text_align=ft.TextAlign.CENTER,
                    ),
                    alignment=ft.alignment.center,
                    padding=30,
                )
            )
        self._update_queue_summary()
        self._update_pagination_controls()
        try:
            if self.queue_list.page:
                self.queue_list.update()
        except Exception:
            pass

    def _on_filter_change(self, event):
        value = getattr(event.control, "value", None) or "working"
        self.queue_filter = value
        self.refresh_queue_async(reset_page=True)

    def _previous_page(self, _event):
        if self.queue_page <= 1:
            return
        self.queue_page -= 1
        self.refresh_queue_async()

    def _next_page(self, _event):
        page_count = self.queue_model.page_count if self.queue_model else 1
        if self.queue_page >= page_count:
            return
        self.queue_page += 1
        self.refresh_queue_async()

    def _update_pagination_controls(self):
        page_count = self.queue_model.page_count if self.queue_model else 1
        self.queue_page_label.value = f"第 {self.queue_page} / {page_count} 页"
        self.queue_prev_btn.disabled = self.queue_page <= 1
        self.queue_next_btn.disabled = self.queue_page >= page_count
        for control in (
            self.queue_page_label,
            self.queue_prev_btn,
            self.queue_next_btn,
        ):
            try:
                if control.page:
                    control.update()
            except Exception:
                pass

    def _batch_pause(self):
        self.app_controller.pause_all_downloads()

    def _batch_resume(self):
        self.app_controller.resume_all_downloads()

    def process_input(self, text: str):
        """Preview pasted IDs before any queue or filesystem side effect."""
        active_ids = set(self.active_downloads)
        try:
            active_ids.update(self.app_controller.db.get_pending_rj_ids())
        except Exception:
            pass
        orchestrator = getattr(self.app_controller, "orc", None)
        if orchestrator is not None:
            active_ids.update(getattr(orchestrator, "active_tasks", {}).keys())
            active_ids.update(getattr(orchestrator, "queued_rj_ids", set()))

        try:
            preview = self.queue_query.preview_input(
                text,
                active_rj_ids=active_ids,
            )
        except Exception as exc:
            logging.error("RJ preview failed: %s", exc, exc_info=True)
            self.app_controller.show_snack(f"RJ 预览失败: {exc}")
            return

        if not preview.ready and not preview.requires_confirmation:
            self.app_controller.show_snack("没有识别到有效 RJ 号")
            return
        if not preview.requires_confirmation and len(preview.ready) == 1:
            self._enqueue_preview(preview)
            return
        self._show_batch_preview(preview)

    @staticmethod
    def _preview_group(label: str, values, limit: int = 12) -> str:
        values = list(values)
        if not values:
            return f"{label}：0"
        shown = "、".join(values[:limit])
        suffix = f"，另有 {len(values) - limit} 项" if len(values) > limit else ""
        return f"{label}：{len(values)}\n{shown}{suffix}"

    def _show_batch_preview(self, preview: BatchRjPreview):
        content = "\n\n".join(
            [
                self._preview_group("可添加", preview.ready),
                self._preview_group("输入内重复", preview.duplicate_input),
                self._preview_group("格式无效", preview.invalid_tokens),
                self._preview_group("已在活动队列", preview.already_active),
                self._preview_group("资源库或历史中已存在", preview.already_known),
            ]
        )
        actions = [
            ft.TextButton("取消", on_click=lambda _e: self._close_batch_preview()),
        ]
        if preview.ready:
            actions.append(
                ft.TextButton(
                    f"添加 {len(preview.ready)} 项",
                    on_click=lambda _e, p=preview: self._confirm_batch_preview(p),
                )
            )
        page = self.app_controller.page
        page.dialog = ft.AlertDialog(
            title=ft.Text("批量 RJ 预览"),
            content=ft.Container(
                content=ft.Text(content, selectable=True),
                width=620,
            ),
            actions=actions,
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog.open = True
        page.update()

    def _close_batch_preview(self):
        page = self.app_controller.page
        if page.dialog:
            page.dialog.open = False
            page.update()

    def _confirm_batch_preview(self, preview: BatchRjPreview):
        self._close_batch_preview()
        self._enqueue_preview(preview)

    def _enqueue_preview(self, preview: BatchRjPreview):
        rj_ids = list(preview.ready)
        if not rj_ids:
            self.app_controller.show_snack("没有可添加的任务")
            return

        self.queue_filter = "working"
        self.queue_page = 1
        self.queue_filter_dropdown.value = "working"
        self._transient_rj_ids = list(dict.fromkeys(
            [*rj_ids, *self._transient_rj_ids]
        ))
        for rj_id in rj_ids:
            self.active_downloads[rj_id] = {
                "status": "准备中...",
                "tracks": {},
                "control": None,
                "last_time": time.time(),
                "last_bytes": 0,
                "cache_hit": False,
            }
            self.app_controller.start_download(rj_id)

        base_ids = []
        if self.queue_model is not None:
            base_ids = [item.rj_id for item in self.queue_model.items]
        remaining = max(0, self.queue_page_size - len(base_ids))
        self._visible_rj_ids = set(
            [*base_ids, *self._transient_rj_ids[:remaining]]
        )
        self._render_visible_queue()
        self.save_queue()
        try:
            if self.queue_filter_dropdown.page:
                self.queue_filter_dropdown.update()
        except Exception:
            pass
        self.app_controller.show_snack(f"已提交 {len(rj_ids)} 个任务")

    def on_download_submit(self, e):
        val = self.rj_input.value.strip()
        if not val:
            return
        self.rj_input.value = ""
        self.rj_input.update()
        self.process_input(val)

    def on_file_selected(self, e):
        if not e.files:
            return
        file_path = e.files[0].path
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.process_input(content)
        except Exception as err:
            self.app_controller.show_snack(f"读取文件失败: {err}")

    # ══════════════════════════════════════════════
    #  Queue item builder (P3: filtered display)
    # ══════════════════════════════════════════════
    @staticmethod
    def _is_terminal(status):
        """Check if status is terminal (hidden when show_completed=False).

        Must stay aligned with WorkStatus.is_terminal:
        completed, registered, verified, external.
        """
        ns = WorkStatus.normalize(status)
        return ns.is_terminal

    @staticmethod
    def _is_failed(status):
        return status in ("failed", "Failed", "下载失败") or \
               status.startswith("Failed")

    @staticmethod
    def normalize_status(status: str) -> str:
        """Normalize via WorkStatus enum (single source of truth)."""
        return WorkStatus.normalize(status).value

    # ══════════════════════════════════════════════
    #  RC7.4-bis: Unified card state derivation from DB
    # ══════════════════════════════════════════════
    def derive_download_card_state(self, rj_id: str) -> dict:
        """Derive card visibility + status from works + downloads tables.

        Returns dict with keys:
          - visible: bool — should this RJ appear in download queue?
          - status: str — card status label (Chinese)
          - enum: WorkStatus — derived WorkStatus enum value
          - works_status: str — raw works.status
          - dl_summary: dict — {status: count} from downloads table
        """
        db = self.app_controller.db
        works_status = db.get_works_status(rj_id)
        dl_summary = db.get_downloads_summary(rj_id)

        # ── Rule: count pending downloads ──
        has_queued = dl_summary.get("queued", 0) > 0
        has_downloading = dl_summary.get("downloading", 0) > 0
        has_paused = dl_summary.get("paused", 0) > 0
        has_failed = dl_summary.get("failed", 0) > 0
        has_pending = has_queued or has_downloading or has_paused or has_failed

        ws_enum = WorkStatus.normalize(works_status) if works_status else None

        # Terminal works may carry historical failed/paused rows.
        # They should not keep reappearing in the active queue.
        if ws_enum and ws_enum.is_terminal and not has_queued and not has_downloading:
            result = {
                "visible": False,
                "status": ws_enum.ui_label,
                "enum": ws_enum,
                "works_status": works_status,
                "dl_summary": dl_summary,
            }
            return result

        result = {
            "visible": False,
            "status": "",
            "enum": WorkStatus.QUEUED,
            "works_status": works_status,
            "dl_summary": dl_summary,
        }

        # ── Rule 1: terminal works with NO pending → HIDE ──
        if works_status:
            ws_enum = WorkStatus.normalize(works_status)
            if ws_enum.is_terminal and not has_pending:
                # completed / verified / external / registered / indexed
                # with no pending downloads → not in download queue
                result["visible"] = False
                result["enum"] = ws_enum
                result["status"] = ws_enum.ui_label
                return result

        # ── Rules 2-5: priority order for card display ──
        if has_downloading:
            result["visible"] = True
            result["enum"] = WorkStatus.DOWNLOADING
            result["status"] = "下载中"
            return result

        if has_queued:
            result["visible"] = True
            result["enum"] = WorkStatus.QUEUED
            result["status"] = "队列中"
            return result

        if has_paused:
            result["visible"] = True
            result["enum"] = WorkStatus.PAUSED
            result["status"] = "已暂停"
            return result

        if has_failed:
            result["visible"] = True
            result["enum"] = WorkStatus.FAILED
            result["status"] = "下载失败"
            return result

        # ── Rule 6: no pending downloads ──
        if works_status:
            ws_enum = WorkStatus.normalize(works_status)
            if ws_enum.is_terminal:
                # terminal work, no pending — hide
                result["visible"] = False
                result["enum"] = ws_enum
                result["status"] = ws_enum.ui_label
                return result
            if ws_enum in (WorkStatus.PREPARED, WorkStatus.PARTIAL,
                           WorkStatus.PREPARING):
                # prepared/partial with no pending → no_pending (show with retry)
                result["visible"] = True
                result["enum"] = WorkStatus.NO_PENDING
                result["status"] = "无可恢复文件"
                return result

        # Fallback: not visible
        result["visible"] = False
        return result

    def _refresh_queue(self):
        """Compatibility wrapper for tests and legacy callers."""
        self.load_queue()

    def _queue_sort_key(self, rj_id: str):
        data = self.active_downloads.get(rj_id, {})
        ns = self.normalize_status(data.get("status", ""))
        priority = {
            "downloading": 0,
            "resuming": 1,
            "queued": 2,
            "paused": 3,
            "failed": 4,
            "metadata_failed": 5,
            "no_pending": 6,
            "duplicate": 7,
            "completed": 8,
        }.get(ns, 9)
        progress = self._get_progress_value(data)
        current_track = 0 if data.get("current_track") else 1
        return (priority, current_track, -progress, rj_id)

    def _update_queue_summary(self):
        model = self.queue_model
        transient_count = len(self._transient_rj_ids)
        if model is None:
            self.queue_summary.value = f"显示 {len(self._visible_rj_ids)} 项"
        else:
            summary = model.summary
            visible_total = model.total_items + transient_count
            all_total = summary.total_tasks + transient_count
            self.queue_summary.value = (
                f"当前筛选 {visible_total} / 全部 {all_total}"
                f"  下载中 {summary.active_tasks}"
                f"  排队 {summary.queued_tasks + transient_count}"
                f"  暂停 {summary.paused_tasks}"
                f"  失败 {summary.failed_tasks}"
                f"  完成 {summary.completed_tasks}"
            )
        try:
            if self.queue_summary.page:
                self.queue_summary.update()
        except Exception:
            pass

    def _get_progress_value(self, item_data: Dict[str, Any]) -> float:
        tracks = item_data.get("tracks", {})
        total = sum(t.get("total", 0) for t in tracks.values())
        downloaded = sum(t.get("downloaded", 0) for t in tracks.values())
        if total > 0:
            return max(0.0, min(1.0, downloaded / total))
        snapshot = item_data.get("snapshot")
        if isinstance(snapshot, DownloadTaskSnapshot):
            return snapshot.percent / 100.0
        return 0.0

    def _find_work_dir(self, rj_id: str) -> Optional[Path]:
        data = self.active_downloads.get(rj_id, {})
        snapshot = data.get("snapshot")
        if isinstance(snapshot, DownloadTaskSnapshot) and snapshot.local_path:
            return Path(snapshot.local_path)
        try:
            work = self.app_controller.db.get_work(rj_id)
            if work and work["local_path"]:
                return Path(work["local_path"])
        except Exception:
            pass
        return None

    def _resolve_cover_source(
        self,
        rj_id: str,
        item_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        data = item_data or self.active_downloads.get(rj_id, {})
        snapshot = data.get("snapshot")
        work_dir = None
        if isinstance(snapshot, DownloadTaskSnapshot) and snapshot.local_path:
            work_dir = Path(snapshot.local_path)
        else:
            work_dir = self._find_work_dir(rj_id)

        if work_dir and work_dir.exists():
            for name in self.COVER_CANDIDATES:
                candidate = work_dir / name
                if candidate.exists():
                    return str(candidate)
            try:
                for child in work_dir.iterdir():
                    if child.is_file() and child.suffix.lower() in {
                        ".jpg", ".jpeg", ".png", ".webp"
                    }:
                        lower_name = child.name.lower()
                        if any(key in lower_name for key in (
                            "cover", "package", "main"
                        )):
                            return str(child)
            except Exception:
                pass

        if isinstance(snapshot, DownloadTaskSnapshot) and snapshot.cover_url:
            return snapshot.cover_url
        try:
            cached = self.app_controller.db.get_metadata_cache(
                rj_id,
                allow_stale=True,
            )
            if cached and cached.get("cover_url"):
                return cached["cover_url"]
        except Exception:
            pass
        return None

    def _build_cover(
        self,
        rj_id: str,
        *,
        item_data: Optional[Dict[str, Any]] = None,
        width: int = 72,
        height: int = 72,
    ):
        src = self._resolve_cover_source(rj_id, item_data=item_data)
        if src:
            return ft.Container(
                width=width,
                height=height,
                border_radius=12,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                bgcolor=BG_SURFACE_LIGHT,
                content=ft.Image(
                    src=src,
                    width=width,
                    height=height,
                    fit=ft.ImageFit.COVER,
                ),
            )

        return ft.Container(
            width=width,
            height=height,
            border_radius=12,
            bgcolor=ft.Colors.with_opacity(0.55, BG_SURFACE_LIGHT),
            alignment=ft.alignment.center,
            content=ft.Icon(
                ft.Icons.ALBUM,
                color=ACCENT_PRIMARY,
                size=min(width, height) // 2,
            ),
        )

    def build_queue_item(self, rj_id: str, update_list: bool = True):
        item_data = self.active_downloads[rj_id]
        status = item_data["status"]
        ns = self.normalize_status(status)
        snapshot = item_data.get("snapshot")

        display_title = rj_id
        circle = ""
        if isinstance(snapshot, DownloadTaskSnapshot):
            display_title = snapshot.title or rj_id
            circle = snapshot.circle or ""
        title_text = ft.Text(
            display_title,
            weight=ft.FontWeight.BOLD,
            size=18,
            selectable=True,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        identity_parts = [rj_id]
        if circle:
            identity_parts.append(circle)
        identity_text = ft.Text(
            " · ".join(identity_parts),
            size=11,
            color="grey",
            selectable=True,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        cur_track = item_data.get("current_track", "")
        cur_title = ft.Text(
            cur_track,
            size=11,
            color=ACCENT_SECONDARY,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        ) if cur_track else ft.Text("")

        cache_label = " [缓存]" if item_data.get("cache_hit") else ""
        status_colors = {"downloading": SUCCESS, "queued": ACCENT_SECONDARY, "paused": WARNING,
                         "failed": ERROR, "completed": SUCCESS, "metadata_failed": ERROR,
                         "no_pending": WARNING, "duplicate": "grey"}
        status_color = status_colors.get(ns, ACCENT_PRIMARY)
        status_text = ft.Text(status + cache_label, color=status_color, size=12, weight=ft.FontWeight.W_600)

        speed_info = item_data.get("last_speed_bps", 0)
        speed_str = ""
        if speed_info > 0:
            speed_str = f"{speed_info/1024/1024:.1f} MB/s"
            eta_info = item_data.get("last_eta", None)
            if eta_info:
                speed_str += f"  ETA {eta_info:.0f}s"
        speed_text = ft.Text(speed_str, color=ACCENT_SECONDARY, size=11)

        prog = self._get_progress_value(item_data)
        total = sum(t.get("total", 0) for t in item_data.get("tracks", {}).values())
        if total <= 0 and isinstance(snapshot, DownloadTaskSnapshot):
            total = snapshot.total_bytes
        if self._is_terminal(status):
            prog = 1.0
        elif ns in ("queued", "resuming") and total <= 0:
            prog = 0.0
        prog_bar = ft.ProgressBar(
            value=prog,
            color=SUCCESS if (prog or 0) >= 1.0 else ACCENT_PRIMARY)

        actions = []
        if ns in ("metadata_failed", "no_pending", "prepared"):
            btn_retry = ft.IconButton(
                icon=ft.Icons.REFRESH, icon_color=ACCENT_PRIMARY,
                tooltip="\u91cd\u65b0\u51c6\u5907",
                on_click=lambda e, r=rj_id: self._retry_prepare(r))
            btn_open = ft.IconButton(
                icon=ft.Icons.FOLDER_OPEN, icon_color=ACCENT_SECONDARY,
                tooltip="\u6253\u5f00\u76ee\u5f55",
                on_click=lambda e, r=rj_id: self._open_work_dir(r))
            btn_remove = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_color=ERROR,
                tooltip="\u79fb\u9664",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            actions.extend([btn_retry, btn_open, btn_remove])
            prog_bar = ft.ProgressBar(value=None, color="grey")
        elif ns == "duplicate":
            btn_open = ft.IconButton(
                icon=ft.Icons.FOLDER_OPEN, icon_color=ACCENT_SECONDARY,
                tooltip="\u6253\u5f00\u76ee\u5f55",
                on_click=lambda e, r=rj_id: self._open_work_dir(r))
            btn_force = ft.IconButton(
                icon=ft.Icons.FORCE_GRAPH_3, icon_color=WARNING,
                tooltip="\u4ecd\u7136\u4e0b\u8f7d",
                on_click=lambda e, r=rj_id: self._force_download(r))
            btn_clear = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_color="grey",
                tooltip="\u6e05\u9664",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            actions.extend([btn_open, btn_force, btn_clear])
        elif ns == "failed":
            btn_retry = ft.IconButton(
                icon=ft.Icons.REPLAY, icon_color=ACCENT_PRIMARY,
                tooltip="\u91cd\u8bd5\u4e0b\u8f7d",
                on_click=lambda e, r=rj_id: self._retry_failed(r))
            btn_clear = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_color=ERROR,
                tooltip="\u6e05\u7406\u5931\u8d25\u4efb\u52a1",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            btn_open = ft.IconButton(
                icon=ft.Icons.FOLDER_OPEN, icon_color=ACCENT_SECONDARY,
                tooltip="\u6253\u5f00\u4e0b\u8f7d\u76ee\u5f55",
                on_click=lambda e, r=rj_id: self._open_work_dir(r))
            actions.extend([btn_retry, btn_clear, btn_open])
        elif ns == "paused":
            btn_resume = ft.IconButton(
                icon=ft.Icons.PLAY_ARROW, icon_color=SUCCESS,
                tooltip="\u7ee7\u7eed\u4e0b\u8f7d",
                on_click=lambda e, r=rj_id: self.toggle_pause(r))
            btn_cancel = ft.IconButton(
                icon=ft.Icons.CANCEL, icon_color=ERROR,
                tooltip="暂停并从本次列表隐藏（保留断点）",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            actions.extend([btn_resume, btn_cancel])
        elif ns == "queued" or ns == "resuming":
            btn_pause = ft.IconButton(
                icon=ft.Icons.PAUSE, icon_color=ACCENT_PRIMARY,
                tooltip="\u6682\u505c",
                on_click=lambda e, r=rj_id: self.toggle_pause(r))
            btn_cancel = ft.IconButton(
                icon=ft.Icons.CANCEL, icon_color=ERROR,
                tooltip="暂停并从本次列表隐藏（保留断点）",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            actions.extend([btn_pause, btn_cancel])
        elif ns == "downloading":
            btn_pause = ft.IconButton(
                icon=ft.Icons.PAUSE, icon_color=ACCENT_PRIMARY,
                tooltip="\u6682\u505c",
                on_click=lambda e, r=rj_id: self.toggle_pause(r))
            btn_cancel = ft.IconButton(
                icon=ft.Icons.CANCEL, icon_color=ERROR,
                tooltip="暂停并从本次列表隐藏（保留断点）",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            btn_reconnect = ft.IconButton(
                icon=ft.Icons.REFRESH, icon_color=ACCENT_SECONDARY,
                tooltip="\u91cd\u8fde\uff08\u6682\u505c\u540e\u91cd\u65b0\u8fde\u63a5\uff09",
                on_click=lambda e, r=rj_id: self._reconnect_job(r))
            actions.extend([btn_pause, btn_cancel, btn_reconnect])

        actions_row = ft.Row(actions, spacing=0, alignment=ft.MainAxisAlignment.END)

        # Build per-file progress list from tracks data
        tracks = item_data.get("tracks", {})
        track_items = []
        showing_count = 0
        for tname, tdata in sorted(tracks.items()):
            if showing_count >= 8:
                track_items.append(ft.Text(f"  ... and {len(tracks)-8} more", size=10, color="grey"))
                break
            t_total = tdata.get("total", 0)
            t_dl = tdata.get("downloaded", 0)
            t_pct = t_dl / t_total if t_total > 0 else 0
            t_color = SUCCESS if t_pct >= 1.0 else ACCENT_PRIMARY
            short_name = tname[:35] + ".." if len(tname) > 35 else tname
            track_items.append(ft.Column([
                ft.Row([
                    ft.Text(short_name, size=10, color=ACCENT_SECONDARY, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{t_pct*100:.0f}%", size=10, color="grey"),
                ], spacing=6, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.ProgressBar(value=t_pct, color=t_color, bar_height=3),
            ], spacing=1))
            showing_count += 1

        # If no tracks yet, show status+speed row
        if not track_items:
            track_items = [
                ft.Row([status_text, speed_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                prog_bar,
            ]
        else:
            # Add status+speed+overall bar below track items
            track_items.append(ft.Row([status_text, speed_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
            track_items.append(prog_bar)

        main_info = ft.Column([
            title_text,
            identity_text,
            cur_title,
            *track_items,
        ], spacing=2, expand=True)

        tile = ft.Container(
            on_click=lambda e, r=rj_id: self.show_detailed_progress(r),
            content=ft.Row([
                self._build_cover(
                    rj_id,
                    item_data=item_data,
                    width=52,
                    height=52,
                ),
                ft.Container(content=main_info, expand=True, padding=ft.padding.only(left=10, right=10)),
                actions_row,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
        )

        container = Styles.glass_container(tile, padding=12)
        item_data["control"] = container
        item_data["title_text"] = title_text
        item_data["status_text"] = status_text
        item_data["speed_text"] = speed_text
        item_data["prog_bar"] = prog_bar

        existing = [c for c in self.queue_list.controls if getattr(c, 'data', None) == rj_id]
        if existing:
            idx = self.queue_list.controls.index(existing[0])
            container.data = rj_id
            self.queue_list.controls[idx] = container
        else:
            container.data = rj_id
            self.queue_list.controls.append(container)

        if update_list:
            try:
                if self.queue_list.page:
                    self.queue_list.update()
            except Exception:
                pass

    # ══════════════════════════════════════════════
    #  Status updates
    # ══════════════════════════════════════════════
    def update_work_status(self, rj_id: str, status: str):
        if "already_queued" in status.lower() or "already_running" in status.lower():
            return

        status_map = {
            "Preparing": "准备中...",
            "Prepared": "已就绪",
            "Prepared (cached)": "已就绪 [缓存]",
            "Fetching metadata...": "获取元数据中...",
            "Failed to fetch metadata": "获取元数据失败",
            "Fetching track list...": "获取文件列表...",
            "Failed to fetch tracks": "获取文件列表失败",
            "No tracks found": "未找到文件",
            "Queued": "队列中",
            "Queued (cached)": "队列中 [缓存]",
            "Downloading": "下载中",
            "Completed": "已完成",
            "Resuming...": "恢复中...",
            "No pending tracks": "无可恢复文件",
        }
        is_metadata_failure = (
            status.startswith("Metadata failed")
            or "metadata_failed" in status.lower()
        )
        if is_metadata_failure:
            cn_status = "元数据失败"
        elif status.startswith("Partially completed"):
            cn_status = "部分完成" + status[20:]
        elif status.startswith("Error:"):
            cn_status = "错误: " + status[6:]
        elif status.startswith("Paused"):
            cn_status = "已暂停"
        else:
            cn_status = status_map.get(status, status)

        data = self.active_downloads.setdefault(
            rj_id,
            {
                "status": cn_status,
                "tracks": {},
                "control": None,
                "last_time": time.time(),
                "last_bytes": 0,
                "cache_hit": False,
            },
        )
        data["status"] = cn_status
        if "cached" in status.lower():
            data["cache_hit"] = True

        state = WorkStatus.normalize(status)
        durable_states = {
            WorkStatus.QUEUED,
            WorkStatus.DOWNLOADING,
            WorkStatus.PAUSED,
            WorkStatus.FAILED,
            WorkStatus.COMPLETED,
            WorkStatus.PARTIAL,
        }
        if state in durable_states:
            self._transient_rj_ids = [
                item for item in self._transient_rj_ids if item != rj_id
            ]

        if rj_id in self._visible_rj_ids:
            self.build_queue_item(rj_id)

        if state is WorkStatus.COMPLETED:
            try:
                self.app_controller.check_achievements()
            except Exception:
                pass

        if state in durable_states or is_metadata_failure or state is WorkStatus.NO_PENDING:
            self.save_queue()
        if state in durable_states:
            self.refresh_queue_async()

    def toggle_pause(self, rj_id: str):
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        if data["status"] in ("已暂停", "Paused (partial)") or data["status"].startswith("Paused"):
            data["status"] = "队列中"
            data["cache_hit"] = False
            self.build_queue_item(rj_id)
            self.app_controller.resume_download(rj_id)
        else:
            self.app_controller.pause_download(rj_id)
            self.update_work_status(rj_id, "Paused")

    def _retry_failed(self, rj_id: str):
        """Retry a failed download."""
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        data["status"] = "队列中"
        data["cache_hit"] = False
        self.build_queue_item(rj_id)
        self.app_controller.resume_download(rj_id)

    def _force_download(self, rj_id: str):
        """Force download a duplicate work."""
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        data["status"] = "队列中"
        data["cache_hit"] = False
        self.build_queue_item(rj_id)
        self.app_controller.start_download(rj_id, allow_duplicate=True)

    def _reconnect_job(self, rj_id: str):
        """Pause → resume to force CDN reconnection."""
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        self.app_controller.reconnect_download(rj_id)

    def _retry_prepare(self, rj_id: str):
        """Retry metadata preparation."""
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        data["status"] = "准备中..."
        data["cache_hit"] = False
        self.build_queue_item(rj_id)
        self.app_controller.start_download(rj_id, force_refresh=True)
        self.app_controller.show_snack(f"{rj_id} 重新准备元数据中...")

    def _open_work_dir(self, rj_id: str):
        """Open the canonical directory recorded by the queue snapshot/works row."""
        path = self._find_work_dir(rj_id)
        if path is None:
            cached = self.app_controller.db.get_metadata_cache(
                rj_id,
                allow_stale=True,
            )
            if cached:
                title = Orchestrator.sanitize(cached.get("title", ""))
                folder = self.app_controller.config.dir_template.format(
                    rj_id=rj_id,
                    title=title,
                    circle="",
                    year="",
                )
                path = self.app_controller.config.output_dir / folder
            else:
                path = self.app_controller.config.output_dir

        if not path.exists():
            self.app_controller.show_snack(f"目录不存在: {path}")
            return

        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            self.app_controller.show_snack(f"打开目录失败: {exc}")

    def cancel_item(self, rj_id: str):
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        if not self._is_terminal(data["status"]):
            self.app_controller.cancel_download(rj_id)
            self.app_controller.show_snack(
                f"{rj_id} 已暂停并从本次列表隐藏；重启后仍可恢复"
            )
        self._transient_rj_ids = [
            item for item in self._transient_rj_ids if item != rj_id
        ]
        self._visible_rj_ids.discard(rj_id)
        self.active_downloads.pop(rj_id, None)
        self._render_visible_queue()
        self.save_queue()

    def update_track_progress(self, event):
        """Keep live speed/progress in memory; SQLite owns durable checkpoints."""
        rj_id = event.rj_id
        data = self.active_downloads.setdefault(
            rj_id,
            {
                "status": "下载中",
                "tracks": {},
                "control": None,
                "last_time": time.time(),
                "last_bytes": 0,
                "cache_hit": False,
            },
        )
        now = time.time()
        data.setdefault("tracks", {})[event.track_title] = {
            "downloaded": event.downloaded_bytes,
            "total": event.total_bytes,
            "status": event.status,
        }
        data["current_track"] = event.track_title
        data["last_speed_bps"] = event.global_speed_bps
        data["last_track_speed"] = event.track_speed_bps
        data["last_eta"] = event.eta_seconds

        # The event stream can be much faster than Flet rendering.  Do not write
        # queue.json or SQLite here; persist only lifecycle checkpoints in core.
        last_ui = data.get("_last_ui_update", 0)
        if now - last_ui < 0.3:
            return
        data["_last_ui_update"] = now

        if rj_id in self._visible_rj_ids:
            try:
                self.build_queue_item(rj_id)
            except Exception:
                logging.debug("progress card update failed", exc_info=True)

        if getattr(self, "current_dialog_rj", None) == rj_id and hasattr(
            self,
            "dialog_list",
        ):
            self.refresh_dialog_list(rj_id)

    def show_detailed_progress(self, rj_id: str):
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        self.current_dialog_rj = rj_id
        self.dialog_list = ft.ListView(expand=True, spacing=5, height=400)
        self.refresh_dialog_list(rj_id)
        dlg = ft.AlertDialog(
            title=ft.Text(f"详细进度 - {rj_id}"),
            content=ft.Container(self.dialog_list, width=600),
            actions=[ft.TextButton("关闭",
                     on_click=lambda e: self.close_dialog(dlg))]
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    def refresh_dialog_list(self, rj_id: str):
        data = self.active_downloads.get(rj_id)
        self.dialog_list.controls.clear()

        # Check: is this a metadata_failed entry?
        status = (data or {}).get("status", "")
        if "metadata_failed" in str(status).lower() or \
           status.startswith("Metadata failed"):
            self.dialog_list.controls.append(
                ft.Text("元数据未准备成功，请检查 metadata_proxy 后重新准备",
                        color=ERROR, size=14))
            try: self.dialog_list.update()
            except: pass
            return

        # Multi-fallback track detail
        tracks_data = data.get("tracks", {}) if data else {}
        details = self.app_controller.orc.get_track_detail_for_ui(
            rj_id, active_tracks=tracks_data)

        if not details:
            self.dialog_list.controls.append(
                ft.Text("暂无文件列表，请重新准备元数据",
                        color="grey", size=14))
        else:
            for d in details:
                total = d["total"]
                dl = d["downloaded"]
                prog = dl / total if total > 0 else 0
                color = (SUCCESS if d["status"] == "completed"
                         else ERROR if d["status"] == "failed"
                         else ACCENT_SECONDARY)
                title = d["title"][:40]
                self.dialog_list.controls.append(ft.Column([
                    ft.Row([
                        ft.Text(title, size=12),
                        ft.Text(f"{prog*100:.1f}%", size=12),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.ProgressBar(value=prog, color=color),
                ]))
        try:
            self.dialog_list.update()
        except Exception:
            pass

    def close_dialog(self, dlg):
        dlg.open = False
        self.current_dialog_rj = None
        self.page.update()
