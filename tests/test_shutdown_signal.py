import os
import threading

import pytest

from core import shutdown_signal


def test_shutdown_signal_is_a_safe_noop_off_windows(monkeypatch):
    monkeypatch.setattr(shutdown_signal.os, "name", "posix")
    signal = shutdown_signal.ShutdownSignal(lambda: None)

    assert signal.start() is False
    assert signal.available is False
    assert shutdown_signal.request_shutdown() is False


@pytest.mark.skipif(os.name != "nt", reason="Windows named-event integration")
def test_shutdown_signal_round_trip_on_windows():
    delivered = threading.Event()
    receiver: shutdown_signal.ShutdownSignal

    def on_shutdown() -> None:
        delivered.set()
        receiver.mark_stopped()

    receiver = shutdown_signal.ShutdownSignal(on_shutdown)
    assert receiver.start() is True
    try:
        assert shutdown_signal.request_shutdown(timeout_ms=3_000) is True
        assert delivered.wait(1)
    finally:
        receiver.close()