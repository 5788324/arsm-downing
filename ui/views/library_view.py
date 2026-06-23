import flet as ft
import os
import platform
import subprocess
from pathlib import Path

from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR


STATUS_LABELS = {
    "completed": ("已完成", SUCCESS),
    "partial": ("部分完成", WARNING),
    "missing": ("文件缺失", ERROR),
    None: ("", "grey"),
}


class LibraryView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True

        self.grid = ft.GridView(
            expand=1, runs_count=5, max_extent=200,
            child_aspect_ratio=0.8, spacing=10, run_spacing=10,
        )

        self.search_input = ft.TextField(
            hint_text="搜索库 (支持作品名或社团)...",
            border_radius=10, expand=True,
            on_change=self.on_search
        )

        self.content = ft.Column([
            ft.Text("您的资源库", size=32, weight=ft.FontWeight.BOLD),
            self.search_input,
            ft.Divider(color="transparent"),
            self.grid
        ])

    def load_library(self, query=""):
        self.grid.controls.clear()
        results = self.app_controller.db.search(query)

        for row in results:
            rj_id = row["rj_id"]
            title = row["title"]
            circle = row["circle"]
            local_path = row["local_path"]
            cover_url = (
                row["cover_url"] if "cover_url" in row.keys() else None)
            status = (
                row["status"] if "status" in row.keys() else "completed")

            label, color = STATUS_LABELS.get(
                status, STATUS_LABELS[None])

            image_control = (
                ft.Image(src=cover_url, width=150, height=150,
                         fit=ft.ImageFit.COVER, border_radius=10)
                if cover_url
                else ft.Icon(ft.icons.LIBRARY_MUSIC, size=100,
                             color=ACCENT_PRIMARY)
            )

            # Status badge
            status_row = ft.Row([ft.Text(rj_id, weight=ft.FontWeight.BOLD)])
            if label:
                status_row.controls.append(
                    ft.Container(
                        content=ft.Text(label, size=9, color="white"),
                        bgcolor=color, border_radius=4,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    )
                )

            card_content = ft.Column([
                image_control,
                status_row,
                ft.Text(title, size=12, max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(circle, size=10, color="grey", max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], alignment=ft.MainAxisAlignment.CENTER,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER)

            container = Styles.glass_container(card_content, padding=10)
            container.on_click = lambda e, p=local_path: self.open_folder(p)
            self.grid.controls.append(container)

        self.grid.update()

    def on_search(self, e):
        self.load_library(self.search_input.value)

    def open_folder(self, path_str):
        path = Path(path_str)
        if path.exists():
            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.run(["open", path])
                else:
                    subprocess.run(["xdg-open", path])
            except Exception:
                pass
