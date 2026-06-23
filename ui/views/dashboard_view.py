import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR
import time
import random

class DashboardView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True
        
        self.stats_grid = ft.Row(spacing=20)
        self.achievements_list = ft.ListView(expand=True, spacing=10)
        
        self.content = ft.Column([
            ft.Text("统计与成就", size=32, weight=ft.FontWeight.BOLD),
            ft.Text("数据概览", size=20, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            self.stats_grid,
            ft.Divider(height=20, color="transparent"),
            ft.Text("成就系统", size=20, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            self.achievements_list
        ])

    def load_data(self):
        # Load statistics
        cnt, sz = self.app_controller.db.get_summary()
        
        self.stats_grid.controls = [
            self._build_stat_card("总下载数", str(cnt), "📈"),
            self._build_stat_card("总存储量", f"{sz/1024**3:.2f} GB", "💾"),
        ]
        
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

    def _build_stat_card(self, title, value, icon):
        col = ft.Column([
            ft.Text(icon, size=30),
            ft.Text(value, size=24, weight=ft.FontWeight.BOLD, color=SUCCESS),
            ft.Text(title, size=14, color="grey")
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        
        return Styles.glass_container(col, padding=20, width=150)
