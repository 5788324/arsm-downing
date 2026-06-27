import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY


class SettingsView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True

        config = self.app_controller.config

        self.dir_input = ft.TextField(label="下载保存目录", value=str(config.output_dir), expand=True,
            tooltip="新下载文件输出到此目录")
        self.metadata_proxy_input = ft.TextField(
            label="元数据代理", value=config.metadata_proxy or "", expand=True,
            hint_text="http://127.0.0.1:7897")
        self.cover_proxy_input = ft.TextField(
            label="封面代理", value=config.cover_proxy or "", expand=True,
            hint_text="同元数据代理或留空")
        self.download_proxy_input = ft.TextField(
            label="下载代理", value=config.download_proxy or "", expand=True,
            hint_text="留空=直连，填代理会大量消耗流量")
        self.download_fallback_switch = ft.Switch(
            label="下载直连失败后回退到代理", value=config.download_fallback_to_proxy)
        self.concurrent_slider = ft.Slider(min=1, max=10, divisions=9,
            value=config.max_concurrent, label="{value}")
        self.tag_audio_switch = ft.Switch(label="自动写入音频标签", value=config.tag_audio)
        self.sort_files_switch = ft.Switch(label="按文件类型自动分类", value=config.sort_files)

        # Library paths editor
        self.lib_paths = getattr(config, 'library_paths', []) or [str(config.output_dir)]
        self.lib_path_list = ft.Column(spacing=4)
        self._refresh_lib_paths()

        save_btn = ft.ElevatedButton("保存设置", icon=ft.icons.SAVE, on_click=self.on_save)

        self.content = ft.Column([
            ft.Text("设置", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("下载目录", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([self.dir_input]),
            ft.Divider(height=8, color="transparent"),
            ft.Text("仓库目录 (扫描已有资源库)", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            self.lib_path_list,
            ft.Row([
                ft.ElevatedButton("添加路径", icon=ft.icons.ADD, on_click=self._add_lib_path),
            ]),
            ft.Divider(height=8, color="transparent"),
            ft.Text("代理设置", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([self.metadata_proxy_input]),
            ft.Row([self.cover_proxy_input]),
            ft.Row([self.download_proxy_input]),
            ft.Row([self.download_fallback_switch]),
            ft.Text("最大并发下载数"),
            self.concurrent_slider,
            self.tag_audio_switch,
            self.sort_files_switch,
            ft.Divider(color="transparent"),
            save_btn,
        ], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

    def _refresh_lib_paths(self):
        self.lib_path_list.controls.clear()
        for i, p in enumerate(self.lib_paths):
            tf = ft.TextField(value=p, expand=True, dense=True)
            rm_btn = ft.IconButton(icon=ft.icons.REMOVE, icon_color=ERROR, tooltip="移除",
                on_click=lambda e, idx=i: self._remove_lib_path(idx))
            self.lib_path_list.controls.append(ft.Row([tf, rm_btn], spacing=4))

    def _add_lib_path(self, e):
        self.lib_paths.append("")
        self._refresh_lib_paths()
        try: self.lib_path_list.update()
        except: pass

    def _remove_lib_path(self, idx):
        if len(self.lib_paths) <= 1:
            self.app_controller.show_snack("至少保留一个仓库目录")
            return
        self.lib_paths.pop(idx)
        self._refresh_lib_paths()
        try: self.lib_path_list.update()
        except: pass

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
        config.download_fallback_to_proxy = self.download_fallback_switch.value
        config.proxy = config.metadata_proxy
        config.max_concurrent = int(self.concurrent_slider.value)
        config.tag_audio = self.tag_audio_switch.value
        config.sort_files = self.sort_files_switch.value

        # Save library paths from UI
        new_paths = []
        for row in self.lib_path_list.controls:
            tf = row.controls[0]
            v = tf.value.strip()
            if v:
                new_paths.append(v)
        config.library_paths = new_paths if new_paths else [str(config.output_dir)]
        config.save()

        self.app_controller.show_snack("设置已保存")
