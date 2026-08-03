"""Windows-only cooperative shutdown signal for the installed desktop app."""
from __future__ import annotations

import ctypes
import os
import threading
from collections.abc import Callable

_SHUTDOWN_EVENT = r"Local\ARSM-Suite-Shutdown"
_STOPPED_EVENT = r"Local\ARSM-Suite-Stopped"
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateEventW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_bool,
        ctypes.c_bool,
        ctypes.c_wchar_p,
    )
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.OpenEventW.argtypes = (ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.SetEvent.argtypes = (ctypes.c_void_p,)
    kernel32.SetEvent.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    return kernel32


class ShutdownSignal:
    """Receive one cooperative shutdown request while the UI is running."""

    def __init__(self, on_shutdown: Callable[[], None]) -> None:
        self._on_shutdown = on_shutdown
        self._stop = threading.Event()
        self._shutdown_handle: int | None = None
        self._stopped_handle: int | None = None
        self._thread: threading.Thread | None = None
        self._kernel32 = None

    @property
    def available(self) -> bool:
        return self._shutdown_handle is not None and self._stopped_handle is not None

    def start(self) -> bool:
        if os.name != "nt":
            return False
        kernel32 = _kernel32()
        shutdown = kernel32.CreateEventW(None, False, False, _SHUTDOWN_EVENT)
        stopped = kernel32.CreateEventW(None, True, False, _STOPPED_EVENT)
        if not shutdown or not stopped:
            if shutdown:
                kernel32.CloseHandle(shutdown)
            if stopped:
                kernel32.CloseHandle(stopped)
            return False
        self._kernel32 = kernel32
        self._shutdown_handle = shutdown
        self._stopped_handle = stopped
        self._thread = threading.Thread(
            target=self._listen, name="arsm-shutdown-signal", daemon=True
        )
        self._thread.start()
        return True

    def _listen(self) -> None:
        assert self._kernel32 is not None and self._shutdown_handle is not None
        while not self._stop.is_set():
            result = self._kernel32.WaitForSingleObject(self._shutdown_handle, 250)
            if result == _WAIT_OBJECT_0 and not self._stop.is_set():
                self._on_shutdown()

    def mark_stopped(self) -> None:
        if self._kernel32 is not None and self._stopped_handle is not None:
            self._kernel32.SetEvent(self._stopped_handle)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._kernel32 is not None:
            for handle in (self._shutdown_handle, self._stopped_handle):
                if handle is not None:
                    self._kernel32.CloseHandle(handle)
        self._shutdown_handle = None
        self._stopped_handle = None


def request_shutdown(timeout_ms: int = 20_000) -> bool:
    if os.name != "nt":
        return False
    kernel32 = _kernel32()
    shutdown = kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, _SHUTDOWN_EVENT)
    if not shutdown:
        return False
    stopped = kernel32.OpenEventW(_SYNCHRONIZE, False, _STOPPED_EVENT)
    try:
        if not kernel32.SetEvent(shutdown) or not stopped:
            return False
        return kernel32.WaitForSingleObject(stopped, timeout_ms) == _WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(shutdown)
        if stopped:
            kernel32.CloseHandle(stopped)