"""Post-RC application shell.

The RC1 controller remains in :mod:`ui.app_base`. This shell removes the
unused achievements page and adds one UI-thread refresh after global queue
operations. T10 can later fold the small compatibility layer back into the
service-oriented application structure without changing the release-tested
backend.
"""

import flet as ft

from ui.app_base import AppController as BaseAppController
from ui.app_base import configure_logging


class AppController(BaseAppController):
    """RC2 shell with four useful pages and synchronized batch controls."""

    def __init__(self, page: ft.Page):
        super().__init__(page)

        old_views = self.views
        self.views = {
            0: old_views[0],
            1: old_views[1],
            2: old_views[3],
            3: old_views[4],
        }
        if len(self.nav_rail.destinations) > 2:
            self.nav_rail.destinations.pop(2)
        self.nav_rail.selected_index = 0
        self.current_view = 0
        self.views_container.content = self.views[0]
        for index, view in self.views.items():
            setter = getattr(view, "set_active", None)
            if callable(setter):
                setter(index == 0)
        try:
            self.page.update()
        except Exception:
            pass

    def on_nav_change(self, e):
        idx = e.control.selected_index
        if idx not in self.views:
            return
        previous = self.views.get(self.current_view)
        if previous is not None:
            setter = getattr(previous, "set_active", None)
            if callable(setter):
                setter(False)
        self.current_view = idx
        current = self.views[idx]
        self.views_container.content = current
        self.views_container.update()
        setter = getattr(current, "set_active", None)
        if callable(setter):
            setter(True)
        elif idx == 1:
            current.load_library()
        elif idx == 2:
            current.refresh_backlog()

    def _queue_download_view_refresh(self, *, reset_speed: bool) -> None:
        def refresh(_result):
            self.views[0].reload_queue_from_database(reset_speed=reset_speed)

        self.ui_queue.put(("ui_callback", refresh, None))

    def pause_all_downloads(self):
        async def _do_pause_all():
            rj_ids = self.orc.pause_all()
            if rj_ids:
                self._enqueue_snack(f"已暂停 {len(rj_ids)} 个任务")
            else:
                self._enqueue_snack("没有可暂停的任务")
            self._queue_download_view_refresh(reset_speed=True)
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
            self._queue_download_view_refresh(reset_speed=False)
            return stats

        return self._submit_background(_do_resume_all(), "全部恢复")

    def check_achievements(self):
        """Compatibility no-op; the achievements page was removed in RC2."""


def start_app(page: ft.Page):
    configure_logging()
    AppController(page)
