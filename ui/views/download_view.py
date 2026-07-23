"""Active download queue UI for the post-RC hotfix.

The release-tested RC1 implementation is retained in
:mod:`ui.views.download_view_base`.  This subclass keeps the data and download
semantics unchanged while fixing the visible queue contract:

* batch actions reload once from SQLite;
* the header shows global throughput;
* cards show per-work throughput;
* completed work leaves the active queue immediately.
"""

import copy
from typing import Any, Dict

import ui.views.download_view_base as base_module
from ui.views.download_view_base import DownloadView as BaseDownloadView

QUEUE_FILE = base_module.QUEUE_FILE
platform = base_module.platform
subprocess = base_module.subprocess


class DownloadView(BaseDownloadView):
    @staticmethod
    def _sync_queue_file() -> None:
        base_module.QUEUE_FILE = QUEUE_FILE

    def save_queue(self):
        self._sync_queue_file()
        return super().save_queue()

    def load_queue(self):
        self._sync_queue_file()
        return super().load_queue()

    def __init__(self, app_controller):
        self.global_speed_bps = 0.0
        super().__init__(app_controller)
        self.btn_resume_all.text = "全部继续"
        self._update_queue_summary(list(self.active_downloads.keys()))

    def reload_queue_from_database(self, *, reset_speed: bool = False):
        """Replace visible cards with one fresh SQLite-derived snapshot."""
        if reset_speed:
            self.global_speed_bps = 0.0
        self.active_downloads.clear()
        self.queue_list.controls.clear()
        self.load_queue()

    def _remove_queue_item(self, rj_id: str, *, save: bool = True):
        """Remove a work from the active list without touching files/history."""
        data = self.active_downloads.pop(rj_id, None)
        if data and data.get("control") in self.queue_list.controls:
            self.queue_list.controls.remove(data["control"])
        if not any(
            self.normalize_status(item.get("status", "")) == "downloading"
            for item in self.active_downloads.values()
        ):
            self.global_speed_bps = 0.0
        self._update_queue_summary(list(self.active_downloads.keys()))
        try:
            if self.queue_list.page:
                self.queue_list.update()
        except Exception:
            pass
        if save:
            self.save_queue()

    def _set_batch_controls_busy(self):
        self.btn_pause_all.disabled = True
        self.btn_resume_all.disabled = True
        for control in (self.btn_pause_all, self.btn_resume_all):
            try:
                if control.page:
                    control.update()
            except Exception:
                pass

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

    def _update_queue_summary(self, visible_items):
        counts = {"downloading": 0, "queued": 0, "paused": 0, "failed": 0}
        for rj_id in visible_items:
            status = self.active_downloads.get(rj_id, {}).get("status", "")
            normalized = self.normalize_status(status)
            if normalized == "resuming":
                counts["downloading"] += 1
            elif normalized in counts:
                counts[normalized] += 1

        if counts["downloading"] == 0:
            self.global_speed_bps = 0.0
        self.queue_summary.value = (
            f"显示 {len(visible_items)} 项"
            f"  下载中 {counts['downloading']}"
            f"  排队 {counts['queued']}"
            f"  暂停 {counts['paused']}"
            f"  失败 {counts['failed']}"
            f"  总速度 {self._format_speed(self.global_speed_bps)}"
        )
        self.btn_pause_all.disabled = (
            counts["downloading"] + counts["queued"] == 0)
        self.btn_resume_all.disabled = (
            counts["paused"] + counts["failed"] == 0)

        for control in (self.queue_summary, self.btn_pause_all, self.btn_resume_all):
            try:
                if control.page:
                    control.update()
            except Exception:
                pass

    def process_input(self, text: str):
        super().process_input(text)
        self._update_queue_summary(list(self.active_downloads.keys()))

    def build_queue_item(self, rj_id: str, update_list: bool = True):
        super().build_queue_item(rj_id, update_list=update_list)
        data = self.active_downloads.get(rj_id)
        if not data:
            return
        speed = data.get("last_speed_bps", 0)
        speed_text = data.get("speed_text")
        if speed_text is not None:
            value = self._format_speed(speed) if speed > 0 else ""
            eta = data.get("last_eta")
            if value and eta:
                value += f"  ETA {eta:.0f}s"
            speed_text.value = value

    def update_work_status(self, rj_id: str, status: str):
        super().update_work_status(rj_id, status)
        if status == "Completed":
            # The DB is already terminal when this callback is emitted.
            self._remove_queue_item(rj_id)
            return
        self._update_queue_summary(list(self.active_downloads.keys()))

    def update_track_progress(self, event):
        # RC1 cards read event.global_speed_bps. Feed them the work aggregate,
        # while retaining the true global value for the queue header.
        card_event = copy.copy(event)
        card_event.global_speed_bps = event.work_speed_bps
        super().update_track_progress(card_event)
        self.global_speed_bps = event.global_speed_bps
        self._update_queue_summary(list(self.active_downloads.keys()))

    def toggle_pause(self, rj_id: str):
        super().toggle_pause(rj_id)
        self._update_queue_summary(list(self.active_downloads.keys()))

    def _retry_failed(self, rj_id: str):
        super()._retry_failed(rj_id)
        self._update_queue_summary(list(self.active_downloads.keys()))

    def _force_download(self, rj_id: str):
        super()._force_download(rj_id)
        self._update_queue_summary(list(self.active_downloads.keys()))

    def _retry_prepare(self, rj_id: str):
        super()._retry_prepare(rj_id)
        self._update_queue_summary(list(self.active_downloads.keys()))

    def cancel_item(self, rj_id: str):
        # The base method preserves .part files and only hides this session card.
        super().cancel_item(rj_id)
        self._update_queue_summary(list(self.active_downloads.keys()))
