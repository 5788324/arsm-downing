import asyncio
import queue

from ui.app import AppController


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
