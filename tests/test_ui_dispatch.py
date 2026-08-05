"""P0-A: coalescing UI dispatcher must survive a 300+ event flood.

Issue #20: every downloaded chunk became one UI message, and the consumer loop
drained until empty — a perpetually-fed queue starved Flet's event loop.  These
tests pin the coalescing contract: latest wins per (rj, track), protected
outcomes are never lost, and drain returns bounded snapshots.
"""

from __future__ import annotations

import asyncio
import queue

from core.models import ProgressEvent
from core.ui_dispatch import UiDispatcher


def _progress(rj_id: str, track_id: str, downloaded: int, total: int = 100,
              status: str = "downloading") -> ProgressEvent:
    return ProgressEvent(
        rj_id=rj_id, track_id=track_id, track_title=track_id,
        downloaded_bytes=downloaded, total_bytes=total,
        percent=round(downloaded / total * 100, 1) if total else 0.0,
        track_speed_bps=0.0, work_speed_bps=0.0, global_speed_bps=0.0,
        eta_seconds=None, status=status,
    )


def test_flood_of_300_events_coalesces_to_latest() -> None:
    dispatcher = UiDispatcher()
    for chunk in range(300):
        dispatcher.submit(_progress("RJ00000001", "track-1", chunk))
    assert dispatcher.received == 300
    assert dispatcher.coalesced == 299
    assert dispatcher.pending_count() == 1

    latest, protected = dispatcher.drain()
    assert protected == []
    assert len(latest) == 1
    assert latest[0].downloaded_bytes == 299
    assert not dispatcher.has_pending()


def test_protected_outcome_survives_flood_and_sets_terminal() -> None:
    dispatcher = UiDispatcher()
    for chunk in range(200):
        dispatcher.submit(_progress("RJ00000001", "track-1", chunk))
    dispatcher.submit(_progress("RJ00000001", "track-1", 100, status="completed"))
    # A late non-terminal tick must never resurrect a protected outcome.
    dispatcher.submit(_progress("RJ00000001", "track-1", 50, status="downloading"))

    latest, protected = dispatcher.drain()
    assert len(protected) == 1
    assert protected[0].status == "completed"
    assert all(event.status != "downloading" for event in latest)


def test_distinct_tracks_coalesce_independently() -> None:
    dispatcher = UiDispatcher()
    for chunk in range(50):
        dispatcher.submit(_progress("RJ00000001", "a.mp3", chunk))
    for chunk in range(80):
        dispatcher.submit(_progress("RJ00000001", "b.mp3", chunk))
    for chunk in range(20):
        dispatcher.submit(_progress("RJ00000002", "c.mp3", chunk))

    latest, protected = dispatcher.drain()
    assert len(latest) == 3
    by_key = {(e.rj_id, e.track_id): e for e in latest}
    assert by_key[("RJ00000001", "a.mp3")].downloaded_bytes == 49
    assert by_key[("RJ00000001", "b.mp3")].downloaded_bytes == 79
    assert by_key[("RJ00000002", "c.mp3")].downloaded_bytes == 19


def test_drain_is_atomic_snapshot() -> None:
    dispatcher = UiDispatcher()
    dispatcher.submit(_progress("RJ00000001", "a.mp3", 10))
    first = dispatcher.drain()
    assert len(first[0]) == 1
    assert not dispatcher.has_pending()
    # Nothing submitted in between → second drain is empty.
    second = dispatcher.drain()
    assert second == ([], [])


def test_requeue_returns_unprocessed_events() -> None:
    dispatcher = UiDispatcher()
    dispatcher.submit(_progress("RJ00000001", "a.mp3", 10))
    dispatcher.submit(_progress("RJ00000001", "b.mp3", 5, status="failed"))
    latest, protected = dispatcher.drain()
    # Simulate a budget cut: drop the protected event back.
    dispatcher.requeue(protected)
    assert dispatcher.pending_count() == 1
    latest2, protected2 = dispatcher.drain()
    assert len(protected2) == 1
    assert protected2[0].status == "failed"
    assert not dispatcher.has_pending()


def test_clear_resets_state_and_metrics_keep_running_total() -> None:
    dispatcher = UiDispatcher()
    dispatcher.submit(_progress("RJ00000001", "a.mp3", 10))
    dispatcher.clear()
    assert not dispatcher.has_pending()
    assert dispatcher.received == 1
    dispatcher.submit(_progress("RJ00000001", "a.mp3", 20))
    assert dispatcher.received == 2


class _NoopView:
    def update_track_progress(self, event):
        return None

    def update_work_status(self, rj_id, status):
        return None


class _NoopWindow:
    destroyed = False
    closed = False


class _NoopPage:
    def __init__(self):
        self.window = _NoopWindow()


class _Harness:
    """Minimal controller shell: real dispatcher + real _process_ui_queue."""

    def __init__(self):
        from ui.app_base import AppController
        self.controller = AppController.__new__(AppController)
        self.controller.page = _NoopPage()
        self.controller.ui_queue = queue.Queue()
        self.controller.ui_dispatcher = UiDispatcher()
        self.controller.ui_processing = False
        self.controller._ui_last_tick = 0.0
        self.controller.views = {0: _NoopView()}
        self.controller.tray = None
        self.controller.ui_metrics = {
            "dispatch_count": 0, "control_processed": 0, "progress_processed": 0,
            "protected_processed": 0, "pending_after": 0, "last_dispatch_ms": 0.0,
            "max_dispatch_ms": 0.0, "received": 0, "coalesced": 0,
        }


def test_process_ui_queue_returns_under_progress_flood() -> None:
    harness = _Harness()
    controller = harness.controller
    for chunk in range(400):
        controller.ui_dispatcher.submit(
            _progress("RJ00000001", f"track-{chunk % 4}", chunk)
        )
    # A flood of control messages too.
    for _ in range(300):
        controller.ui_queue.put(("work_status", "RJ00000001", "Downloading"))
    # No page.run_task on the test double: re-scheduling must be tolerated.
    controller.page.run_task = lambda _coro: None

    asyncio.run(controller._process_ui_queue())

    # Control budget (256) capped the control drain; remaining stay queued for
    # the re-scheduled run. The method must have returned and released the flag.
    assert controller.ui_processing is False
    assert controller.ui_queue.qsize() == 300 - 256
    assert controller.ui_metrics["control_processed"] == 256
    assert controller.ui_metrics["progress_processed"] + \
        controller.ui_metrics["protected_processed"] > 0


def test_work_status_messages_are_consumed_before_progress() -> None:
    harness = _Harness()
    controller = harness.controller
    seen = []
    controller.views[0] = type(
        "View",
        (),
        {
            "update_work_status": lambda self, rj, st: seen.append(("status", st)),
            "update_track_progress": lambda self, ev: seen.append(("progress", ev.status)),
        },
    )()
    controller.ui_queue.put(("work_status", "RJ00000001", "Completed"))
    controller.ui_dispatcher.submit(_progress("RJ00000001", "a.mp3", 10))
    controller.page.run_task = lambda _coro: None

    asyncio.run(controller._process_ui_queue())

    assert seen[0] == ("status", "Completed")
