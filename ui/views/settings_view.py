import os
import secrets
import webbrowser
import flet as ft
from pathlib import Path

from ui.theme import ACCENT_PRIMARY, ERROR, SUCCESS, WARNING
from core.browser_bridge import (
    BROWSER_BRIDGE_PORT as DEFAULT_PORT,
    BROWSER_EXTENSION_ID as EXTENSION_ID,
)
from core.paths import resource_path
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
        self.browser_bridge_switch = ft.Switch(
            label="允许浏览器扩展连接到 ARSM",
            value=bool(getattr(config, "browser_bridge_enabled", False)),
            tooltip="只监听本机 127.0.0.1，不向网页暴露文件路径。",
        )
        self.browser_bridge_status = ft.Text("正在读取连接状态…", size=12)
        self.browser_token_input = ft.TextField(
            label="扩展连接令牌",
            value=str(getattr(config, "browser_extension_token", "") or ""),
            password=True,
            can_reveal_password=True,
            read_only=True,
            expand=True,
            tooltip="仅复制到扩展设置页；不要发给他人。",
        )
        self.browser_endpoint_input = ft.TextField(
            label="本机连接地址",
            value=f"http://127.0.0.1:{int(getattr(config, 'browser_bridge_port', DEFAULT_PORT))}",
            read_only=True,
            expand=True,
        )
        self.browser_extension_id_input = ft.TextField(
            label="固定扩展 ID", value=EXTENSION_ID, read_only=True, expand=True,
        )
        self.browser_endpoint_copy_btn = ft.IconButton(
            icon=ft.Icons.CONTENT_COPY,
            tooltip="复制本机连接地址",
            on_click=self._copy_browser_endpoint,
        )
        self.browser_token_copy_btn = ft.IconButton(
            icon=ft.Icons.CONTENT_COPY,
            tooltip="复制扩展连接令牌",
            on_click=self._copy_browser_token,
        )

        self.lib_paths = list(getattr(config, "library_paths", []) or [str(config.output_dir)])
        self.lib_path_list = ft.Column(spacing=6)
        self._refresh_lib_paths()

        self.save_top_btn = ft.ElevatedButton(
            "保存设置", icon=ft.Icons.SAVE, on_click=self.on_save
        )
        self.save_bottom_btn = ft.ElevatedButton(
            "保存设置", icon=ft.Icons.SAVE, on_click=self.on_save
        )

        self.content = ft.Column(
            [
                ft.Row([
                    ft.Text("设置", size=28, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    self.save_top_btn,
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
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
                ft.Text("浏览器扩展", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
                ft.Text(
                    "在 asmr.one 的销量旁显示是否已入库，并把下载请求安全交给 ARSM。扩展不会直接读写媒体文件。",
                    size=12, color="white70",
                ),
                ft.Row([self.browser_bridge_switch]),
                self.browser_bridge_status,
                ft.Row([self.browser_endpoint_input, self.browser_endpoint_copy_btn]),
                ft.Row([self.browser_extension_id_input]),
                ft.Row([self.browser_token_input, self.browser_token_copy_btn]),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            "打开扩展安装目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=self._open_browser_extension_folder,
                        ),
                        ft.OutlinedButton(
                            "管理 / 卸载扩展",
                            icon=ft.Icons.SETTINGS,
                            on_click=self._open_browser_extension_manager,
                        ),
                        ft.OutlinedButton(
                            "检查连接",
                            icon=ft.Icons.REFRESH,
                            on_click=self._check_browser_bridge,
                        ),
                        ft.TextButton(
                            "重新生成令牌",
                            icon=ft.Icons.KEY,
                            on_click=self._confirm_regenerate_browser_token,
                        ),
                    ],
                    wrap=True,
                ),
                ft.Text(
                    "安装：在 Chrome/Edge 扩展管理页开启开发者模式，选择“加载已解压的扩展程序”，指向上面的目录。卸载也在扩展管理页完成。",
                    size=12, color="white70",
                ),
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
                self.save_bottom_btn,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self._active = False

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if self._active:
            self._refresh_browser_bridge_status(update=True)

    def _refresh_browser_bridge_status(self, *, update: bool = False) -> None:
        snapshot = self.app_controller.browser_bridge_snapshot()
        self.browser_endpoint_input.value = snapshot.endpoint
        if snapshot.running:
            self.browser_bridge_status.value = "已连接：ARSM 正在等待扩展请求"
            self.browser_bridge_status.color = SUCCESS
        elif snapshot.enabled and snapshot.last_error:
            self.browser_bridge_status.value = f"连接失败：{snapshot.last_error}"
            self.browser_bridge_status.color = ERROR
        elif snapshot.enabled:
            self.browser_bridge_status.value = "已启用，保存设置后将启动本机连接"
            self.browser_bridge_status.color = WARNING
        else:
            self.browser_bridge_status.value = "未启用：网页不会连接 ARSM"
            self.browser_bridge_status.color = "white70"
        if update:
            try:
                self.browser_bridge_status.update()
                self.browser_endpoint_input.update()
            except Exception:
                pass

    def _copy_browser_endpoint(self, _event) -> None:
        self.app_controller.page.set_clipboard(self.browser_endpoint_input.value)
        self.app_controller.show_snack("本机连接地址已复制")

    def _copy_browser_token(self, _event) -> None:
        self.app_controller.page.set_clipboard(self.browser_token_input.value)
        self.app_controller.show_snack("扩展令牌已复制；请只粘贴到 ARSM 网页助手设置")

    def _open_browser_extension_folder(self, _event) -> None:
        folder = resource_path("browser_extension")
        if not folder.is_dir():
            self.app_controller.show_snack(f"扩展目录不存在：{folder}")
            return
        os.startfile(str(folder))
        self.app_controller.show_snack("已打开扩展目录，请在浏览器中选择该文件夹")

    def _open_browser_extension_manager(self, _event) -> None:
        if not webbrowser.open("chrome://extensions/"):
            webbrowser.open("edge://extensions/")
        self.app_controller.show_snack("请在扩展管理页启用、更新或卸载 ARSM 扩展")

    def _check_browser_bridge(self, _event) -> None:
        self._refresh_browser_bridge_status(update=True)
        snapshot = self.app_controller.browser_bridge_snapshot()
        if snapshot.running:
            self.app_controller.show_snack("本机桥接运行正常；请在扩展设置页保存同一个令牌")
        elif snapshot.enabled:
            self.app_controller.show_snack(snapshot.last_error or "本机桥接尚未启动，请保存设置后重试")
        else:
            self.app_controller.show_snack("请先启用浏览器扩展连接并保存设置")

    def _confirm_regenerate_browser_token(self, _event) -> None:
        def close_dialog(_click=None) -> None:
            closer = getattr(self.app_controller.page, "close", None)
            if callable(closer):
                closer(dialog)
            else:
                dialog.open = False
                self.app_controller.page.update()

        def regenerate(_click) -> None:
            self.browser_token_input.value = secrets.token_urlsafe(36)
            self.browser_token_input.update()
            close_dialog()
            self.app_controller.show_snack("新令牌已生成；保存设置后，请同步到扩展设置页")

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("重新生成扩展令牌？"),
            content=ft.Text(
                "旧令牌会立即失效。保存后需要把新令牌复制到 Chrome/Edge 扩展设置页。"
            ),
            actions=[
                ft.TextButton("取消", on_click=close_dialog),
                ft.TextButton("重新生成", on_click=regenerate),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        opener = getattr(self.app_controller.page, "open", None)
        if callable(opener):
            opener(dialog)
        else:
            self.app_controller.page.dialog = dialog
            dialog.open = True
            self.app_controller.page.update()

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
            "tag_audio", "sort_files", "browser_bridge_enabled",
            "browser_bridge_port", "browser_extension_token",
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
            browser_token = str(self.browser_token_input.value or "").strip()
            if self.browser_bridge_switch.value and len(browser_token) < 32:
                raise ValueError("浏览器扩展连接令牌无效，请重新生成")

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
            config.browser_bridge_enabled = bool(self.browser_bridge_switch.value)
            config.browser_bridge_port = DEFAULT_PORT
            config.browser_extension_token = browser_token
            config.save()
            self.app_controller.apply_browser_bridge_settings()

            # The service is read-only, but it snapshots paths for duplicate scans.
            # Refresh those snapshots immediately; existing active targets stay fixed.
            if service is not None:
                service.output_dir = Path(config.output_dir)
                service.library_paths = tuple(Path(value) for value in config.library_paths)
            self.app_controller.show_snack(
                "设置已保存；浏览器扩展连接已同步，并发线程数重启后完整生效"
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
