import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS


class DashboardView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True

        self.stats_grid = ft.Row(spacing=20, wrap=True)
        self.achievements_list = ft.ListView(expand=True, spacing=10)
        self.source_note = ft.Text("", size=11, color="grey")

        self.content = ft.Column([
            ft.Text("\u7edf\u8ba1\u4e0e\u6210\u5c31", size=32, weight=ft.FontWeight.BOLD),
            self.source_note,
            ft.Text("\u6570\u636e\u6982\u89c8", size=20, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            self.stats_grid,
            ft.Divider(height=20, color="transparent"),
            ft.Text("\u6210\u5c31\u7cfb\u7edf", size=20, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            self.achievements_list,
        ], expand=True, spacing=12, scroll=ft.ScrollMode.AUTO)

    def load_data(self):
        db = self.app_controller.db
        works_count, works_size = db.get_summary()
        lib = db.get_library_summary()
        lib_count = lib.get("total_works", 0)
        lib_files = lib.get("total_files", 0)
        lib_size = lib.get("total_size", 0)

        self.stats_grid.controls = [
            self._build_stat_card("\u4f5c\u54c1\u603b\u6570", str(works_count), "#", "works"),
            self._build_stat_card("\u4f5c\u54c1\u5bb9\u91cf", f"{works_size / 1024 ** 3:.2f} GB", "GB", "works"),
            self._build_stat_card("\u8d44\u6e90\u5e93\u7d22\u5f15", str(lib_count), "IDX", "library_items"),
            self._build_stat_card("\u7d22\u5f15\u6587\u4ef6\u6570", str(lib_files), "FILE", "library_items"),
            self._build_stat_card("\u7d22\u5f15\u5bb9\u91cf", f"{lib_size / 1024 ** 3:.2f} GB", "SUM", "library_items"),
        ]
        diff = works_count - lib_count
        self.source_note.value = (
            f"\u6570\u636e\u6765\u6e90\uff1aworks={works_count}\uff0clibrary_items={lib_count}\uff0c\u5dee\u503c={diff}\u3002"
            "\u5982\u679c\u4e24\u8005\u4e0d\u4e00\u81f4\uff0c\u8bf7\u5148\u6267\u884c\u8d44\u6e90\u5e93\u91cd\u5efa\u3002"
        )

        achievements_data = [
            {"id": "first_blood", "name": "\u521d\u5165\u4ed3\u5e93", "desc": "\u81f3\u5c11\u6709 1 \u4e2a\u4f5c\u54c1", "condition": lambda: works_count >= 1},
            {"id": "collector", "name": "\u6536\u85cf\u5bb6", "desc": "\u4f5c\u54c1\u6570\u8d85\u8fc7 50", "condition": lambda: works_count >= 50},
            {"id": "master", "name": "\u4ed3\u5e93\u7ba1\u7406\u5458", "desc": "\u4f5c\u54c1\u6570\u8d85\u8fc7 100", "condition": lambda: works_count >= 100},
            {"id": "organizer", "name": "\u6574\u7406\u63a7", "desc": "\u542f\u7528\u81ea\u52a8\u5206\u7c7b\u529f\u80fd", "condition": lambda: self.app_controller.config.sort_files},
        ]

        self.achievements_list.controls.clear()
        unlocked = self.app_controller.config.achievements
        changed = False
        for ach in achievements_data:
            is_unlocked = ach["id"] in unlocked
            if not is_unlocked and ach["condition"]():
                unlocked.append(ach["id"])
                is_unlocked = True
                changed = True
                self.app_controller.show_snack(f"\u8fbe\u6210\u65b0\u6210\u5c31\uff1a{ach['name']}")
            icon = "OK" if is_unlocked else "--"
            color = SUCCESS if is_unlocked else "grey"
            card = ft.ListTile(
                leading=ft.Text(icon, size=18, color=color),
                title=ft.Text(ach["name"], color=color, weight=ft.FontWeight.BOLD),
                subtitle=ft.Text(ach["desc"], color="grey"),
            )
            self.achievements_list.controls.append(Styles.glass_container(card, padding=10))
        if changed:
            self.app_controller.config.save()
        self.update()

    def _build_stat_card(self, title, value, icon, source="", width=170):
        col = ft.Column([
            ft.Text(icon, size=24),
            ft.Text(value, size=24, weight=ft.FontWeight.BOLD, color=SUCCESS),
            ft.Text(title, size=14, color="grey"),
            ft.Text(source, size=9, color="grey") if source else ft.Text(""),
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        return Styles.glass_container(col, padding=20, width=width)
