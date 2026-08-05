import flet as ft
import asyncio
import concurrent.futures
import threading
import queue
import time
import logging
from pathlib import Path

from core.paths import app_path
from core.shutdown_signal import ShutdownSignal
from core.version import display_title
from core.tray import SystemTray
from core.ui_dispatch import UiDispatcher

logger = logging.getLogger("echovault")


def configure_logging(log_dir: str | Path | None = None) -> None:
    """Configure application logging only when a real app is launched.

    Importing ``ui.app`` is part of the portable test gate.  Opening a file
    handler at import time leaked descriptors into test and tooling processes,
    so logging setup is explicit and idempotent.
    """
    root = logging.getLogger()
    if getattr(root, "_arsm_configured", False):
        return
    directory = Path(log_dir) if log_dir is not None else app_path("logs")
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
        self.page.title = display_title()
        self.page.theme = PremiumTheme.get_theme()
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = BG_DARK
        self.page.padding = 0

        # ── Graceful shutdown on window close ──
        # Flet 0.27 moved window events and window state under ``page.window``.
        # Register the guard before a close is requested: otherwise Windows
        # destroys the native window first and leaves this Python process (and
        # its downloader loop) alive without a visible window.
        self.page.window.prevent_close = True
        self.page.window.on_event = self._on_window_event
        self._closing = False
        self._exit_requested = False
        self._ui_poller_stop = threading.Event()

        # ── UI message queue for thread-safe cross-thread updates ──
        self.ui_queue: queue.Queue = queue.Queue()
        # P0-A: high-frequency progress events are coalesced instead of flooding
        # the control queue.  Control messages keep their own priority queue.
        self.ui_dispatcher = UiDispatcher()
        self.ui_metrics = {
            "dispatch_count": 0,
            "control_processed": 0,
            "progress_processed": 0,
            "protected_processed": 0,
            "pending_after": 0,
            "last_dispatch_ms": 0.0,
            "max_dispatch_ms": 0.0,
            "received": 0,
            "coalesced": 0,
        }
        # Per-dispatch budgets: yield back to Flet's event loop once exceeded.
        self._ui_control_budget = 256
        self._ui_dispatch_budget_ms = 50.0
        # Single-scheduler guard for the UI drain: the background poller and the
        # drain task itself both claim scheduling through this lock, so at most
        # one ``_process_ui_queue`` is ever running or scheduled at a time.
        self._ui_schedule_lock = threading.Lock()
        self.ui_processing = False
        self._ui_last_tick = time.time()
        self.shutdown_signal = ShutdownSignal(
            lambda: self.ui_queue.put(("installer_shutdown",))
        )
        self.shutdown_signal.start()
        self.tray = SystemTray(
            on_show=lambda: self.ui_queue.put(("tray_show_window",)),
            on_pause_all=lambda: self.ui_queue.put(("tray_pause_all",)),
            on_resume_all=lambda: self.ui_queue.put(("tray_resume_all",)),
            on_exit=lambda: self.ui_queue.put(("tray_exit",)),
        )

        # ── Initialize Core Backend ──
        self.config = ConfigManager.load()
        self.db = LibraryVault()
        self.kernel = NetworkKernel(self.config)
        self.orc = Orchestrator(self.kernel, self.config, self.db)

        # ── Async event loop on a dedicated thread ──
        self.loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop, name="arsm-async-loop", daemon=True
        )
        self._loop_thread.start()

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
        self.tray.start()

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
        try:
            self.loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(self.loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self.loop.close()

    async def _shutdown_backend(self):
        """Stop workers and close backend resources exactly once."""
        await self.orc.shutdown()
        self.db.close()

    def _on_window_event(self, e):
        """Hide to tray on a normal close; explicit tray exit shuts down."""
        if e.data != "close" or self._closing:
            return
        if not self._exit_requested and self.tray.available:
            self._hide_to_tray()
            return
        self._begin_shutdown()

    def _begin_shutdown(self) -> None:
        """Begin the existing idempotent backend shutdown sequence."""
        if self._closing:
            return
        self._closing = True
        try:
            self.page.window.prevent_close = True
            self.page.update()
        except Exception:
            logger.debug("Unable to set window close guard", exc_info=True)

        future = asyncio.run_coroutine_threadsafe(
            self._shutdown_backend(), self.loop
        )

        def _finish_close(done_future):
            error = None
            try:
                done_future.result()
            except Exception as exc:  # close the UI even if cleanup reports an error
                error = str(exc)
                logger.exception("Application shutdown failed")
            self.ui_queue.put(("close_window", error))
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError:
                pass

        future.add_done_callback(_finish_close)

    def _hide_to_tray(self) -> None:
        try:
            self.page.window.visible = False
            self.page.update()
            logger.info("Window hidden to system tray")
        except Exception:
            logger.exception("Unable to hide window to system tray")
            self._begin_shutdown()

    def _show_from_tray(self) -> None:
        try:
            self.page.window.visible = True
            self.page.window.minimized = False
            self.page.window.to_front()
            self.page.update()
            logger.info("Window restored from system tray")
        except Exception:
            logger.exception("Unable to restore window from system tray")

    def _exit_from_tray(self) -> None:
        self._exit_requested = True
        self._begin_shutdown()

    # ──────────────────────────────────────────────────────
    #  Thread-safe message enqueue (called from any thread)
    # ──────────────────────────────────────────────────────
    def _enqueue_progress(self, event):
        """Called from the downloader loop — coalesced into the UI dispatcher."""
        self.ui_dispatcher.submit(event)

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
            while not self._ui_poller_stop.wait(0.1):
                try:
                    # At most one drain runs at a time; the poller is just one
                    # of the two schedulers (the drain may re-schedule itself).
                    self._schedule_ui_if_pending()
                except Exception as e:
                    logging.debug(f"UI poller error: {e}")

        threading.Thread(target=poll_loop, daemon=True).start()

    def _schedule_ui_if_pending(self) -> bool:
        """Atomically claim and schedule exactly one UI drain.

        Returns True if this call scheduled a drain.  The background poller and
        ``_process_ui_queue`` (which may re-schedule itself) share this guard,
        so duplicate/concurrent drains are impossible.
        """
        with self._ui_schedule_lock:
            if self.ui_processing:
                return False
            if not self._ui_has_pending_work():
                return False
            if not self._schedule_ui_processing():
                return False
            self.ui_processing = True
            return True

    def _ui_has_pending_work(self) -> bool:
        """True when either control messages or coalesced progress are waiting."""
        if not self.ui_queue.empty():
            return True
        dispatcher = getattr(self, "ui_dispatcher", None)
        if dispatcher is not None and dispatcher.has_pending():
            return True
        return False

    async def _process_ui_queue(self):
        """Process pending UI work under count + time double budget (P0-A).

        Control messages (close/tray/status/snack) are consumed first so they
        are never starved by progress traffic; both the control loop and the
        progress batch check the 50ms time budget.  Progress is applied from one
        coalesced snapshot; anything left over is requeued.  If new work is
        still pending after the budget, the method yields to Flet's event loop
        (``await asyncio.sleep(0)``) and re-schedules itself through the same
        single-scheduler guard — a perpetually-fed queue can never keep
        ``_process_ui_queue`` from returning or spawn a second concurrent drain.
        """
        started = time.perf_counter()
        control_processed = 0
        progress_processed = 0
        protected_processed = 0
        budget_ms = getattr(self, "_ui_dispatch_budget_ms", 50.0)
        try:
            control_budget = getattr(self, "_ui_control_budget", 256)
            while control_processed < control_budget:
                if (time.perf_counter() - started) * 1000.0 > budget_ms:
                    break
                try:
                    msg = self.ui_queue.get_nowait()
                except queue.Empty:
                    break
                control_processed += 1
                self._dispatch_control_message(msg)

            dispatcher = getattr(self, "ui_dispatcher", None)
            if dispatcher is not None and dispatcher.has_pending():
                latest_batch, protected_batch = dispatcher.drain()
                remaining = []
                for event in protected_batch + latest_batch:
                    if (time.perf_counter() - started) * 1000.0 > budget_ms:
                        remaining.append(event)
                        continue
                    if event.status in ("completed", "failed", "paused", "cancelled"):
                        protected_processed += 1
                    else:
                        progress_processed += 1
                    self._apply_progress_event(event)
                if remaining:
                    dispatcher.requeue(remaining)
        except Exception as exc:
            logging.debug("UI queue processing error: %s", exc)

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        metrics = getattr(self, "ui_metrics", None)
        if metrics is not None:
            metrics["dispatch_count"] += 1
            metrics["control_processed"] += control_processed
            metrics["progress_processed"] += progress_processed
            metrics["protected_processed"] += protected_processed
            metrics["last_dispatch_ms"] = elapsed_ms
            metrics["max_dispatch_ms"] = max(
                metrics.get("max_dispatch_ms", 0.0), elapsed_ms)
            dispatcher = getattr(self, "ui_dispatcher", None)
            if dispatcher is not None:
                metrics["pending_after"] = dispatcher.pending_count()
                metrics["received"] = dispatcher.received
                metrics["coalesced"] = dispatcher.coalesced
        self._ui_last_tick = time.time()

        # Yield back to Flet and re-schedule only if more work is already
        # waiting.  The flag stays True while we re-schedule, so the background
        # poller cannot start a second concurrent drain; it is cleared only when
        # there is genuinely nothing left to process.
        if control_processed or progress_processed or protected_processed:
            if self._ui_has_pending_work():
                await asyncio.sleep(0)
                with self._ui_schedule_lock:
                    if self._schedule_ui_processing():
                        self.ui_processing = True
                    else:
                        self.ui_processing = False
                return
        with self._ui_schedule_lock:
            self.ui_processing = False

    def _schedule_ui_processing(self) -> bool:
        try:
            self.page.run_task(self._process_ui_queue)
            return True
        except Exception:
            logging.debug("Unable to re-schedule UI processing", exc_info=True)
            return False

    def _apply_progress_event(self, event) -> None:
        try:
            self.views[0].update_track_progress(event)
        except Exception as exc:
            logging.debug("UI progress update error: %s", exc)

    def _dispatch_control_message(self, msg) -> None:
        """Route one control message; a single bad message must not kill the loop."""
        try:
            msg_type = msg[0]
            if msg_type == "work_status":
                _, rj_id, status = msg
                self.views[0].update_work_status(rj_id, status)
            elif msg_type == "snack":
                self.show_snack(msg[1])
            elif msg_type == "ui_callback":
                callback, result = msg[1], msg[2]
                callback(result)
            elif msg_type == "tray_show_window":
                self._show_from_tray()
            elif msg_type == "tray_pause_all":
                self.pause_all_downloads()
            elif msg_type == "tray_resume_all":
                self.resume_all_downloads()
            elif msg_type == "tray_exit":
                self._exit_from_tray()
            elif msg_type == "installer_shutdown":
                self._exit_requested = True
                self._begin_shutdown()
            elif msg_type == "close_window":
                self._ui_poller_stop.set()
                tray = getattr(self, "tray", None)
                if tray is not None:
                    tray.stop()
                error = msg[1] if len(msg) > 1 else None
                if error:
                    logger.error("Closing after shutdown error: %s", error)
                try:
                    self.page.window.destroy()
                except Exception:
                    try:
                        self.page.window.close()
                    except Exception:
                        logging.debug("Unable to close Flet window", exc_info=True)
                shutdown_signal = getattr(self, "shutdown_signal", None)
                if shutdown_signal is not None:
                    shutdown_signal.mark_stopped()
                    shutdown_signal.close()
        except Exception as exc:
            logging.debug("UI queue message error: %s", exc)

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
        """Resume one download and map structured core outcomes to UI states."""
        async def _do_resume():
            result = await self.orc._resume_one(rj_id)
            status = result.get("status", "")
            if status == "already_queued":
                self._enqueue_snack(f"{rj_id} 已在队列中或正在恢复")
            elif status == "already_running":
                self._enqueue_snack(f"{rj_id} 正在下载")
            elif status == "queued":
                self._enqueue_work_status(rj_id, "Queued")
                if int(result.get("unrecoverable", 0) or 0):
                    self._enqueue_snack(
                        f"{rj_id} 已继续可恢复文件；另有文件需要手动检查"
                    )
            elif status == "reconciled_complete":
                self._enqueue_work_status(rj_id, "Completed")
            elif status == "metadata_required":
                self._enqueue_work_status(rj_id, "Metadata required")
            elif status == "unrecoverable":
                self._enqueue_work_status(rj_id, "Failed: manual review required")
                self._enqueue_snack(f"{rj_id} 的本地文件异常，需要手动检查")
            elif status == "no_pending":
                self._enqueue_work_status(rj_id, "No pending tracks")
            elif status == "cancelled":
                self._enqueue_work_status(rj_id, "Cancelled")
            elif status == "paused":
                self._enqueue_work_status(rj_id, "Paused")
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

    def pause_and_hide_download(self, rj_id: str):
        """Pause a task and let the view hide it without changing its semantics."""
        async def _do_pause_hide():
            result = self.orc.pause_job(rj_id)
            self._enqueue_snack(f"{rj_id} 已暂停并隐藏；稍后可以继续")
            return result
        return self._submit_background(_do_pause_hide(), "暂停并隐藏")

    def cancel_download(self, rj_id: str):
        """Persist a true cancelled state while preserving partial files."""
        async def _do_cancel():
            result = self.orc.cancel_job(rj_id)
            status = result.get("status", "")
            if status == "cancelled":
                self._enqueue_work_status(rj_id, "Cancelled")
                self._enqueue_snack(f"{rj_id} 已取消；断点文件已保留")
            elif status == "already_terminal":
                self._enqueue_snack(f"{rj_id} 已完成，未执行取消")
            else:
                self._enqueue_snack(f"{rj_id} 取消结果: {status or 'unknown'}")
            return result
        return self._submit_background(_do_cancel(), "取消任务")

    def resume_cancelled_download(self, rj_id: str):
        """Explicitly retry a previously cancelled task."""
        async def _do_retry():
            result = await self.orc.retry_cancelled_job(rj_id)
            status = result.get("status", "")
            if status == "queued":
                self._enqueue_work_status(rj_id, "Queued")
                if int(result.get("unrecoverable", 0) or 0):
                    self._enqueue_snack(
                        f"{rj_id} 已继续可恢复断点；另有文件需要手动检查"
                    )
                else:
                    self._enqueue_snack(f"{rj_id} 已从保留断点继续")
            elif status == "reconciled_complete":
                self._enqueue_work_status(rj_id, "Completed")
                self._enqueue_snack(f"{rj_id} 本地文件已完整，无需重新下载")
            elif status == "metadata_required":
                self._enqueue_work_status(rj_id, "Metadata required")
                self._enqueue_snack(f"{rj_id} 需要重新获取元数据")
            elif status == "unrecoverable":
                self._enqueue_work_status(rj_id, "Failed: manual review required")
                self._enqueue_snack(f"{rj_id} 的本地文件异常，需要手动检查")
            elif status == "no_pending":
                self._enqueue_work_status(rj_id, "No pending tracks")
                self._enqueue_snack(f"{rj_id} 没有可继续的文件")
            elif status == "paused":
                self._enqueue_work_status(rj_id, "Paused")
                self._enqueue_snack(f"{rj_id} 在恢复过程中被暂停")
            else:
                self._enqueue_work_status(rj_id, status)
                self._enqueue_snack(
                    f"{rj_id} 无法继续: {result.get('message', status)}"
                )
            return result
        return self._submit_background(_do_retry(), "继续已取消任务")

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
            failed = (stats.get("failed", 0) + stats.get("metadata_required", 0)
                      + stats.get("unrecoverable", 0))
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