import flet as ft
import asyncio
import threading
import queue
import time
import logging
import os
from pathlib import Path

# ── File logging ──
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("echovault")

from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel
from core.orchestrator import Orchestrator
from ui.theme import PremiumTheme, BG_DARK, BG_SURFACE
from ui.views.download_view import DownloadView
from ui.views.library_view import LibraryView
from ui.views.settings_view import SettingsView
from ui.views.dashboard_view import DashboardView
from ui.views.tools_view import ToolsView


class AppController:
    """Main application controller with thread-safe UI updates."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "EchoVault Premium"
        self.page.theme = PremiumTheme.get_theme()
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = BG_DARK
        self.page.padding = 0

        # ── RC7: graceful shutdown on window close ──
        self.page.on_window_event = self._on_window_event

        # ── UI message queue for thread-safe cross-thread updates ──
        self.ui_queue: queue.Queue = queue.Queue()

        # ── Initialize Core Backend ──
        self.config = ConfigManager.load()
        self.db = LibraryVault()
        self.kernel = NetworkKernel(self.config)
        self.orc = Orchestrator(self.kernel, self.config, self.db)

        # ── Async event loop on a dedicated thread ──
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()

        # ── Initialize Views ──
        self.views = {
            0: DownloadView(self),
            1: LibraryView(self),
            2: DashboardView(self),
            3: ToolsView(self),
            4: SettingsView(self)
        }
        self.current_view = 0

        # ── Wire callbacks via message queue (NOT direct UI calls) ──
        self.orc.set_callbacks(
            on_progress=self._enqueue_progress,
            on_work_status=self._enqueue_work_status
        )

        self.setup_ui()

        # ── Start background workers ──
        # ── Start background workers (work_concurrency) ──
        async def _start_workers():
            self.worker_tasks = await self.orc.boot_workers()
        asyncio.run_coroutine_threadsafe(_start_workers(), self.loop)

        # ── Restore pending downloads from previous session ──
        asyncio.run_coroutine_threadsafe(
            self.orc.restore_pending_downloads(), self.loop)

        # ── Start UI message queue poller ──
        self._start_ui_poller()

    # ──────────────────────────────────────────────────────
    #  Event loop thread
    # ──────────────────────────────────────────────────────
    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _on_window_event(self, e):
        """Graceful shutdown on window close."""
        if e.data == "close":
            async def _do_shutdown():
                await self.orc.shutdown()
                self.loop.stop()
            asyncio.run_coroutine_threadsafe(_do_shutdown(), self.loop)

    # ──────────────────────────────────────────────────────
    #  Thread-safe message enqueue (called from any thread)
    # ──────────────────────────────────────────────────────
    def _enqueue_progress(self, event):
        """Called from download thread — puts ProgressEvent in queue."""
        self.ui_queue.put(("progress", event))

    def _enqueue_work_status(self, rj_id: str, status: str):
        """Called from download thread — puts message in queue."""
        self.ui_queue.put(("work_status", rj_id, status))

    # ──────────────────────────────────────────────────────
    #  UI poller: runs on a background thread, schedules
    #  updates on Flet's main event loop via page.run_task()
    # ──────────────────────────────────────────────────────
    def _start_ui_poller(self):
        """Start a background thread that polls the message queue
        and dispatches UI updates to Flet's main event loop."""
        self.ui_processing = False

        def poll_loop():
            while True:
                time.sleep(0.1)
                try:
                    if not self.ui_processing and not self.ui_queue.empty():
                        self.ui_processing = True
                        self.page.run_task(self._process_ui_queue)
                except Exception as e:
                    logging.debug(f"UI poller error: {e}")

        threading.Thread(target=poll_loop, daemon=True).start()

    async def _process_ui_queue(self):
        """Process all pending UI messages. Runs on Flet's event loop."""
        processed = False
        try:
            while not self.ui_queue.empty():
                try:
                    msg = self.ui_queue.get_nowait()
                    msg_type = msg[0]

                    if msg_type == "progress":
                        event = msg[1]  # ProgressEvent
                        try:
                            self.views[0].update_track_progress(event)
                        except Exception as e:
                            logging.debug(f"UI progress update error: {e}")

                    elif msg_type == "work_status":
                        _, rj_id, status = msg
                        try:
                            self.views[0].update_work_status(rj_id, status)
                        except Exception as e:
                            logging.debug(f"UI work_status update error: {e}")

                    processed = True
                except queue.Empty:
                    break
                except Exception as e:
                    logging.debug(f"UI queue processing error: {e}")

            if processed:
                try:
                    self.page.update()
                except Exception:
                    pass
        finally:
            self.ui_processing = False

    # ──────────────────────────────────────────────────────
    #  UI setup
    # ──────────────────────────────────────────────────────
    def setup_ui(self):
        self.nav_rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=100,
            min_extended_width=200,
            group_alignment=-0.9,
            bgcolor=BG_SURFACE,
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.icons.CLOUD_DOWNLOAD_OUTLINED,
                    selected_icon=ft.icons.CLOUD_DOWNLOAD,
                    label="下载中心"
                ),
                ft.NavigationRailDestination(
                    icon=ft.icons.LIBRARY_MUSIC_OUTLINED,
                    selected_icon=ft.icons.LIBRARY_MUSIC,
                    label="资源库"
                ),
                ft.NavigationRailDestination(
                    icon=ft.icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.icons.DASHBOARD,
                    label="统计与成就"
                ),
                ft.NavigationRailDestination(
                    icon=ft.icons.HANDYMAN_OUTLINED,
                    selected_icon=ft.icons.HANDYMAN,
                    label="系统工具"
                ),
                ft.NavigationRailDestination(
                    icon=ft.icons.SETTINGS_OUTLINED,
                    selected_icon=ft.icons.SETTINGS,
                    label="设置"
                ),
            ],
            on_change=self.on_nav_change,
        )

        self.views_container = ft.Container(
            content=self.views[0],
            expand=True,
            padding=40
        )

        self.page.add(
            ft.Row(
                [
                    self.nav_rail,
                    ft.VerticalDivider(width=1),
                    self.views_container
                ],
                expand=True,
            )
        )

    def on_nav_change(self, e):
        idx = e.control.selected_index
        if idx in self.views:
            self.views_container.content = self.views[idx]
            self.views_container.update()

            if idx == 1:
                self.views[1].load_library()
            elif idx == 2:
                self.views[2].load_data()
            elif idx == 3:
                self.views[3].refresh_backlog()

    # ──────────────────────────────────────────────────────
    #  Actions (called from UI thread / Flet event loop)
    # ──────────────────────────────────────────────────────
    def start_download(self, rj_id: str):
        """Queue a download. Called from UI thread."""
        try:
            asyncio.run_coroutine_threadsafe(
                self.orc.queue_job(rj_id), self.loop
            )
        except Exception as e:
            self.show_snack(f"排队失败: {e}")

    def pause_download(self, rj_id: str):
        """Pause via background loop — thread-safe."""
        asyncio.run_coroutine_threadsafe(
            self.orc.pause_job_async(rj_id), self.loop)

    def resume_download(self, rj_id: str):
        """Resume a single download — unified _resume_one path."""
        async def _do_resume():
            result = await self.orc._resume_one(rj_id)
            st = result.get("status", "")
            if st == "already_queued":
                self.show_snack(f"{rj_id} 已在队列中")
            elif st == "already_running":
                pass  # already active, no update needed
            elif st == "queued":
                self.views[0].update_work_status(rj_id, "Queued")
            else:
                self.views[0].update_work_status(rj_id, st)
        try:
            asyncio.run_coroutine_threadsafe(_do_resume(), self.loop)
        except Exception as e:
            self.show_snack(f"恢复失败: {e}")

    def cancel_download(self, rj_id: str):
        """Cancel via background loop — thread-safe."""
        async def _do_cancel():
            self.orc.cancel_job(rj_id)
        asyncio.run_coroutine_threadsafe(_do_cancel(), self.loop)

    def show_snack(self, message: str):
        self.page.snack_bar = ft.SnackBar(ft.Text(message))
        self.page.snack_bar.open = True
        self.page.update()

    def check_achievements(self):
        if 2 in self.views:
            self.views[2].load_data()


def start_app(page: ft.Page):
    AppController(page)
