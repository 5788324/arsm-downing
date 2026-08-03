import multiprocessing
import sys


if __name__ == "__main__":
    if "--shutdown" in sys.argv:
        from core.shutdown_signal import request_shutdown
        raise SystemExit(0 if request_shutdown() else 1)

    import flet as ft
    from ui.app import start_app

    multiprocessing.freeze_support()
    ft.app(target=start_app)
