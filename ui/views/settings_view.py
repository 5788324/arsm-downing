import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY

class SettingsView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True
        
        config = self.app_controller.config
        
        self.dir_input = ft.TextField(label="下载保存目录", value=str(config.output_dir), expand=True)
        self.proxy_input = ft.TextField(label="代理服务器 (如 http://127.0.0.1:7890，留空直连)", value=config.proxy or "", expand=True)
        self.concurrent_slider = ft.Slider(min=1, max=10, divisions=9, value=config.max_concurrent, label="{value}")
        self.proxy_download_switch = ft.Switch(label="下载音频时也使用代理 (默认关闭，省流量)", value=getattr(config, 'proxy_download', False))
        self.tag_audio_switch = ft.Switch(label="自动写入音频标签 (MP3/FLAC/OGG)", value=config.tag_audio)
        self.sort_files_switch = ft.Switch(label="按文件类型自动分类", value=config.sort_files)
        
        save_btn = ft.ElevatedButton("保存设置", icon=ft.icons.SAVE, on_click=self.on_save)
        
        form = ft.Column([
            ft.Text("通用设置", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([self.dir_input]),
            ft.Row([self.proxy_input]),
            ft.Text("最大并发下载数"),
            self.concurrent_slider,
            self.proxy_download_switch,
            self.tag_audio_switch,
            self.sort_files_switch,
            ft.Divider(color="transparent"),
            save_btn
        ])
        
        self.content = ft.Column([
            ft.Text("设置", size=32, weight=ft.FontWeight.BOLD),
            Styles.glass_container(form)
        ])

    def on_save(self, e):
        config = self.app_controller.config
        from pathlib import Path
        config.output_dir = Path(self.dir_input.value)
        config.proxy = self.proxy_input.value.strip() if self.proxy_input.value.strip() else None
        config.max_concurrent = int(self.concurrent_slider.value)
        config.proxy_download = self.proxy_download_switch.value
        config.tag_audio = self.tag_audio_switch.value
        config.sort_files = self.sort_files_switch.value
        config.save()
        
        # Optional: show snackbar
        self.page.snack_bar = ft.SnackBar(ft.Text("Settings saved successfully!"))
        self.page.snack_bar.open = True
        self.page.update()
