import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR
import time
import random

class DashboardView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True
        
        self.stats_grid = ft.Row(spacing=20, wrap=True)
        self.achievements_list = ft.ListView(expand=True, spacing=10)
        self.source_note = ft.Text("", size=10, color="grey")

        self.content = ft.Column([
            ft.Text("统计与成就", size=32, weight=ft.FontWeight.BOLD),
            self.source_note,
            ft.Text("数据概览", size=20, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            self.stats_grid,
            ft.Divider(height=20, color="transparent"),
            ft.Text("成就系统", size=20, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            self.achievements_list
        ], expand=True)

    def load_data(self):
        db = self.app_controller.db
        cnt, sz = db.get_summary()  # works table
        lib = db.get_library_summary()  # library_items table

        self.stats_grid.controls = [
            self._build_stat_card("作品总数", str(cnt), "📚", "(works 表)"),
            self._build_stat_card("总存储量", f"{sz/1024**3:.2f} GB", "💾", "(works 表)"),
            self._build_stat_card("已索引", str(lib.get("total_works", 0)), "📋", "(library_items)"),
            self._build_stat_card("索引文件", str(lib.get("total_files", 0)), "📁", "(library_items)"),
        ]
        self.source_note.value = "数据来源: works 表 (作品) + library_items 表 (资源库索引)"
        
        # Load achievements
        achievements_data = [
            {"id": "first_blood", "name": "初入坑", "desc": "下载您的第一部 ASMR 作品", "condition": lambda: cnt >= 1},
            {"id": "collector", "name": "收藏家", "desc": "累计下载超过 50 部作品", "condition": lambda: cnt >= 50},
            {"id": "master", "name": "仓鼠王", "desc": "累计下载超过 100 部作品", "condition": lambda: cnt >= 100},
            {"id": "organizer", "name": "整理狂", "desc": "开启自动分类功能", "condition": lambda: self.app_controller.config.sort_files},
        ]
        
        self.achievements_list.controls.clear()
        unlocked_list = self.app_controller.config.achievements
        
        new_unlocks = False
        for ach in achievements_data:
            is_unlocked = ach["id"] in unlocked_list
            if not is_unlocked and ach["condition"]():
                unlocked_list.append(ach["id"])
                is_unlocked = True
                new_unlocks = True
                self.app_controller.show_snack(f"🏆 达成新成就: {ach['name']}!")
            
            icon = "🔓" if is_unlocked else "🔒"
            color = SUCCESS if is_unlocked else "grey"
            
            card = ft.ListTile(
                leading=ft.Text(icon, size=24),
                title=ft.Text(ach["name"], color=color, weight=ft.FontWeight.BOLD),
                subtitle=ft.Text(ach["desc"], color="grey")
            )
            self.achievements_list.controls.append(Styles.glass_container(card, padding=10))
            
        if new_unlocks:
            self.app_controller.config.save()
            
        self.update()

    def _build_stat_card(self, title, value, icon, source="", width=150):
        col = ft.Column([
            ft.Text(icon, size=30),
            ft.Text(value, size=24, weight=ft.FontWeight.BOLD, color=SUCCESS),
            ft.Text(title, size=14, color="grey"),
            ft.Text(source, size=9, color="grey") if source else ft.Text(""),
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        return Styles.glass_container(col, padding=20, width=width)
