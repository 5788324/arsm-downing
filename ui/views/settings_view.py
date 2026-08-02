import flet as ft
from pathlib import Path

from ui.theme import ACCENT_PRIMARY, ERROR
from core.settings_validation import (
    normalize_library_paths, validate_proxy_uri,
    validate_writable_directory,
)


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
        self.cover_fallback_switch = ft.Switch(
            label="封面代理失败时允许直连回退",
            value=getattr(config, "cover_fallback_to_direct", False),
            tooltip="默认关闭；开启后仅封面请求可进行一次受控直连回退。",
        )
        self.work_concurrency_slider = ft.Slider(
            min=1, max=4, divisions=3,
            value=getattr(config, "work_concurrency", 1),
            label="{value}",
        )
        self.metadata_concurrency_slider = ft.Slider(
            min=1, max=8, divisions=7,
            value=getattr(config, "metadata_concurrency", 2),
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
                ft.Row([self.cover_fallback_switch]),
                ft.Text("同时下载的作品数"),
                self.work_concurrency_slider,
                ft.Text("同时准备元数据的作品数"),
                self.metadata_concurrency_slider,
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

        self._active = False

    def set_active(self, active: bool) -> None:
        self._active = bool(active)

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
        del e
        config = self.app_controller.config
        attrs = (
            "output_dir", "library_paths", "external_intake_root",
            "external_quarantine_root", "metadata_proxy", "cover_proxy",
            "download_proxy", "cover_fallback_to_direct",
            "download_fallback_to_proxy", "proxy", "work_concurrency",
            "metadata_concurrency", "file_concurrency", "max_concurrent",
            "tag_audio", "sort_files",
        )
        previous = {name: getattr(config, name, None) for name in attrs}
        download_view = getattr(self.app_controller, "views", {}).get(0)
        service = getattr(download_view, "download_service", None)
        service_previous = (
            getattr(service, "output_dir", None),
            getattr(service, "library_paths", ()),
        ) if service is not None else None
        created_output_dir = None
        try:
            raw_output = str(self.dir_input.value or "").strip()
            if not raw_output:
                raise ValueError("下载保存目录不能为空")
            output_candidate = Path(raw_output).expanduser().resolve(strict=False)
            output_existed = output_candidate.exists()
            if output_existed and not output_candidate.is_dir():
                raise ValueError(f"路径不是目录: {output_candidate}")

            # Complete all pure validation before creating a new output directory.
            metadata_proxy = validate_proxy_uri(self.metadata_proxy_input.value)
            cover_proxy = validate_proxy_uri(self.cover_proxy_input.value)
            download_proxy = validate_proxy_uri(self.download_proxy_input.value)

            external_intake_root = self.external_intake_root_input.value.strip()
            external_quarantine_root = self.external_quarantine_root_input.value.strip()
            for label, value in (
                ("外部资源扫描目录", external_intake_root),
                ("外部资源隔离目录", external_quarantine_root),
            ):
                if value and not Path(value).is_absolute():
                    raise ValueError(f"{label}必须使用绝对路径")
            if external_intake_root and external_quarantine_root:
                root_path = Path(external_intake_root).resolve(strict=False)
                quarantine_path = Path(external_quarantine_root).resolve(strict=False)
                if root_path == quarantine_path:
                    raise ValueError("扫描目录和隔离目录不能相同")
                try:
                    quarantine_path.relative_to(root_path)
                except ValueError:
                    pass
                else:
                    raise ValueError("隔离目录必须位于扫描目录之外")

            raw_library_paths = [
                row.controls[0].value for row in self.lib_path_list.controls
                if getattr(row, "controls", None)
            ]
            library_paths = normalize_library_paths(raw_library_paths)
            output_dir = validate_writable_directory(raw_output)
            if not output_existed:
                created_output_dir = output_dir
            if not library_paths:
                library_paths = [str(output_dir)]

            config.output_dir = output_dir
            config.library_paths = library_paths
            config.external_intake_root = external_intake_root or None
            config.external_quarantine_root = external_quarantine_root or None
            config.metadata_proxy = metadata_proxy
            config.cover_proxy = cover_proxy
            config.download_proxy = download_proxy
            config.cover_fallback_to_direct = bool(self.cover_fallback_switch.value)
            config.download_fallback_to_proxy = bool(self.download_fallback_switch.value)
            config.proxy = metadata_proxy
            config.work_concurrency = int(self.work_concurrency_slider.value)
            config.metadata_concurrency = int(self.metadata_concurrency_slider.value)
            config.file_concurrency = int(self.file_concurrency_slider.value)
            config.max_concurrent = config.file_concurrency
            config.tag_audio = bool(self.tag_audio_switch.value)
            config.sort_files = bool(self.sort_files_switch.value)
            config.save()

            # The service is read-only, but it snapshots paths for duplicate scans.
            # Refresh those snapshots immediately; existing active targets stay fixed.
            if service is not None:
                service.output_dir = Path(config.output_dir)
                service.library_paths = tuple(Path(value) for value in config.library_paths)
            self.app_controller.show_snack(
                "设置已保存；路径与代理对后续任务生效，并发线程数重启后完整生效"
            )
        except Exception as exc:
            for name, value in previous.items():
                setattr(config, name, value)
            if service is not None and service_previous is not None:
                service.output_dir, service.library_paths = service_previous
            # If persistence succeeded but a later runtime update failed, restore the
            # previous durable file as well.  A second failure is reported but never
            # hidden behind a false success toast.
            try:
                config.save()
            except Exception:
                pass
            if created_output_dir is not None:
                try:
                    created_output_dir.rmdir()
                except OSError:
                    pass
            self.app_controller.show_snack(f"设置未保存: {exc}")
