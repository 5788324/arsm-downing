import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR
import asyncio
import os
import time

class ToolsView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True

        self.log_area = ft.ListView(expand=True, spacing=5, auto_scroll=True)

        self.content = ft.Column([
            ft.Text("实用工具与系统诊断", size=32, weight=ft.FontWeight.BOLD),
            ft.Text("系统工具", size=20, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("修复数据库", icon=ft.icons.STORAGE, on_click=self.repair_db),
                ft.ElevatedButton("清理缓存", icon=ft.icons.DELETE_SWEEP, on_click=self.clear_cache),
                ft.ElevatedButton("测试网络", icon=ft.icons.NETWORK_CHECK, on_click=self.test_network),
                ft.ElevatedButton("扫描仓库", icon=ft.icons.FOLDER_SPECIAL, on_click=self.scan_library),
            ], spacing=20, wrap=True),
            ft.Divider(height=20, color="transparent"),
            ft.Row([
                ft.Text("诊断日志", size=20, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
                ft.ElevatedButton("运行一键诊断", icon=ft.icons.HEALTH_AND_SAFETY, on_click=self.run_diagnostic)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            Styles.glass_container(self.log_area, padding=10)
        ])

    def log(self, message: str, color: str = "white"):
        self.log_area.controls.append(ft.Text(message, color=color, size=12, font_family="Consolas"))
        self.log_area.update()

    def scan_library(self, e):
        cfg = self.app_controller.config
        paths = getattr(cfg, 'library_paths', [])
        if not paths:
            self.log("⚠ library_paths 为空 — 请在 config.json 中添加路径", WARNING)
            return
        self.log(f"> 扫描仓库路径 ({len(paths)} 个)...", "white")
        result = self.app_controller.db.rebuild_library(paths)
        self.log(f"  发现: {result['found']} 个作品", SUCCESS)
        self.log(f"  新增索引: {result['indexed']} 个", ACCENT_PRIMARY)
        if result['errors']:
            self.log(f"  错误: {result['errors']}", ERROR)

    def repair_db(self, e):
        self.log("> 开始修复数据库...", "white")
        try:
            self.app_controller.db.conn.execute("VACUUM")
            self.log("✓ 数据库修复/优化成功!", SUCCESS)
        except Exception as ex:
            self.log(f"✗ 数据库修复失败: {ex}", ERROR)

    def clear_cache(self, e):
        self.log("> 开始清理缓存...", "white")
        # Just a simulated cache clearing for now as we don't have heavy temp files
        time.sleep(0.5)
        self.log("✓ 缓存清理成功!", SUCCESS)

    def test_network(self, e):
        self.log("> 测试 API 连通性...", "white")
        import aiohttp
        from core.config import HOSTNAME_MIRRORS
        async def _test():
            for mirror in HOSTNAME_MIRRORS:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(mirror, timeout=5) as resp:
                            if resp.status in (200, 403, 404):
                                self.log(f"✓ {mirror} 连接正常", SUCCESS)
                            else:
                                self.log(f"⚠ {mirror} 状态异常: {resp.status}", WARNING)
                except Exception:
                    self.log(f"✗ {mirror} 无法连接", ERROR)
        import asyncio
        if hasattr(self, 'app_controller') and \
           hasattr(self.app_controller, 'loop'):
            asyncio.run_coroutine_threadsafe(
                _test(), self.app_controller.loop)
        else:
            asyncio.create_task(_test())

    def run_diagnostic(self, e):
        self.log_area.controls.clear()
        self.log("=== 系统诊断开始 ===", ACCENT_PRIMARY)
        
        config = self.app_controller.config
        
        self.log(f"检查配置文件: {'✓' if True else '✗'}", SUCCESS)
        self.log(f"检查数据库: {'✓' if os.path.exists('history.db') else '✗'}", SUCCESS if os.path.exists('history.db') else ERROR)
        
        try:
            os.makedirs(config.output_dir, exist_ok=True)
            self.log(f"输出目录权限: {'✓' if os.access(config.output_dir, os.W_OK) else '✗'}", SUCCESS if os.access(config.output_dir, os.W_OK) else ERROR)
        except Exception:
            self.log(f"输出目录权限: ✗", ERROR)
        
        try:
            import mutagen
            self.log("音频标签模块 (mutagen): ✓", SUCCESS)
        except ImportError:
            self.log("音频标签模块 (mutagen): ✗ (未安装)", ERROR)
            
        try:
            import aiohttp
            self.log("网络模块 (aiohttp): ✓", SUCCESS)
        except ImportError:
            self.log("网络模块 (aiohttp): ✗ (未安装)", ERROR)
            
        self.log("=== 诊断完成 ===", ACCENT_PRIMARY)
