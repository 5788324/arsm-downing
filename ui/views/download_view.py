import flet as ft
import logging
import os
import platform
import subprocess
import re
import json
import time
from typing import Dict, Any, Optional
from pathlib import Path

from ui.theme import Styles, ACCENT_PRIMARY, ACCENT_SECONDARY, SUCCESS, WARNING, ERROR, BG_SURFACE_LIGHT
from core.status import WorkStatus
from core.orchestrator import Orchestrator

RJ_PATTERN = re.compile(r"(?:RJ)?(\d{6,})")
QUEUE_FILE = Path("queue.json")


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

        self.rj_input = ft.TextField(
            label="\u8f93\u5165 RJ \u53f7 (\u4f8b\u5982: RJ01603020)",
            hint_text="\u7c98\u8d34\u5355\u4e2a\u6216\u591a\u4e2aRJ\u53f7\uff08\u7a7a\u683c\u5206\u9694\uff09\u5e76\u6309\u56de\u8f66...",
            border_color=ACCENT_PRIMARY,
            focused_border_color=SUCCESS,
            border_radius=10,
            expand=True,
            on_submit=self.on_download_submit
        )

        self.download_btn = ft.ElevatedButton(
            "\u4e0b\u8f7d",
            icon=ft.icons.DOWNLOAD,
            style=ft.ButtonStyle(
                bgcolor=ACCENT_PRIMARY, color="white",
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.all(20)
            ),
            on_click=self.on_download_submit
        )

        self.file_picker = ft.FilePicker(on_result=self.on_file_selected)
        self.batch_btn = ft.ElevatedButton(
            "\u6279\u91cf\u5bfc\u5165\u6587\u4ef6", icon=ft.icons.FOLDER_OPEN,
            style=ft.ButtonStyle(
                bgcolor=BG_SURFACE_LIGHT, color="white",
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.all(20)
            ),
            on_click=lambda _: self.file_picker.pick_files(
                allowed_extensions=["txt"])
        )

        self.btn_pause_all = ft.ElevatedButton(
            "\u5168\u90e8\u6682\u505c", icon=ft.icons.PAUSE_CIRCLE,
            style=ft.ButtonStyle(
                bgcolor=WARNING, color="white",
                shape=ft.RoundedRectangleBorder(radius=10)),
            on_click=lambda e: self._batch_pause()
        )
        self.btn_resume_all = ft.ElevatedButton(
            "\u5168\u90e8\u5f00\u59cb", icon=ft.icons.PLAY_CIRCLE,
            style=ft.ButtonStyle(
                bgcolor=SUCCESS, color="white",
                shape=ft.RoundedRectangleBorder(radius=10)),
            on_click=lambda e: self._batch_resume()
        )

        self.queue_summary = ft.Text("", size=12, color="grey")
        self.queue_list = ft.ListView(
            expand=True,
            spacing=8,
            auto_scroll=False,
        )
        self.active_downloads: Dict[str, Dict[str, Any]] = {}

        controls_row = ft.Row([
            self.btn_pause_all,
            self.btn_resume_all,
        ], spacing=12)

        self.content = ft.Column([
            self.file_picker,
            ft.Text("\u4e0b\u8f7d\u4e2d\u5fc3", size=32, weight=ft.FontWeight.BOLD),
            ft.Row([self.rj_input, self.download_btn, self.batch_btn],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            controls_row,
            ft.Divider(height=6, color="transparent"),
            ft.Row([
                ft.Text("\u5f53\u524d\u4e0b\u8f7d\u961f\u5217", size=18, weight=ft.FontWeight.W_500,
                        color=ACCENT_PRIMARY),
                ft.Container(expand=True),
                self.queue_summary,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.queue_list,
        ], expand=True, spacing=6)

        self.load_queue()

    # ══════════════════════════════════════════════
    #  Queue persistence
    # ══════════════════════════════════════════════
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
        """Restore download queue from DB-derived state.

        Reads active RJs from DB, derives card state. Old queue.json track
        progress is discarded to prevent fake progress bars on queued/paused tasks.
        """
        try:
            db = self.app_controller.db
            pending_rjs = db.get_pending_rj_ids()
            loaded = 0

            for rj_id in sorted(pending_rjs):
                derived = self.derive_download_card_state(rj_id)
                if not derived["visible"]:
                    continue

                self.active_downloads[rj_id] = {
                    "status": derived["status"],
                    "tracks": {},  # fresh — no stale queue.json progress
                    "control": None, "last_time": time.time(),
                    "last_bytes": 0, "cache_hit": False,
                    "_derived_enum": derived["enum"],
                }
                loaded += 1

            self._refresh_queue()
            logging.info(
                f"load_queue: loaded={loaded} total_pending={len(pending_rjs)}")
        except Exception as e:
            logging.error(f"load_queue failed: {e}")

    def _batch_pause(self):
        ids = self.app_controller.orc.pause_all()
        self._refresh_queue()
        if not ids:
            self.app_controller.show_snack("没有可暂停的任务")
        else:
            self.app_controller.show_snack(f"已暂停 {len(ids)} 个任务")

    def _batch_resume(self):
        orc = self.app_controller.orc
        loop = self.app_controller.loop
        rj_ids = orc.resume_all()
        if not rj_ids:
            self.app_controller.show_snack("没有可恢复的任务")
            return
        import asyncio

        async def _resume_all():
            for rj_id in rj_ids:
                r = await orc._resume_one(rj_id)
                st = r.get("status", "unknown")
                if st == "queued":
                    self.update_work_status(rj_id, "Queued")
                elif st == "already_queued":
                    pass  # silently skip, already in queue
                elif st == "already_running":
                    pass  # silently skip, already active
                elif st == "no_pending":
                    self.update_work_status(rj_id, "No pending tracks")
                else:
                    self.update_work_status(rj_id, f"恢复失败: {r.get('message', st)}")
            self._refresh_queue()

        asyncio.run_coroutine_threadsafe(_resume_all(), loop)
        self.app_controller.show_snack(
            f"正在恢复 {len(rj_ids)} 个任务...")

    def process_input(self, text: str):
        codes = []
        for match in RJ_PATTERN.finditer(text):
            code = match.group(1)
            if code and code not in codes:
                codes.append(code)

        for rj_num in codes:
            rj_id = f"RJ{rj_num}"

            # ── P3.4: duplicate detection ──
            dup_entries = self.app_controller.db.find_in_library(rj_id)
            if dup_entries:
                dup_paths = ", ".join(e["work_dir"] for e in dup_entries[:3])
                self.app_controller.show_snack(
                    f"{rj_id} 已存在于仓库: {dup_paths}")
                self.active_downloads[rj_id] = {
                    "status": "重复 (跳过)",
                    "tracks": {}, "control": None,
                    "last_time": time.time(), "last_bytes": 0,
                    "cache_hit": False
                }
                self._refresh_queue()
                continue

            if rj_id not in self.active_downloads or \
               self.active_downloads[rj_id]["status"] == "已完成":
                self.active_downloads[rj_id] = {
                    "status": "队列中",
                    "tracks": {}, "control": None,
                    "last_time": time.time(), "last_bytes": 0,
                    "cache_hit": False
                }
                self.build_queue_item(rj_id)
                self.app_controller.start_download(rj_id)
        self.save_queue()

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
            self.app_controller.show_snack("成功从文件导入任务！")
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
        """Rebuild queue list from DB-derived state. Reads only — no DB writes."""
        visible_items = []
        self.queue_list.controls.clear()
        for rj_id in list(self.active_downloads.keys()):
            try:
                derived = self.derive_download_card_state(rj_id)

                data = self.active_downloads.get(rj_id)
                if data:
                    data["status"] = derived["status"]
                    data["_derived_enum"] = derived["enum"]

                if not derived["visible"]:
                    self.active_downloads.pop(rj_id, None)
                    continue

                visible_items.append(rj_id)
            except Exception as e:
                logging.warning(f"_refresh_queue skip {rj_id}: {e}")

        for rj_id in sorted(visible_items, key=self._queue_sort_key):
            self.build_queue_item(rj_id)

        self._update_queue_summary(visible_items)
        try:
            if self.queue_list.page:
                self.queue_list.update()
        except Exception:
            pass

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

    def _update_queue_summary(self, visible_items):
        counts = {"downloading": 0, "queued": 0, "paused": 0, "failed": 0}
        for rj_id in visible_items:
            ns = self.normalize_status(self.active_downloads.get(rj_id, {}).get("status", ""))
            if ns in counts:
                counts[ns] += 1
        self.queue_summary.value = (
            f"\u663e\u793a {len(visible_items)} \u9879"
            f"  \u4e0b\u8f7d\u4e2d {counts['downloading']}"
            f"  \u6392\u961f {counts['queued']}"
            f"  \u6682\u505c {counts['paused']}"
            f"  \u5931\u8d25 {counts['failed']}"
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
        if total <= 0:
            return 0.0
        return max(0.0, min(1.0, downloaded / total))

    def _find_work_dir(self, rj_id: str) -> Optional[Path]:
        try:
            rows = self.app_controller.db.search(rj_id, limit=10)
            for row in rows:
                if row["rj_id"] == rj_id and row["local_path"]:
                    return Path(row["local_path"])
        except Exception:
            pass
        return None

    def _resolve_cover_source(self, rj_id: str) -> Optional[str]:
        # 1. Local disk scan (best quality, no proxy)
        work_dir = self._find_work_dir(rj_id)
        if work_dir and work_dir.exists():
            for name in self.COVER_CANDIDATES:
                candidate = work_dir / name
                if candidate.exists():
                    return str(candidate)
            try:
                for child in work_dir.iterdir():
                    if child.is_file() and child.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                        lower_name = child.name.lower()
                        if "cover" in lower_name or "package" in lower_name or "main" in lower_name:
                            return str(child)
            except Exception:
                pass

        # 2. Metadata cache (works for new downloads with no local files yet)
        try:
            cached = self.app_controller.db.get_metadata_cache(rj_id)
            if cached and cached.get("cover_url"):
                return cached["cover_url"]
        except Exception:
            pass
        return None

    def _build_cover(self, rj_id: str, width: int = 72, height: int = 72):
        src = self._resolve_cover_source(rj_id)
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
            bgcolor=ft.colors.with_opacity(0.55, BG_SURFACE_LIGHT),
            alignment=ft.alignment.center,
            content=ft.Icon(ft.icons.ALBUM, color=ACCENT_PRIMARY, size=min(width, height) // 2),
        )

    def build_queue_item(self, rj_id: str):
        item_data = self.active_downloads[rj_id]
        status = item_data["status"]
        ns = self.normalize_status(status)

        title_text = ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=20)

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
        if self._is_terminal(status):
            prog = 1.0
        elif ns in ("queued", "resuming") and total <= 0:
            prog = 0.0
        prog_bar = ft.ProgressBar(
            value=prog,
            color=SUCCESS if (prog or 0) >= 1.0 else ACCENT_PRIMARY)

        actions = []
        if ns == "metadata_failed" or ns == "no_pending":
            btn_retry = ft.IconButton(
                icon=ft.icons.REFRESH, icon_color=ACCENT_PRIMARY,
                tooltip="\u91cd\u65b0\u51c6\u5907",
                on_click=lambda e, r=rj_id: self._retry_prepare(r))
            btn_open = ft.IconButton(
                icon=ft.icons.FOLDER_OPEN, icon_color=ACCENT_SECONDARY,
                tooltip="\u6253\u5f00\u76ee\u5f55",
                on_click=lambda e, r=rj_id: self._open_work_dir(r))
            btn_remove = ft.IconButton(
                icon=ft.icons.DELETE_OUTLINE, icon_color=ERROR,
                tooltip="\u79fb\u9664",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            actions.extend([btn_retry, btn_open, btn_remove])
            prog_bar = ft.ProgressBar(value=None, color="grey")
        elif ns == "duplicate":
            btn_open = ft.IconButton(
                icon=ft.icons.FOLDER_OPEN, icon_color=ACCENT_SECONDARY,
                tooltip="\u6253\u5f00\u76ee\u5f55",
                on_click=lambda e, r=rj_id: self._open_work_dir(r))
            btn_force = ft.IconButton(
                icon=ft.icons.FORCE_GRAPH_3, icon_color=WARNING,
                tooltip="\u4ecd\u7136\u4e0b\u8f7d",
                on_click=lambda e, r=rj_id: self._force_download(r))
            btn_clear = ft.IconButton(
                icon=ft.icons.DELETE_OUTLINE, icon_color="grey",
                tooltip="\u6e05\u9664",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            actions.extend([btn_open, btn_force, btn_clear])
        elif ns == "failed":
            btn_retry = ft.IconButton(
                icon=ft.icons.REPLAY, icon_color=ACCENT_PRIMARY,
                tooltip="\u91cd\u8bd5\u4e0b\u8f7d",
                on_click=lambda e, r=rj_id: self._retry_failed(r))
            btn_clear = ft.IconButton(
                icon=ft.icons.DELETE_OUTLINE, icon_color=ERROR,
                tooltip="\u6e05\u7406\u5931\u8d25\u4efb\u52a1",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            btn_open = ft.IconButton(
                icon=ft.icons.FOLDER_OPEN, icon_color=ACCENT_SECONDARY,
                tooltip="\u6253\u5f00\u4e0b\u8f7d\u76ee\u5f55",
                on_click=lambda e, r=rj_id: self._open_work_dir(r))
            actions.extend([btn_retry, btn_clear, btn_open])
        elif ns == "paused":
            btn_resume = ft.IconButton(
                icon=ft.icons.PLAY_ARROW, icon_color=SUCCESS,
                tooltip="\u7ee7\u7eed\u4e0b\u8f7d",
                on_click=lambda e, r=rj_id: self.toggle_pause(r))
            btn_cancel = ft.IconButton(
                icon=ft.icons.CANCEL, icon_color=ERROR,
                tooltip="\u53d6\u6d88\u4e0b\u8f7d",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            actions.extend([btn_resume, btn_cancel])
        elif ns == "queued" or ns == "resuming":
            btn_pause = ft.IconButton(
                icon=ft.icons.PAUSE, icon_color=ACCENT_PRIMARY,
                tooltip="\u6682\u505c",
                on_click=lambda e, r=rj_id: self.toggle_pause(r))
            btn_cancel = ft.IconButton(
                icon=ft.icons.CANCEL, icon_color=ERROR,
                tooltip="\u53d6\u6d88\u4e0b\u8f7d",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            actions.extend([btn_pause, btn_cancel])
        elif ns == "downloading":
            btn_pause = ft.IconButton(
                icon=ft.icons.PAUSE, icon_color=ACCENT_PRIMARY,
                tooltip="\u6682\u505c",
                on_click=lambda e, r=rj_id: self.toggle_pause(r))
            btn_cancel = ft.IconButton(
                icon=ft.icons.CANCEL, icon_color=ERROR,
                tooltip="\u53d6\u6d88\u4e0b\u8f7d",
                on_click=lambda e, r=rj_id: self.cancel_item(r))
            btn_reconnect = ft.IconButton(
                icon=ft.icons.REFRESH, icon_color=ACCENT_SECONDARY,
                tooltip="\u91cd\u8fde\uff08\u6682\u505c\u540e\u91cd\u65b0\u8fde\u63a5\uff09",
                on_click=lambda e, r=rj_id: self._reconnect_job(r))
            actions.extend([btn_pause, btn_cancel, btn_reconnect])

        actions_row = ft.Row(actions, spacing=0, alignment=ft.MainAxisAlignment.END)

        main_info = ft.Column([
            title_text,
            cur_title,
            ft.Row([status_text, speed_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            prog_bar,
        ], spacing=4, expand=True)

        tile = ft.Container(
            on_click=lambda e, r=rj_id: self.show_detailed_progress(r),
            content=ft.Row([
                self._build_cover(rj_id, width=52, height=52),
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

        try:
            if self.queue_list.page:
                self.queue_list.update()
        except Exception:
            pass

    # ══════════════════════════════════════════════
    #  Status updates
    # ══════════════════════════════════════════════
    def update_work_status(self, rj_id: str, status: str):
        status_map = {
            "Preparing": "准备中...",
            "Prepared": "已就绪",
            "Prepared (cached)": "已就绪 [缓存]",
            "Fetching metadata...": "获取元数据中...",
            "Failed to fetch metadata": "获取元数据失败",
            "Fetching track list...": "获取文件列表...",
            "Failed to fetch tracks": "获取文件列表失败",
            "No tracks found": "未找到文件",
            "Queued": "队列排队中",
            "Queued (cached)": "队列排队中 [缓存]",
            "Downloading": "下载中",
            "Completed": "已完成",
            "Resuming...": "恢复中...",
            "No pending tracks": "无可恢复文件",
        }

        # RC4: metadata_failed detection
        is_meta_fail = (status.startswith("Metadata failed") or
                        "metadata_failed" in status.lower())

        # RC7.3: already_queued / already_running must never display as status
        if "already_queued" in status.lower():
            return  # silently ignore, toast is handled by caller
        if "already_running" in status.lower():
            return  # silently ignore

        # RC7.4-bis: resuming must be transient; always re-derive from DB after
        if "resuming" in status.lower() or status == "恢复中...":
            # Accept the transient status but schedule a DB re-derive
            pass

        # Handle partial / error statuses
        if status.startswith("Partially completed"):
            cn_status = "部分完成" + status[20:]  # e.g. "部分完成 (2/3)"
        elif status.startswith("Error:"):
            cn_status = "错误: " + status[6:]
        elif status.startswith("Paused"):
            cn_status = "已暂停"
        elif status in status_map:
            cn_status = status_map[status]
        else:
            cn_status = status

        if rj_id in self.active_downloads:
            data = self.active_downloads[rj_id]
            data["status"] = cn_status
            ns = self.normalize_status(status)

            # Cache hit detection
            if "cached" in status.lower():
                data["cache_hit"] = True

            if "status_text" in data:
                data["status_text"].value = cn_status

                if ns == "metadata_failed":
                    data["status_text"].color = ERROR
                    data["prog_bar"].value = None
                    data["prog_bar"].color = "grey"
                    data["speed_text"].value = ""
                elif ns == "no_pending":
                    data["status_text"].color = WARNING
                    # RC7.4: no progress animation for no_pending
                    data["prog_bar"].value = 0.0
                    data["prog_bar"].color = "grey"
                    data["speed_text"].value = ""
                elif status == "Completed":
                    data["status_text"].color = SUCCESS
                    data["prog_bar"].value = 1.0
                    data["prog_bar"].color = SUCCESS
                    data["speed_text"].value = ""
                    self.app_controller.check_achievements()
                elif status.startswith("Failed") or status.startswith("Error"):
                    data["status_text"].color = ERROR
                    data["prog_bar"].color = ERROR
                    data["speed_text"].value = ""
                elif status == "Paused (partial)" or \
                     status.startswith("Paused"):
                    data["status_text"].color = WARNING
                    data["speed_text"].value = ""
                    # RC7.3: keep progress bar static at current value
                    try:
                        data["speed_text"].update()
                    except Exception:
                        pass
                elif status.startswith("Partially completed"):
                    data["status_text"].color = WARNING
                    data["speed_text"].value = ""

                # Rebuild to update action buttons
                self.build_queue_item(rj_id)
                self.save_queue()

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
        self.app_controller.start_download(rj_id)

    def _reconnect_job(self, rj_id: str):
        """Pause → resume to force CDN reconnection."""
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        self.app_controller.pause_download(rj_id)
        self.app_controller.resume_download(rj_id)
        self.update_work_status(rj_id, "Resuming...")
        self.app_controller.show_snack(f"{rj_id} 重连中...")

    def _retry_prepare(self, rj_id: str):
        """Retry metadata preparation."""
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        data["status"] = "准备中..."
        data["cache_hit"] = False
        self.build_queue_item(rj_id)
        self.app_controller.start_download(rj_id)
        self.app_controller.show_snack(f"{rj_id} 重新准备元数据中...")

    def _open_work_dir(self, rj_id: str):
        """Open the download directory for this work."""
        cfg = self.app_controller.config
        cached = self.app_controller.db.get_metadata_cache(rj_id)
        if cached:
            title = Orchestrator.sanitize(cached.get("title", ""))
            dir_template = cfg.dir_template
            folder = dir_template.format(rj_id=rj_id, title=title,
                                         circle="", year="")
            path = cfg.output_dir / folder
        else:
            path = cfg.output_dir

        path = Path(path)
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

    def cancel_item(self, rj_id: str):
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        if not self._is_terminal(data["status"]):
            self.app_controller.cancel_download(rj_id)
        if data.get("control") and data["control"] in self.queue_list.controls:
            self.queue_list.controls.remove(data["control"])
        self.active_downloads.pop(rj_id, None)
        try:
            if self.queue_list.page: self.queue_list.update()
        except Exception:
            pass
        self.save_queue()

    # ══════════════════════════════════════════════
    #  Track progress (P3: store speed/eta)
    # ══════════════════════════════════════════════
    def update_track_progress(self, event):
        """Accept ProgressEvent — throttled UI updates to prevent freeze."""
        rj_id = event.rj_id
        track_title = event.track_title
        downloaded = event.downloaded_bytes
        total = event.total_bytes

        if rj_id not in self.active_downloads:
            return

        data = self.active_downloads[rj_id]
        now = time.time()

        if "tracks" not in data:
            data["tracks"] = {}

        data["tracks"][track_title] = {
            "downloaded": downloaded,
            "total": total,
            "status": event.status
        }

        data["current_track"] = event.track_title
        data["last_speed_bps"] = event.global_speed_bps
        data["last_track_speed"] = event.track_speed_bps
        data["last_eta"] = event.eta_seconds

        # Throttle: max 3 UI updates per second to prevent freeze
        last_ui = data.get("_last_ui_update", 0)
        if now - last_ui < 0.3:
            return
        data["_last_ui_update"] = now

        # ── RC7.3: paused items — update data ONLY, no visual animation ──
        ui_status = data.get("status", "")
        is_paused = (
            ui_status in ("已暂停", "Paused (partial)") or
            ui_status.startswith("Paused") or
            "paused" in str(ui_status).lower())

        if is_paused:
            # Update downloaded/total in data but NOT visual controls
            # The progress bar stays at last known static value
            # Speed stays at 0 / empty
            if "speed_text" in data:
                data["speed_text"].value = ""
                try:
                    data["speed_text"].update()
                except Exception:
                    pass
            return

        total_bytes = sum(t["total"] for t in data["tracks"].values())
        downloaded_bytes = sum(t["downloaded"] for t in data["tracks"].values())

        if total_bytes > 0:
            prog = downloaded_bytes / total_bytes
            if "prog_bar" in data:
                data["prog_bar"].value = prog

            # Display core-calculated speed
            if data.get("status") == "下载中":
                gbps = event.global_speed_bps
                if "speed_text" in data:
                    if gbps > 0:
                        eta = event.eta_seconds
                        speed_str = f"{gbps/1024/1024:.2f} MB/s"
                        if eta:
                            speed_str += f" ETA {eta:.0f}s"
                        data["speed_text"].value = speed_str
                    else:
                        data["speed_text"].value = "连接中..."
                    try:
                        data["speed_text"].update()
                    except Exception:
                        pass
            elif data.get("status") in ("队列排队中", "队列中"):
                if "speed_text" in data:
                    data["speed_text"].value = ""
                    try:
                        data["speed_text"].update()
                    except Exception:
                        pass

            try:
                if "prog_bar" in data:
                    data["prog_bar"].update()
            except Exception:
                pass

        if hasattr(self, "current_dialog_rj") and \
           self.current_dialog_rj == rj_id:
            if hasattr(self, "dialog_list"):
                self.refresh_dialog_list(rj_id)

        if time.time() - getattr(self, "last_save", 0) > 5:
            self.save_queue()
            self.last_save = time.time()

    # ══════════════════════════════════════════════
    #  Detail dialog (unchanged)
    # ══════════════════════════════════════════════
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
