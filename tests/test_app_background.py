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
