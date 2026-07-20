import multiprocessing

import flet as ft

from ui.app import start_app


if __name__ == "__main__":
    multiprocessing.freeze_support()
    ft.app(target=start_app)
