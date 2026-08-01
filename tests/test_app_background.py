import asyncio
import queue

from ui.app import AppController
from ui.app_base import AppController as BaseAppController


def test_run_blocking_marshals_result_to_ui_queue() -> None:
    controller = AppController.__new__(AppController)
    controller.ui_queue = queue.Queue()
    captured = []

    def submit(coroutine, _label):
        captured.append(coroutine)
        return coroutine

    controller._submit_background = submit
    callback = lambda result: result
    coroutine = controller.run_blocking(lambda: 42, callback, action_label="test")
    assert coroutine is captured[0]
    assert asyncio.run(coroutine) == 42
    message = controller.ui_queue.get_nowait()
    assert message == ("ui_callback", callback, 42)


class BatchFakeOrchestrator:
    def pause_all(self):
        return ["RJ00000001"]

    async def _resume_all_async(self):
        return {
            "resumed_to_queue": 1,
            "already_queued": 0,
            "already_running": 0,
            "no_pending": 0,
            "no_cache": 0,
            "cache_corrupt": 0,
            "failed": 0,
        }


def _make_batch_controller() -> AppController:
    controller = AppController.__new__(AppController)
    controller.orc = BatchFakeOrchestrator()
    controller.ui_queue = queue.Queue()
    controller._enqueue_snack = lambda _message: None
    controller._submit_background = lambda coroutine, _label: coroutine
    return controller


def test_pause_all_requests_one_database_queue_refresh() -> None:
    controller = _make_batch_controller()

    asyncio.run(controller.pause_all_downloads())

    message = controller.ui_queue.get_nowait()
    assert message[0] == "ui_callback"
    assert message[2] is None


def test_resume_all_requests_one_database_queue_refresh() -> None:
    controller = _make_batch_controller()

    asyncio.run(controller.resume_all_downloads())

    message = controller.ui_queue.get_nowait()
    assert message[0] == "ui_callback"
    assert message[2] is None


class _LifecycleView:
    def __init__(self):
        self.states = []

    def set_active(self, value):
        self.states.append(bool(value))


class _ViewContainer:
    def __init__(self):
        self.content = None
        self.updated = 0

    def update(self):
        self.updated += 1


class _NavEvent:
    def __init__(self, index):
        self.control = type("Control", (), {"selected_index": index})()


def test_navigation_deactivates_old_view_and_activates_new_view() -> None:
    controller = AppController.__new__(AppController)
    old = _LifecycleView()
    new = _LifecycleView()
    controller.views = {0: old, 1: new}
    controller.current_view = 0
    controller.views_container = _ViewContainer()

    controller.on_nav_change(_NavEvent(1))

    assert old.states == [False]
    assert new.states == [True]
    assert controller.current_view == 1
    assert controller.views_container.content is new

class _Window:
    def __init__(self) -> None:
        self.prevent_close = False
        self.destroyed = False
        self.closed = False

    def destroy(self) -> None:
        self.destroyed = True

    def close(self) -> None:
        self.closed = True


class _Page:
    def __init__(self) -> None:
        self.window = _Window()


def test_close_queue_uses_flet_027_window_api() -> None:
    controller = BaseAppController.__new__(BaseAppController)
    controller.page = _Page()
    controller.ui_queue = queue.Queue()
    controller.ui_processing = False
    controller._ui_poller_stop = type("Stop", (), {"set": lambda self: None})()
    controller.ui_queue.put(("close_window", None))

    asyncio.run(controller._process_ui_queue())

    assert controller.page.window.destroyed is True
    assert controller.page.window.closed is False