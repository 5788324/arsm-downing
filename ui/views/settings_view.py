import flet as ft
from pathlib import Path

from ui.theme import ACCENT_PRIMARY, ERROR


class SettingsView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True

        config = self.app_controller.config

        self.dir_input = ft.TextField(
            label="下载保存目录",
            value=str(config.output_dir),
            expand=True,
            tooltip="新下载文件会保存到这里。",
        )
        self.external_intake_root_input = ft.TextField(
            label="外部资源扫描目录",
            value=getattr(config, "external_intake_root", None) or "",
            expand=True,
            hint_text=r"例如 E:\arsm",
            tooltip="只读扫描此目录的直接子文件夹；留空时外部资源整理不可用。",
        )
        self.external_quarantine_root_input = ft.TextField(
            label="外部资源隔离目录",
            value=getattr(config, "external_quarantine_root", None) or "",
            expand=True,
            hint_text=r"例如 E:\arsm_quarantine_external",
            tooltip="必须位于扫描目录之外；当前仅用于计划校验，不会实际移动文件。",
        )
        self.metadata_proxy_input = ft.TextField(
            label="元数据代理",
            value=config.metadata_proxy or "",
            expand=True,
            hint_text="http://127.0.0.1:7897",
        )
        self.cover_proxy_input = ft.TextField(
            label="封面代理",
            value=config.cover_proxy or "",
            expand=True,
            hint_text="通常与元数据代理相同，可留空。",
        )
        self.download_proxy_input = ft.TextField(
            label="下载代理",
            value=config.download_proxy or "",
            expand=True,
            hint_text="留空表示直连。",
        )
        self.download_fallback_switch = ft.Switch(
            label="下载直连失败后回退到代理",
            value=getattr(config, "download_fallback_to_proxy", False),
        )
        self.work_concurrency_slider = ft.Slider(
            min=1, max=4, divisions=3,
            value=getattr(config, "work_concurrency", 1),
            label="{value}",
        )
        self.file_concurrency_slider = ft.Slider(
            min=1, max=16, divisions=15,
            value=getattr(config, "file_concurrency", 4),
            label="{value}",
        )
        self.tag_audio_switch = ft.Switch(
            label="自动写入音频标签",
            value=getattr(config, "tag_audio", False),
        )
        self.sort_files_switch = ft.Switch(
            label="按文件类型自动分类",
            value=getattr(config, "sort_files", False),
        )

        self.lib_paths = list(getattr(config, "library_paths", []) or [str(config.output_dir)])
        self.lib_path_list = ft.Column(spacing=6)
        self._refresh_lib_paths()

        save_btn = ft.ElevatedButton("保存设置", icon=ft.Icons.SAVE, on_click=self.on_save)

        self.content = ft.Column(
            [
                ft.Text("设置", size=28, weight=ft.FontWeight.BOLD),
                ft.Text("下载目录", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
                ft.Row([self.dir_input]),
                ft.Divider(height=8, color="transparent"),
                ft.Text("仓库目录", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
                ft.Text("这里可以添加已有资源目录，扫描资源库时会一起纳入。", size=12, color="white70"),
                self.lib_path_list,
                ft.Row([
                    ft.ElevatedButton("添加路径", icon=ft.Icons.ADD, on_click=self._add_lib_path),
                ]),
                ft.Divider(height=8, color="transparent"),
                ft.Text("外部资源整理", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
                ft.Text(
                    "该功能当前仅生成只读计划和报告，真实移动与数据库写入保持冻结。",
                    size=12,
                    color="white70",
                ),
                ft.Row([self.external_intake_root_input]),
                ft.Row([self.external_quarantine_root_input]),
                ft.Divider(height=8, color="transparent"),
                ft.Text("代理设置", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
                ft.Row([self.metadata_proxy_input]),
                ft.Row([self.cover_proxy_input]),
                ft.Row([self.download_proxy_input]),
                ft.Row([self.download_fallback_switch]),
                ft.Text("同时下载的作品数"),
                self.work_concurrency_slider,
                ft.Text("每个作品同时下载的文件数"),
                self.file_concurrency_slider,
                ft.Text(
                    "并发设置会在下次启动时完整生效；下载运行中不会重建工作线程。",
                    size=12, color="white70"),
                self.tag_audio_switch,
                self.sort_files_switch,
                ft.Divider(color="transparent"),
                save_btn,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _refresh_lib_paths(self):
        self.lib_path_list.controls.clear()
        for i, path in enumerate(self.lib_paths):
            path_input = ft.TextField(value=path, expand=True, dense=True)
            remove_btn = ft.IconButton(
                icon=ft.Icons.REMOVE,
                icon_color=ERROR,
                tooltip="移除",
                on_click=lambda e, idx=i: self._remove_lib_path(idx),
            )
            self.lib_path_list.controls.append(ft.Row([path_input, remove_btn], spacing=4))

    def _add_lib_path(self, e):
        self.lib_paths.append("")
        self._refresh_lib_paths()
        try:
            self.lib_path_list.update()
        except Exception:
            pass

    def _remove_lib_path(self, idx):
        if len(self.lib_paths) <= 1:
            self.app_controller.show_snack("至少保留一个仓库目录")
            return
        self.lib_paths.pop(idx)
        self._refresh_lib_paths()
        try:
            self.lib_path_list.update()
        except Exception:
            pass

    def on_save(self, e):
        config = self.app_controller.config
        output_value = self.dir_input.value.strip()
        if not output_value:
            self.app_controller.show_snack("下载保存目录不能为空")
            return
        config.output_dir = Path(output_value).expanduser()

        metadata_proxy = self.metadata_proxy_input.value.strip()
        cover_proxy = self.cover_proxy_input.value.strip()
        download_proxy = self.download_proxy_input.value.strip()

        external_intake_root = self.external_intake_root_input.value.strip()
        external_quarantine_root = self.external_quarantine_root_input.value.strip()
        for label, value in (
            ("外部资源扫描目录", external_intake_root),
            ("外部资源隔离目录", external_quarantine_root),
        ):
            if value and not Path(value).is_absolute():
                self.app_controller.show_snack(f"{label}必须使用绝对路径")
                return
        if external_intake_root and external_quarantine_root:
            root_path = Path(external_intake_root).resolve(strict=False)
            quarantine_path = Path(external_quarantine_root).resolve(strict=False)
            try:
                quarantine_path.relative_to(root_path)
                self.app_controller.show_snack("隔离目录必须位于扫描目录之外")
                return
            except ValueError:
                pass
            if root_path == quarantine_path:
                self.app_controller.show_snack("扫描目录和隔离目录不能相同")
                return

        config.external_intake_root = external_intake_root or None
        config.external_quarantine_root = external_quarantine_root or None

        config.metadata_proxy = metadata_proxy or None
        config.cover_proxy = cover_proxy or None
        config.download_proxy = download_proxy or None
        config.download_fallback_to_proxy = self.download_fallback_switch.value
        config.proxy = config.metadata_proxy
        config.work_concurrency = int(self.work_concurrency_slider.value)
        config.file_concurrency = int(self.file_concurrency_slider.value)
        config.max_concurrent = config.file_concurrency  # legacy compatibility
        config.tag_audio = self.tag_audio_switch.value
        config.sort_files = self.sort_files_switch.value

        new_paths = []
        for row in self.lib_path_list.controls:
            value = row.controls[0].value.strip()
            if value:
                new_paths.append(value)
        config.library_paths = new_paths if new_paths else [str(config.output_dir)]
        try:
            config.save()
        except OSError as exc:
            self.app_controller.show_snack(f"设置保存失败: {exc}")
            return

        self.app_controller.show_snack("设置已保存")
