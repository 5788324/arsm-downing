import flet as ft
import asyncio
import concurrent.futures
import threading
import queue
import time
import logging
from pathlib import Path

logger = logging.getLogger("echovault")


def configure_logging(log_dir: str | Path = "logs") -> None:
    """Configure application logging only when a real app is launched.

    Importing ``ui.app`` is part of the portable test gate.  Opening a file
    handler at import time leaked descriptors into test and tooling processes,
    so logging setup is explicit and idempotent.
    """
    root = logging.getLogger()
    if getattr(root, "_arsm_configured", False):
        return
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(directory / "app.log", encoding="utf-8"),
        ],
    )
    root._arsm_configured = True

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
        self.page.title = "ARSM Suite"
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
            self.page.window_prevent_close = True
            self.page.update()

            async def _do_shutdown():
                try:
                    await self.orc.shutdown()
                finally:
                    self.loop.stop()

            fut = asyncio.run_coroutine_threadsafe(_do_shutdown(), self.loop)

            def _finish_close(_future):
                self.ui_queue.put(("close_window",))

            fut.add_done_callback(_finish_close)

    # ──────────────────────────────────────────────────────
    #  Thread-safe message enqueue (called from any thread)
    # ──────────────────────────────────────────────────────
    def _enqueue_progress(self, event):
        """Called from download thread — puts ProgressEvent in queue."""
        self.ui_queue.put(("progress", event))

    def _enqueue_work_status(self, rj_id: str, status: str):
        """Called from download thread — puts message in queue."""
        self.ui_queue.put(("work_status", rj_id, status))

    def _enqueue_snack(self, message: str):
        self.ui_queue.put(("snack", message))

    def _submit_background(self, coroutine, action_label: str):
        """Submit work to the downloader loop and surface failures on UI thread."""
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)

        def _done(done_future):
            try:
                done_future.result()
            except (asyncio.CancelledError, concurrent.futures.CancelledError):
                pass
            except Exception as exc:
                logger.exception("%s failed", action_label)
                self._enqueue_snack(f"{action_label}失败: {exc}")

        future.add_done_callback(_done)
        return future

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

                    elif msg_type == "snack":
                        self.show_snack(msg[1])

                    elif msg_type == "ui_callback":
                        callback, result = msg[1], msg[2]
                        callback(result)

                    elif msg_type == "close_window":
                        try:
                            self.page.window_destroy()
                        except Exception:
                            try:
                                self.page.window_close()
                            except Exception:
                                pass

                    processed = True
                except queue.Empty:
                    break
                except Exception as e:
                    logging.debug(f"UI queue processing error: {e}")

        finally:
            self.ui_processing = False

    def run_blocking(self, function, on_success=None, *, action_label: str = "后台任务"):
        """Run blocking filesystem/SQLite presentation work off the Flet loop.

        ``function`` executes through ``asyncio.to_thread``.  The optional
        callback is marshalled back through the UI queue and therefore never
        mutates Flet controls from the worker thread.
        """
        async def _run():
            result = await asyncio.to_thread(function)
            if on_success is not None:
                self.ui_queue.put(("ui_callback", on_success, result))
            return result

        return self._submit_background(_run(), action_label)

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
                    icon=ft.Icons.CLOUD_DOWNLOAD_OUTLINED,
                    selected_icon=ft.Icons.CLOUD_DOWNLOAD,
                    label="下载中心"
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.LIBRARY_MUSIC_OUTLINED,
                    selected_icon=ft.Icons.LIBRARY_MUSIC,
                    label="资源库"
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.Icons.DASHBOARD,
                    label="统计与成就"
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.HANDYMAN_OUTLINED,
                    selected_icon=ft.Icons.HANDYMAN,
                    label="系统工具"
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
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
    def start_download(self, rj_id: str, *, allow_duplicate: bool = False,
                       force_refresh: bool = False):
        """Queue a download without updating Flet controls off the UI thread."""
        async def _do_start():
            result = await self.orc.queue_job(
                rj_id, force_refresh=force_refresh,
                allow_duplicate=allow_duplicate)
            status = result.get("status", "")
            if status == "already_queued":
                self._enqueue_snack(f"{rj_id} 已在队列中")
            elif status == "already_running":
                self._enqueue_snack(f"{rj_id} 正在下载")
            elif status == "queued":
                self._enqueue_work_status(rj_id, "Queued")
            return result

        return self._submit_background(_do_start(), "排队")

    def pause_download(self, rj_id: str):
        """Pause via background loop — thread-safe."""
        return self._submit_background(
            self.orc.pause_job_async(rj_id), "暂停")

    def resume_download(self, rj_id: str):
        """Resume one download and route all UI changes through ui_queue."""
        async def _do_resume():
            result = await self.orc._resume_one(rj_id)
            status = result.get("status", "")
            if status == "already_queued":
                self._enqueue_snack(f"{rj_id} 已在队列中")
            elif status == "already_running":
                self._enqueue_snack(f"{rj_id} 正在下载")
            elif status == "queued":
                self._enqueue_work_status(rj_id, "Queued")
            else:
                self._enqueue_work_status(rj_id, status)
            return result

        return self._submit_background(_do_resume(), "恢复")

    def reconnect_download(self, rj_id: str):
        """Pause and resume sequentially; avoids the old reconnect race."""
        async def _do_reconnect():
            self._enqueue_work_status(rj_id, "Resuming...")
            result = await self.orc.reconnect_job(rj_id)
            status = result.get("status", "")
            if status == "queued":
                self._enqueue_work_status(rj_id, "Queued")
                self._enqueue_snack(f"{rj_id} 已重新连接")
            else:
                self._enqueue_work_status(rj_id, status)
                self._enqueue_snack(
                    f"{rj_id} 重连失败: {result.get('message', status)}")
            return result

        return self._submit_background(_do_reconnect(), "重连")

    def cancel_download(self, rj_id: str):
        """Preserve current legacy behavior: pause while keeping partial files."""
        async def _do_cancel():
            self.orc.cancel_job(rj_id)
        return self._submit_background(_do_cancel(), "暂停并隐藏")

    def pause_all_downloads(self):
        async def _do_pause_all():
            rj_ids = self.orc.pause_all()
            if rj_ids:
                self._enqueue_snack(f"已暂停 {len(rj_ids)} 个任务")
            else:
                self._enqueue_snack("没有可暂停的任务")
            return rj_ids

        return self._submit_background(_do_pause_all(), "全部暂停")

    def resume_all_downloads(self):
        async def _do_resume_all():
            stats = await self.orc._resume_all_async()
            resumed = stats.get("resumed_to_queue", 0)
            failed = stats.get("failed", 0) + stats.get("no_cache", 0)
            self._enqueue_snack(
                f"已恢复 {resumed} 个任务"
                + (f"，{failed} 个需要手动处理" if failed else ""))
            return stats

        return self._submit_background(_do_resume_all(), "全部恢复")

    def show_snack(self, message: str):
        self.page.snack_bar = ft.SnackBar(ft.Text(message))
        self.page.snack_bar.open = True
        self.page.update()

    def check_achievements(self):
        if 2 in self.views:
            self.views[2].load_data()


def start_app(page: ft.Page):
    configure_logging()
    AppController(page)
