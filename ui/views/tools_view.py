import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR
import asyncio
import os
from pathlib import Path

class ToolsView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True

        self.log_area = ft.ListView(expand=True, spacing=5, auto_scroll=True)
        self.keep_source_mode = True
        self.delete_source_confirm_pending = False

        # Backlog widgets
        self.backlog_summary = ft.Text("", size=13, color="grey")
        self._backlog_source_val = "ignored"
        self._backlog_batch_val = "30"
        self.backlog_preview_text = ft.Text("", size=12, font_family="Consolas")

        # External intake is intentionally read-only until the transactional
        # execution service is implemented and accepted.
        self.external_status = ft.Text(
            "只读计划模式：请先在 config.json 设置 external_intake_root",
            size=12,
            color=WARNING,
        )
        self.external_report_text = ft.Text("", size=11, color="grey")
        self.external_scan_running = False

        self.backlog_source = ft.Dropdown(
            width=120, value="ignored",
            options=[ft.dropdown.Option("ignored"), ft.dropdown.Option("stale"), ft.dropdown.Option("all")])
        self.backlog_batch_size = ft.TextField(width=80, value="30", label="batch")

        self.keep_source_checkbox = ft.Checkbox(
            label="\u4fdd\u7559\u6e90\u76ee\u5f55\uff0c\u7a0d\u540e\u7edf\u4e00\u6e05\u7406",
            value=True,
            on_change=self._set_keep_source_mode,
        )
        self.delete_source_checkbox = ft.Checkbox(
            label="\u6210\u529f\u540e\u5220\u9664\u6e90\u76ee\u5f55",
            value=False,
            on_change=self._set_delete_source_mode,
        )

        self.content = ft.Column([
            ft.Text("\u7cfb\u7edf\u5de5\u5177", size=28, weight=ft.FontWeight.BOLD),

            ft.Text("\u8bca\u65ad", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("\u8fd0\u884c\u4e00\u952e\u8bca\u65ad", icon=ft.Icons.HEALTH_AND_SAFETY, on_click=self.run_diagnostic),
                ft.ElevatedButton("\u6d4b\u8bd5\u7f51\u7edc", icon=ft.Icons.NETWORK_CHECK, on_click=self.test_network),
            ], spacing=12, wrap=True),

            ft.Text("\u4ed3\u5e93\u4e0e\u5143\u6570\u636e", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("\u626b\u63cf\u4ed3\u5e93", icon=ft.Icons.FOLDER_SPECIAL, on_click=self.scan_library,
                    tooltip="\u626b\u63cf library_paths \u4e2d\u7684 RJ \u76ee\u5f55\u5e76\u66f4\u65b0 library_index"),
                ft.ElevatedButton("\u8bca\u65ad\u5931\u8d25\u4efb\u52a1", icon=ft.Icons.BUG_REPORT, on_click=self.diagnose_failed,
                    tooltip="\u5206\u6790 downloads \u8868\u4e2d\u7684\u5931\u8d25\u72b6\u6001"),
            ], spacing=12, wrap=True),

            ft.Text("\u8fc1\u79fb", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("预览迁移计划", icon=ft.Icons.DRIVE_FILE_MOVE, on_click=self.migrate_dry_run,
                    tooltip="后台扫描 completed/verified 作品；仅生成计划，不移动文件、不修改数据库"),
                ft.ElevatedButton("\u9a8c\u8bc1\u8fc1\u79fb", icon=ft.Icons.VERIFIED_USER, on_click=self.verify_migrated),
            ], spacing=12, wrap=True),
            ft.Row([self.keep_source_checkbox, self.delete_source_checkbox], spacing=12, wrap=True),

            # ── 外部资源导入（只读计划） ──
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.SECURITY, color=WARNING),
                        ft.Text("外部资源整理", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
                        ft.Container(expand=True),
                        ft.Text("READ-ONLY", size=11, color=WARNING, weight=ft.FontWeight.BOLD),
                    ]),
                    self.external_status,
                    ft.Row([
                        ft.ElevatedButton(
                            "扫描计划",
                            icon=ft.Icons.FOLDER_SPECIAL,
                            on_click=self.external_scan,
                            tooltip="读取配置路径并分类，不移动文件、不修改数据库",
                        ),
                        ft.ElevatedButton(
                            "生成完整 DRY-RUN 报告",
                            icon=ft.Icons.DESCRIPTION,
                            on_click=self.external_dry_run,
                            tooltip="后台扫描并保存完整 JSON/文本报告，actions 不截断",
                        ),
                        ft.ElevatedButton(
                            "真实执行已冻结",
                            icon=ft.Icons.BLOCK,
                            disabled=True,
                            tooltip="等待事务、回滚和沙盒验收完成后才会重新开放",
                        ),
                    ], spacing=12, wrap=True),
                    self.external_report_text,
                ], spacing=8),
                padding=12,
                border=ft.border.all(1, "#3b3b4f"),
                border_radius=10,
            ),

            ft.Text("\u961f\u5217\u6e05\u7406", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("预览队列清理", icon=ft.Icons.CLEANING_SERVICES, on_click=self.clean_queue,
                    tooltip="只读统计终态记录；存在活动或可恢复任务时不允许删除"),
            ], spacing=12, wrap=True),

            ft.Text("\u7f13\u5b58\u4e0e\u6570\u636e\u5e93", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("检查并压缩数据库", icon=ft.Icons.STORAGE, on_click=self.repair_db,
                    tooltip="后台检查；存在 queued/paused/downloading/failed 等任务时拒绝 VACUUM"),
                ft.ElevatedButton("安全清理元数据缓存", icon=ft.Icons.DELETE_SWEEP, on_click=self.clear_cache,
                    tooltip="仅删除过期且不属于活动、暂停、失败或恢复任务的缓存"),
            ], spacing=12, wrap=True),

            ft.Divider(height=10, color="transparent"),
            ft.Text("\u5386\u53f2\u4efb\u52a1\u6062\u590d", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            self.backlog_summary,
            ft.Row([
                self.backlog_source,
                self.backlog_batch_size,
                ft.ElevatedButton("\u9884\u89c8", icon=ft.Icons.PREVIEW, on_click=self.backlog_preview),
                ft.ElevatedButton("\u6062\u590d\u961f\u5217", icon=ft.Icons.REFRESH, on_click=self.backlog_reenable, bgcolor=WARNING),
            ], spacing=10),
            ft.Container(self.backlog_preview_text, padding=10, border_radius=8, bgcolor="#1a1a2e"),

            ft.Divider(height=10, color="transparent"),
            ft.Text("\u64cd\u4f5c\u65e5\u5fd7", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            Styles.glass_container(self.log_area, padding=10),
        ], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

    def log(self, message: str, color: str = "white"):
        self.log_area.controls.append(ft.Text(message, color=color, size=12, font_family="Consolas"))
        self.log_area.update()

    def _set_keep_source_mode(self, e):
        self.keep_source_mode = True
        self.keep_source_checkbox.value = True
        self.delete_source_checkbox.value = False
        self.delete_source_confirm_pending = False
        self.keep_source_checkbox.update()
        self.delete_source_checkbox.update()

    def _set_delete_source_mode(self, e):
        delete_mode = bool(self.delete_source_checkbox.value)
        self.keep_source_mode = not delete_mode
        self.keep_source_checkbox.value = not delete_mode
        self.delete_source_confirm_pending = False
        self.keep_source_checkbox.update()
        self.delete_source_checkbox.update()

    def current_migration_mode(self) -> str:
        return "copy_keep_source" if getattr(self, "keep_source_mode", True) else "move"

    def require_delete_source_confirm(self) -> bool:
        if getattr(self, "keep_source_mode", True):
            self.delete_source_confirm_pending = False
            return False
        if not self.delete_source_confirm_pending:
            self.delete_source_confirm_pending = True
            self.log("  WARNING: \u5c06\u5220\u9664\u6e90\u76ee\u5f55\uff0c\u8bf7\u518d\u6b21\u70b9\u51fb\u786e\u8ba4\u6267\u884c\u3002", WARNING)
            return True
        self.delete_source_confirm_pending = False
        return False

    def log_space_check(self, space_check: dict):
        self.log(
            f"  target_drive={space_check['target_drive']} free_space={space_check['free_space_gb']}GB "
            f"planned_size={space_check['planned_size_gb']}GB "
            f"headroom_required={space_check['headroom_required_gb']}GB "
            f"enough_space={'yes' if space_check['enough_space'] else 'no'}",
            SUCCESS if space_check['enough_space'] else WARNING,
        )

    def _db_path(self) -> Path:
        return Path(getattr(self.app_controller.db, "db_path", "history.db"))

    def scan_library(self, e):
        """Build a filesystem snapshot and atomically refresh library indexes."""
        del e
        paths = list(getattr(self.app_controller.config, "library_paths", []) or [])
        if not paths:
            self.log("⚠ library_paths 为空 — 请先在设置中添加资源库路径", WARNING)
            return
        self.log(f"> 后台扫描资源库路径 ({len(paths)} 个)…", "white")

        def _scan():
            return self.app_controller.db.rebuild_library(paths)

        def _render(result):
            if not result.get("success"):
                self.log(f"  扫描失败，旧索引已保留：{result.get('error', 'unknown')}", ERROR)
                return
            self.log(
                f"  发现 {result['found']} 个 RJ / {result['entries']} 个目录",
                SUCCESS,
            )
            self.log(
                f"  新增 works={result['indexed']} | 更新={result['updated']} | "
                f"陈旧索引清理={result['removed_index']} | 标记缺失={result['missing']}",
                ACCENT_PRIMARY,
            )
            if result.get("warnings"):
                self.log(f"  扫描警告: {result['warnings']} 项", WARNING)
            self.log("  library_items 与 library_index 已由同一快照原子更新。", "grey")

        self.app_controller.run_blocking(
            _scan, _render, action_label="资源库扫描"
        )

    def repair_db(self, e):
        """VACUUM on a dedicated connection and fail closed for active queues."""
        del e
        from core.tools_maintenance import vacuum_database

        self.log("> 检查数据库压缩条件…", "white")

        def _render(result):
            if not result.get("success"):
                preview = result.get("preview", {})
                active = preview.get("active_download_rows", 0)
                self.log(
                    f"  已阻止 VACUUM：存在 {active} 条活动/可恢复下载记录。",
                    WARNING,
                )
                self.log("  请等待下载器完全空闲后再执行，当前数据库未修改。", "grey")
                return
            reclaimed = result.get("reclaimed_bytes", 0)
            self.log(f"✓ 数据库压缩完成，回收约 {reclaimed / 1024 / 1024:.2f} MB", SUCCESS)

        self.app_controller.run_blocking(
            lambda: vacuum_database(self._db_path()),
            _render,
            action_label="数据库压缩",
        )

    def clean_queue(self, e):
        """Preview queue cleanup only; never delete mixed live queue state."""
        del e
        from core.tools_maintenance import preview_queue_cleanup

        self.log("> 只读预览队列清理…", "white")

        def _render(preview):
            self.log(
                f"  终态 DB 记录={preview.terminal_db_rows} | "
                f"queue.json 终态项={preview.terminal_queue_items}",
                ACCENT_PRIMARY,
            )
            if preview.blocked:
                self.log(
                    f"  已阻止清理：存在 {preview.active_download_rows} 条活动/可恢复记录。",
                    WARNING,
                )
            else:
                self.log("  当前只提供预览；实际删除入口尚未开放。", WARNING)

        self.app_controller.run_blocking(
            lambda: preview_queue_cleanup(self._db_path(), Path("queue.json")),
            _render,
            action_label="队列清理预览",
        )

    def clear_cache(self, e):
        """Delete only expired cache rows that no resumable task references."""
        del e
        from core.tools_maintenance import (
            cleanup_metadata_cache,
            preview_metadata_cache_cleanup,
        )

        self.log("> 后台检查元数据缓存…", "white")

        def _work():
            preview = preview_metadata_cache_cleanup(self._db_path())
            return cleanup_metadata_cache(
                self._db_path(), preview_token=preview.preview_token
            )

        def _render(result):
            preview = result.get("preview", {})
            if not result.get("success"):
                self.log("  缓存预览期间数据库已变化，未执行删除。", WARNING)
                return
            self.log(
                f"✓ 删除过期缓存 {result.get('deleted_rows', 0)} 条；"
                f"保护中的过期缓存 {preview.get('protected_expired_rows', 0)} 条",
                SUCCESS,
            )
            if preview.get("protected_expired_rows", 0):
                self.log("  暂停/失败/恢复任务所需的旧缓存已保留。", ACCENT_PRIMARY)

        self.app_controller.run_blocking(
            _work, _render, action_label="元数据缓存清理"
        )

    def test_network(self, e):
        """Test metadata mirrors through the configured proxy without probing the proxy URL as a website."""
        del e
        import aiohttp
        from core.config import HOSTNAME_MIRRORS

        cfg = self.app_controller.config
        proxy = cfg.get_proxy_for("metadata")
        mirrors = [cfg.mirror, *HOSTNAME_MIRRORS]
        mirrors = list(dict.fromkeys(item for item in mirrors if item))
        self.log(f"> 后台测试元数据网络；proxy={proxy or 'direct'}", "white")

        async def _test():
            results = []
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for mirror in mirrors:
                    try:
                        async with session.get(mirror, proxy=proxy) as response:
                            results.append({
                                "mirror": mirror,
                                "ok": response.status in (200, 401, 403, 404),
                                "status": response.status,
                                "error": "",
                            })
                    except Exception as exc:
                        results.append({
                            "mirror": mirror,
                            "ok": False,
                            "status": None,
                            "error": type(exc).__name__,
                        })
            return results

        def _render(results):
            for result in results:
                if result["ok"]:
                    self.log(
                        f"✓ {result['mirror']} HTTP {result['status']}", SUCCESS
                    )
                else:
                    self.log(
                        f"✗ {result['mirror']} {result['error'] or result['status']}",
                        ERROR,
                    )
            if proxy:
                self.log("  结果已通过 metadata_proxy 请求；未把代理地址当作目标网页。", ACCENT_PRIMARY)

        future = asyncio.run_coroutine_threadsafe(_test(), self.app_controller.loop)

        def _done(done_future):
            try:
                result = done_future.result()
            except Exception as exc:
                self.app_controller.ui_queue.put((
                    "ui_callback",
                    lambda value: self.log(f"✗ 网络测试失败: {value}", ERROR),
                    str(exc),
                ))
                return
            self.app_controller.ui_queue.put(("ui_callback", _render, result))

        future.add_done_callback(_done)

    def resolve_migration_target(self):
        """Resolve migration target strictly from config.output_dir."""
        cfg = self.app_controller.config
        output_dir = getattr(cfg, "output_dir", None)
        if not output_dir:
            self.log("  ERROR: output_dir \u672a\u914d\u7f6e\uff0c\u8fc1\u79fb\u5df2\u505c\u6b62\u3002", ERROR)
            return None

        target_base = Path(output_dir).expanduser().resolve(strict=False)
        if not target_base.exists():
            self.log(f"  ERROR: output_dir \u4e0d\u5b58\u5728: {target_base}", ERROR)
            return None

        source_roots = self.list_migration_source_roots(target_base)
        self.log(
            f"  MIGRATION_TARGET_RESOLVED target_base={target_base} "
            f"source_roots={source_roots}",
            ACCENT_PRIMARY,
        )
        return target_base

    def list_migration_source_roots(self, target_base):
        cfg = self.app_controller.config
        roots = []
        target_norm = str(target_base).lower()
        for raw in getattr(cfg, "library_paths", []):
            resolved = str(Path(raw).expanduser().resolve(strict=False))
            if resolved.lower() == target_norm:
                continue
            roots.append(resolved)
        return roots

    def migrate_dry_run(self, e):
        """Build a migration plan off the Flet thread using a read-only DB."""
        del e
        from core.database import LibraryVault
        from core.migration import MigrationEngine

        target_base = self.resolve_migration_target()
        if not target_base:
            return
        self.log(f"> 迁移计划 dry-run target={target_base}", "white")
        self.log(
            f"  migration_mode={self.current_migration_mode()} "
            f"source_will_be_preserved={'yes' if getattr(self, 'keep_source_mode', True) else 'no'}",
            ACCENT_PRIMARY,
        )

        def _work():
            db_path = self._db_path()
            if db_path.is_file():
                with LibraryVault.open_read_only(db_path) as readonly_db:
                    return MigrationEngine(readonly_db).dry_run(str(target_base))
            # Compatibility path for isolated tests backed by an in-memory DB.
            return MigrationEngine(self.app_controller.db).dry_run(str(target_base))

        def _render(dry):
            self.log(
                f"  MIGRATION_DRY_RUN candidate_count={dry['candidate_count']} "
                f"total_size={dry['total_size_mb']}MB",
                ACCENT_PRIMARY,
            )
            self.log(
                f"  skipped_already_on_target={dry['skipped_already_on_target']} "
                f"skipped_target_exists={dry['skipped_target_exists']} "
                f"skipped_pending={dry['skipped_pending']} "
                f"skipped_part_file={dry['skipped_part_file']} "
                f"skipped_unsafe={dry.get('skipped_symlink_or_unreadable', 0)}",
                "grey",
            )
            if dry.get("db_size_mismatch_count"):
                self.log(
                    f"  WARNING: {dry['db_size_mismatch_count']} 个作品的 DB size 与磁盘实测不一致；"
                    "空间估算已使用磁盘实测值。",
                    WARNING,
                )
            self.log_space_check(dry["space_check"])
            if dry["candidate_count"] == 0:
                self.log("  没有可迁移候选。", WARNING)
                return
            self.log("")
            for item in dry["candidates"][:20]:
                self.log(
                    f"  {item['rj_id']} [{item['status']}] {item['size_mb']}MB "
                    f"files={item.get('file_count', 0)}",
                    "white",
                )
                self.log(f"    source: {item['source']}", "grey")
                self.log(f"    target: {item['target']}", ACCENT_PRIMARY)
                self.log(f"    plan: {item.get('manifest_token', '')[:16]}", "grey")
            if dry["candidate_count"] > 20:
                self.log(f"  ... 还有 {dry['candidate_count'] - 20} 个候选", "grey")
            self.log("")
            self.log(
                f"> mode={self.current_migration_mode()} / source preserved="
                f"{getattr(self, 'keep_source_mode', True)}",
                ACCENT_PRIMARY,
            )
            self.log("  dry-run 不会修改 history.db 或文件。", WARNING)

        runner = getattr(self.app_controller, "run_blocking", None)
        if callable(runner):
            runner(_work, _render, action_label="迁移 dry-run")
        else:
            _render(_work())

    def migrate_execute(self, e, batch_limit: int):
        """RC8.4: Real migration using config.output_dir with keep-source default."""
        from core.migration import MigrationEngine
        db = self.app_controller.db
        engine = MigrationEngine(db)

        if self.require_delete_source_confirm():
            return

        target_base = self.resolve_migration_target()
        if not target_base:
            return

        dry = engine.dry_run(str(target_base))
        self.log_space_check(dry['space_check'])
        if not dry['space_check']['enough_space']:
            self.log('  MIGRATION_REJECT reason=insufficient_space', WARNING)
            return
        candidates = dry['candidates']
        orc = self.app_controller.orc
        active_or_queued = orc.queued_rj_ids | set(orc.active_tasks.keys())

        batch = []
        for item in candidates:
            validation = engine.validate_migration_request(
                item["rj_id"], item["source"], item["target"], str(target_base),
                active_or_queued=active_or_queued,
                expected_manifest_token=item.get('manifest_token', ''),
            )
            if not validation["success"]:
                self.log(
                    f"  MIGRATION_REJECT rj={item['rj_id']} reason={validation['reason']}",
                    WARNING,
                )
                continue
            batch.append(item)
            if len(batch) >= batch_limit:
                break

        if not batch:
            self.log("  \u6ca1\u6709\u53ef\u6267\u884c\u5019\u9009\uff0c\u53ef\u80fd\u88ab active/queued/invalid \u8fc7\u6ee4\u3002", WARNING)
            return

        self.log(f"> \u6267\u884c\u8fc1\u79fb {len(batch)} \u4e2a\u4f5c\u54c1...", ACCENT_PRIMARY)
        self.log(
            f"  mode={self.current_migration_mode()} copy_keep_source mode source will be preserved={'yes' if getattr(self, 'keep_source_mode', True) else 'no'}",
            ACCENT_PRIMARY,
        )
        self.log("  \u6ce8\u610f\uff1a\u8fd9\u662f\u5b9e\u9645\u8fc1\u79fb\uff0c\u4f1a\u66f4\u65b0 history.db\u3002", WARNING)

        ok, fail = 0, 0
        delete_source = not getattr(self, 'keep_source_mode', True)
        for item in batch:
            rj_id = item["rj_id"]
            self.log(f"  MIGRATION_START rj={rj_id}", "white")
            res = engine.migrate_one(
                rj_id, item["source"], item["target"],
                delete_source=delete_source,
                target_base=str(target_base), active_or_queued=active_or_queued,
                expected_manifest_token=item.get('manifest_token', ''),
            )
            if res["success"]:
                self.log(f"  MIGRATION_COPY_DONE rj={rj_id}", SUCCESS)
                self.log(f"  MIGRATION_VERIFY_DONE rj={rj_id}", SUCCESS)
                self.log(f"  MIGRATION_DB_UPDATE_DONE rj={rj_id}", SUCCESS)
                if delete_source:
                    self.log(f"  MIGRATION_DELETE_SOURCE_DONE rj={rj_id}", SUCCESS)
                else:
                    self.log(f"  MIGRATION_SOURCE_PRESERVED rj={rj_id}", SUCCESS)
                self.log(f"  MIGRATION_DONE rj={rj_id}", SUCCESS)
                ok += 1
            else:
                if res.get("error") in {
                    "active_or_queued", "pending_downloads", "source_missing",
                    "source_under_target_base", "target_not_under_target_base",
                    "source_equals_target", "source_target_overlap", "part_file_present",
                    "target_exists", "target_exists_nonempty", "unsafe_source_tree",
                    "source_plan_changed",
                }:
                    self.log(
                        f"  MIGRATION_REJECT rj={rj_id} reason={res['error']}",
                        WARNING,
                    )
                else:
                    self.log(
                        f"  MIGRATION_FAIL rj={rj_id} stage={res['stage']} error={res['error']}",
                        ERROR,
                    )
                fail += 1

        self.log(f"  \u8fc1\u79fb\u5b8c\u6210: {ok} \u4e2a\u6210\u529f, {fail} \u4e2a\u5931\u8d25", ACCENT_PRIMARY)

    def verify_migrated(self, e):
        """Verify migrated works in a worker thread using a read-only DB."""
        del e
        from core.database import LibraryVault
        from core.migration import MigrationEngine

        target_base = self.resolve_migration_target()
        if not target_base:
            return
        source_roots = self.list_migration_source_roots(target_base)
        self.log("> 后台验证已迁移作品…", "white")

        def _work():
            db_path = self._db_path()
            with LibraryVault.open_read_only(db_path) as readonly_db:
                engine = MigrationEngine(readonly_db)
                rows = readonly_db.conn.execute(
                    "SELECT rj_id, local_path, status FROM works "
                    "WHERE status IN ('completed','verified') ORDER BY rj_id"
                ).fetchall()
                selected = [
                    dict(row)
                    for row in rows
                    if row["local_path"]
                    and engine._is_same_or_under(row["local_path"], target_base)
                ]
                return [
                    (row, engine.verify_migrated_work(
                        row["rj_id"], str(target_base), source_roots=source_roots
                    ))
                    for row in selected[:20]
                ], len(selected)

        def _render(payload):
            results, total = payload
            if not results:
                self.log("  没有位于目标盘的 completed/verified 作品。", "grey")
                return
            ok = 0
            issues = 0
            for row, result in results:
                if result["success"]:
                    mode_note = "source_preserved" if result["source_preserved"] else "source_deleted"
                    self.log(f"  OK {row['rj_id']} [{row['status']}] {mode_note}", SUCCESS)
                    ok += 1
                else:
                    self.log(
                        f"  ERR {row['rj_id']}: work_exists={result['work_exists']} "
                        f"missing_downloads={len(result['missing_downloads'])} "
                        f"source_ok={result['source_removed_or_empty']} "
                        f"library_items_on_target={result.get('library_items_on_target')} "
                        f"library_index_on_target={result['library_on_target']} "
                        f"part_files={result['part_files_present']} "
                        f"manifest_error={result.get('target_manifest_error', '')}",
                        ERROR,
                    )
                    issues += 1
            if total > len(results):
                self.log(f"  仅显示前 {len(results)} / {total} 个作品。", WARNING)
            self.log(f"  验证完成: {ok} 个通过, {issues} 个异常", ACCENT_PRIMARY)

        runner = getattr(self.app_controller, "run_blocking", None)
        if callable(runner):
            runner(_work, _render, action_label="验证迁移")
        else:
            # Legacy isolated tests normally do not call this path.
            _render(_work())

    def diagnose_failed(self, e):
        """Diagnose failed downloads off the Flet thread using a read-only connection."""
        del e
        import json
        from datetime import datetime
        from core.tools_maintenance import diagnose_download_failures

        self.log("> 后台诊断失败下载任务…", "white")

        def _work():
            result = diagnose_download_failures(self._db_path())
            report_dir = Path("logs")
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / (
                "failed_diagnosis_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
            )
            payload = dict(result)
            payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
            report_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            return result, str(report_path)

        def _render(payload):
            result, report_path = payload
            self.log(f"  failed_total: {result['failed_total']}", ERROR)
            self.log(
                f"  failed_resumable_partial_file: {result['failed_resumable_partial_file']}",
                WARNING,
            )
            self.log(f"  failed_retry_from_zero: {result['failed_retry_from_zero']}", ACCENT_PRIMARY)
            self.log(f"  failed_missing_file: {result['failed_missing_file']}", "grey")
            self.log(
                f"  failed_missing_url_or_metadata: {result['failed_missing_url_or_metadata']}",
                "grey",
            )
            self.log(
                f"  failed_complete_but_db_failed: {result['failed_complete_but_db_failed']}",
                WARNING,
            )
            self.log(f"  paused_resumable: {result['paused_resumable']}", SUCCESS)
            self.log(f"  paused_missing_file: {result['paused_missing_file']}", "grey")
            self.log(f"  registered_count: {result['registered_count']}", ACCENT_PRIMARY)
            self.log(f"  stale_count: {result['stale_count']}", "grey")
            self.log(f"  ignored_count: {result['ignored_count']}", "grey")
            if result["per_error_prefix"]:
                self.log("  错误前缀分布:", "white")
                for prefix, count in sorted(
                    result["per_error_prefix"].items(), key=lambda item: -item[1]
                )[:10]:
                    self.log(f"    {prefix[:50]}: {count}", "grey")
            self.log(f"  ✓ 报告已写入 {report_path}", SUCCESS)

        self.app_controller.run_blocking(
            _work, _render, action_label="失败任务诊断"
        )

    def run_diagnostic(self, e):
        """Read-only diagnostics; never create output directories as a side effect."""
        del e
        from core.tools_maintenance import build_system_diagnostic

        self.log_area.controls.clear()
        self.log("=== 系统诊断开始（只读）===", ACCENT_PRIMARY)
        output_dir = self.app_controller.config.output_dir

        def _work():
            result = build_system_diagnostic(self._db_path(), output_dir)
            try:
                import mutagen  # noqa: F401
                result["mutagen"] = True
            except ImportError:
                result["mutagen"] = False
            try:
                import aiohttp  # noqa: F401
                result["aiohttp"] = True
            except ImportError:
                result["aiohttp"] = False
            return result

        def _render(result):
            self.log(
                f"数据库: {'✓' if result['db_exists'] else '✗'} {result['db_path']}",
                SUCCESS if result["db_exists"] else ERROR,
            )
            self.log(
                f"完整性: {result['integrity']}",
                SUCCESS if result["integrity"] == "ok" else WARNING,
            )
            self.log(
                f"输出目录存在/可写: {result['output_exists']}/{result['output_writable']} "
                f"{result['output_dir']}",
                SUCCESS if result["output_writable"] else WARNING,
            )
            self.log(f"mutagen: {'✓' if result['mutagen'] else '✗'}", SUCCESS if result["mutagen"] else ERROR)
            self.log(f"aiohttp: {'✓' if result['aiohttp'] else '✗'}", SUCCESS if result["aiohttp"] else ERROR)
            counts = result.get("download_status_counts", {})
            if counts:
                self.log(f"下载状态: {counts}", ACCENT_PRIMARY)
            self.log("=== 诊断完成；未创建目录、未修改数据库 ===", ACCENT_PRIMARY)

        self.app_controller.run_blocking(
            _work, _render, action_label="系统诊断"
        )

    # ══════════════════════════════════════════════
    #  Backlog: History recovery task manager
    # ══════════════════════════════════════════════
    def refresh_backlog(self, e=None):
        """Refresh backlog counts off the UI thread."""
        del e
        from core.tools_maintenance import get_backlog_summary

        def _render(stats):
            self.backlog_summary.value = (
                f"可恢复: {stats.get('stale_rjs', 0) + stats.get('ignored_rjs', 0)} 个作品 "
                f"({stats.get('stale_rows', 0) + stats.get('ignored_rows', 0)} 条记录) | "
                f"排队: {stats.get('queued_rows', 0)} | 暂停: {stats.get('paused_rows', 0)} | "
                f"失败: {stats.get('failed_rows', 0)} | 运行: {stats.get('running_rows', 0)}"
            )
            self.backlog_summary.update()

        self.app_controller.run_blocking(
            lambda: get_backlog_summary(self._db_path()),
            _render,
            action_label="历史任务统计",
        )

    def backlog_preview(self, e):
        """Build a read-only stale/ignored preview on a worker thread."""
        del e
        from core.tools_maintenance import preview_backlog_candidates

        source = self.backlog_source.value or "ignored"
        try:
            limit = int(self.backlog_batch_size.value or "30")
        except ValueError:
            limit = 30

        def _render(result):
            preview = (
                f"Preview ({result['source']}, limit={result['limit']}): "
                f"{result['candidate_count']} RJs\n"
                f"  selected rows: {result['source_rows']} | "
                f"actual stale+ignored: {result['actual_total']}\n"
            )
            for row in result["actual_rows"][:8]:
                preview += f"  {row['rj_id']}: {row['count']} rows\n"
            if len(result["actual_rows"]) > 8:
                preview += f"  ... and {len(result['actual_rows']) - 8} more\n"
            preview += "\nNo DB write performed."
            self.backlog_preview_text.value = preview
            self._backlog_candidate_ids = result["rj_ids"]
            self.backlog_preview_text.update()

        self.app_controller.run_blocking(
            lambda: preview_backlog_candidates(
                self._db_path(), source=source, limit=limit
            ),
            _render,
            action_label="历史任务恢复预览",
        )

    def backlog_reenable(self, e):
        """Re-enable only after preview and only while the runtime queue is idle."""
        del e
        rj_ids = list(getattr(self, "_backlog_candidate_ids", []))
        if not rj_ids:
            self.app_controller.show_snack("请先运行预览选择候选任务")
            return

        runtime_active = set(getattr(self.app_controller.orc, "queued_rj_ids", set()))
        runtime_active.update(getattr(self.app_controller.orc, "active_tasks", {}).keys())
        if runtime_active:
            self.app_controller.show_snack(
                f"下载器仍有 {len(runtime_active)} 个运行时任务，恢复操作已阻止"
            )
            self.log("  历史任务恢复已阻止：请等待当前下载队列完全空闲。", WARNING)
            return

        def _execute():
            from tools.backlog_reenable import execute

            return execute(
                rj_ids,
                mode="continue",
                db_path=self._db_path(),
            )

        def _render(result):
            integrity = result.get("integrity_after", "?")
            updated = result.get("updated_rows", 0)
            backup = result.get("backup_dir", "?")
            message = (
                f"恢复 {len(rj_ids)} 个 RJ（{updated} 条记录）；"
                f"integrity={integrity}；backup={backup}"
            )
            self.backlog_preview_text.value = message
            self.backlog_preview_text.update()
            self.refresh_backlog()
            self.app_controller.show_snack(message[:100])

        def _confirmed(_event):
            self._close_dialog()
            self.app_controller.run_blocking(
                _execute, _render, action_label="历史任务恢复"
            )

        self.app_controller.page.dialog = ft.AlertDialog(
            title=ft.Text(f"恢复 {len(rj_ids)} 个 RJ？"),
            content=ft.Text(
                "仅把 stale/ignored 改为 queued，保留现有断点字节。\n"
                "执行前会创建 SQLite 在线备份和 preimage。"
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda _event: self._close_dialog()),
                ft.TextButton("执行", on_click=_confirmed),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.app_controller.page.dialog.open = True
        self.app_controller.page.update()

    def _close_dialog(self):
        self.app_controller.page.dialog.open = False
        self.app_controller.page.update()

    # ── External intake (read-only planner) ──
    def _external_paths(self):
        config = self.app_controller.config
        return (
            getattr(config, "external_intake_root", None),
            getattr(config, "external_quarantine_root", None),
        )

    def _set_external_busy(self, message: str) -> None:
        self.external_status.value = message
        self.external_status.color = ACCENT_PRIMARY
        self.external_status.update()

    def _render_external_plan(self, plan: dict, report_dir=None) -> None:
        counts = plan["counts"]
        fatal_count = len(plan["fatal_blockers"])
        review_count = len(plan["review_required"])
        quarantine_count = len(plan["quarantine_actions"])

        if fatal_count:
            status = f"不可执行：{fatal_count} 个致命问题"
            status_color = ERROR
        elif review_count:
            status = f"需要人工复核：{review_count} 项"
            status_color = WARNING
        else:
            status = "只读计划完成；真实执行仍保持冻结"
            status_color = SUCCESS

        self.external_status.value = status
        self.external_status.color = status_color
        self.external_status.update()

        root_label = plan["root"] or "未配置"
        self.log(f"> 外部资源只读扫描: {root_label}", ACCENT_PRIMARY)
        self.log(
            f"  目录={plan['scanned_top_dirs']} | RJ={plan['unique_rj']} | "
            f"fatal={fatal_count} | 复核={review_count} | 隔离候选={quarantine_count}",
            ERROR if fatal_count else WARNING if review_count else SUCCESS,
        )
        self.log(
            "  已规范={already} | 需加Title层={layer} | 需改顶层名={rename} | 重复RJ={duplicate}".format(
                already=counts["already_normalized"],
                layer=counts["needs_title_layer"],
                rename=counts["needs_rename_top_level"],
                duplicate=counts["duplicate_review"],
            ),
            "white",
        )

        for notice in plan["fatal_blockers"][:5]:
            self.log(f"  [FATAL] {notice['message']}", ERROR)
        for notice in plan["review_required"][:5]:
            self.log(f"  [REVIEW] {notice['message']}", WARNING)
        for warning in plan["warnings"][:3]:
            self.log(f"  [WARN] {warning['message']}", WARNING)

        for action in plan["actions"][:15]:
            source_name = action["source_name"] or action["source"]
            self.log(
                f"  [{action['classification']}] {source_name[:72]} — {action['reason']}",
                "white",
            )
        if len(plan["actions"]) > 15:
            self.log(f"  …另有 {len(plan['actions']) - 15} 项，完整内容见报告", "grey")

        if report_dir is not None:
            self.external_report_text.value = f"完整报告：{report_dir}"
            self.external_report_text.update()
            self.log(f"  完整报告: {report_dir}", SUCCESS)
        else:
            self.external_report_text.value = "扫描预览只显示前 15 项；使用“生成完整 DRY-RUN 报告”保存全部 actions。"
            self.external_report_text.update()

    async def _run_external_plan(self, write_report: bool) -> None:
        from tools.external_intake import (
            annotate_plan_with_database,
            scan_structure,
            write_plan_report,
        )

        if self.external_scan_running:
            self.app_controller.show_snack("外部资源扫描正在进行，请勿重复启动")
            return

        self.external_scan_running = True
        root, quarantine_root = self._external_paths()
        self._set_external_busy("正在后台扫描，只读操作不会修改文件或数据库…")
        try:
            plan = await asyncio.to_thread(scan_structure, root, quarantine_root)
            plan = await asyncio.to_thread(
                annotate_plan_with_database, plan, self.app_controller.db
            )
            report_dir = None
            if write_report:
                report_dir = await asyncio.to_thread(write_plan_report, plan)
            self._render_external_plan(plan, report_dir)
        except Exception as exc:
            self.external_status.value = "扫描失败；未执行任何文件或数据库修改"
            self.external_status.color = ERROR
            self.external_status.update()
            self.log(f"  [ERROR] 外部资源扫描失败: {exc}", ERROR)
            self.app_controller.show_snack("外部资源扫描失败，详情见操作日志")
        finally:
            self.external_scan_running = False

    async def _external_scan_async(self) -> None:
        await self._run_external_plan(write_report=False)

    async def _external_dry_run_async(self) -> None:
        await self._run_external_plan(write_report=True)

    def external_scan(self, e):
        del e
        self.app_controller.page.run_task(self._external_scan_async)

    def external_dry_run(self, e):
        del e
        self.app_controller.page.run_task(self._external_dry_run_async)

    def external_execute(self, e):
        """Defensive STOP for stale callbacks or programmatic invocation."""
        del e
        from tools.external_intake import EXECUTION_STOP_MESSAGE

        self.log(EXECUTION_STOP_MESSAGE, ERROR)
        self.app_controller.show_snack("外部资源真实整理已冻结，仅允许扫描和 DRY-RUN")

    # end backlog
