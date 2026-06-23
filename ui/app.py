import flet as ft
from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel
from core.orchestrator import Orchestrator
from ui.theme import PremiumTheme, BG_DARK, BG_SURFACE
from ui.views.download_view import DownloadView
from ui.views.library_view import LibraryView
from ui.views.settings_view import SettingsView
from ui.views.dashboard_view import DashboardView
from ui.views.tools_view import ToolsView
import asyncio

class AppController:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "EchoVault Premium"
        self.page.theme = PremiumTheme.get_theme()
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = BG_DARK
        self.page.padding = 0
        
        # Initialize Core Backend
        self.config = ConfigManager.load()
        self.db = LibraryVault()
        self.kernel = NetworkKernel(self.config)
        self.orc = Orchestrator(self.kernel, self.config, self.db)
        
        self.loop = asyncio.new_event_loop()
        import threading
        threading.Thread(target=self._run_loop, daemon=True).start()
        
        # Initialize Views
        self.views = {
            0: DownloadView(self),
            1: LibraryView(self),
            2: DashboardView(self),
            3: ToolsView(self),
            4: SettingsView(self)
        }
        self.current_view = 0
        
        # Callbacks
        self.orc.set_callbacks(
            on_progress=self.on_download_progress,
            on_work_status=self.on_work_status
        )
        
        self.setup_ui()
        asyncio.run_coroutine_threadsafe(self.orc.boot_worker(), self.loop)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def setup_ui(self):
        self.nav_rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=100,
            min_extended_width=200,
            group_alignment=-0.9,
            bgcolor=BG_SURFACE,
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.icons.CLOUD_DOWNLOAD_OUTLINED,
                    selected_icon=ft.icons.CLOUD_DOWNLOAD,
                    label="下载中心"
                ),
                ft.NavigationRailDestination(
                    icon=ft.icons.LIBRARY_MUSIC_OUTLINED,
                    selected_icon=ft.icons.LIBRARY_MUSIC,
                    label="资源库"
                ),
                ft.NavigationRailDestination(
                    icon=ft.icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.icons.DASHBOARD,
                    label="统计与成就"
                ),
                ft.NavigationRailDestination(
                    icon=ft.icons.HANDYMAN_OUTLINED,
                    selected_icon=ft.icons.HANDYMAN,
                    label="系统工具"
                ),
                ft.NavigationRailDestination(
                    icon=ft.icons.SETTINGS_OUTLINED,
                    selected_icon=ft.icons.SETTINGS,
                    label="设置"
                ),
            ],
            on_change=self.on_nav_change,
        )
        
        self.views_container = ft.Container(
            content=self.views[0],
            expand=True,
            padding=40
        )
        
        self.page.add(
            ft.Row(
                [
                    self.nav_rail,
                    ft.VerticalDivider(width=1),
                    self.views_container
                ],
                expand=True,
            )
        )

    def on_nav_change(self, e):
        idx = e.control.selected_index
        if idx in self.views:
            self.views_container.content = self.views[idx]
            self.views_container.update()
            
            if idx == 1:
                self.views[1].load_library()
            elif idx == 2:
                self.views[2].load_data()

    def start_download(self, rj_id: str):
        try:
            asyncio.run_coroutine_threadsafe(self.orc.queue_job(rj_id), self.loop)
        except Exception as e:
            self.page.run_task(lambda: self.show_snack(f"Failed to queue download: {str(e)}"))

    def on_download_progress(self, rj_id: str, track_id: str, downloaded: int, total: int, status: str):
        self.views[0].update_track_progress(rj_id, track_id, downloaded, total, status)

    def on_work_status(self, rj_id: str, status: str):
        self.views[0].update_work_status(rj_id, status)
        
    def pause_download(self, rj_id: str):
        self.orc.pause_job(rj_id)
        
    def cancel_download(self, rj_id: str):
        self.orc.cancel_job(rj_id)
        
    def show_snack(self, message: str):
        self.page.snack_bar = ft.SnackBar(ft.Text(message))
        self.page.snack_bar.open = True
        self.page.update()
        
    def check_achievements(self):
        if 2 in self.views:
            self.views[2].load_data()

def start_app(page: ft.Page):
    AppController(page)
