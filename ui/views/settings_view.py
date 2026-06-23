import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY


class SettingsView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True

        config = self.app_controller.config

        self.dir_input = ft.TextField(
            label="下载保存目录", value=str(config.output_dir), expand=True)
        self.metadata_proxy_input = ft.TextField(
            label="元数据代理 (metadata_proxy, 如 http://127.0.0.1:7890)",
            value=config.metadata_proxy or "", expand=True)
        self.cover_proxy_input = ft.TextField(
            label="封面代理 (cover_proxy, 同元数据代理或留空)",
            value=config.cover_proxy or "", expand=True)
        self.download_proxy_input = ft.TextField(
            label="下载代理 (download_proxy, 默认留空走直连)",
            value=config.download_proxy or "", expand=True)
        self.concurrent_slider = ft.Slider(
            min=1, max=10, divisions=9,
            value=config.max_concurrent, label="{value}")
        self.tag_audio_switch = ft.Switch(
            label="自动写入音频标签 (MP3/FLAC/OGG)",
            value=config.tag_audio)
        self.sort_files_switch = ft.Switch(
            label="按文件类型自动分类", value=config.sort_files)

        save_btn = ft.ElevatedButton(
            "保存设置", icon=ft.icons.SAVE, on_click=self.on_save)

        form = ft.Column([
            ft.Text("通用设置", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([self.dir_input]),
            ft.Divider(height=10, color="transparent"),
            ft.Text("代理设置", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([self.metadata_proxy_input]),
            ft.Row([self.cover_proxy_input]),
            ft.Row([self.download_proxy_input]),
            ft.Text("最大并发下载数"),
            self.concurrent_slider,
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
        mp = self.metadata_proxy_input.value.strip()
        config.metadata_proxy = mp if mp else None
        cp = self.cover_proxy_input.value.strip()
        config.cover_proxy = cp if cp else None
        dp = self.download_proxy_input.value.strip()
        config.download_proxy = dp if dp else None
        # Legacy compat
        config.proxy = config.metadata_proxy
        config.max_concurrent = int(self.concurrent_slider.value)
        config.tag_audio = self.tag_audio_switch.value
        config.sort_files = self.sort_files_switch.value
        config.save()

        self.page.snack_bar = ft.SnackBar(
            ft.Text("设置已保存"))
        self.page.snack_bar.open = True
        self.page.update()
