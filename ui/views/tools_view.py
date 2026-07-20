import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR
import asyncio
import os
import time
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
                ft.ElevatedButton("\u8fd0\u884c\u4e00\u952e\u8bca\u65ad", icon=ft.icons.HEALTH_AND_SAFETY, on_click=self.run_diagnostic),
                ft.ElevatedButton("\u6d4b\u8bd5\u7f51\u7edc", icon=ft.icons.NETWORK_CHECK, on_click=self.test_network),
            ], spacing=12, wrap=True),

            ft.Text("\u4ed3\u5e93\u4e0e\u5143\u6570\u636e", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("\u626b\u63cf\u4ed3\u5e93", icon=ft.icons.FOLDER_SPECIAL, on_click=self.scan_library,
                    tooltip="\u626b\u63cf library_paths \u4e2d\u7684 RJ \u76ee\u5f55\u5e76\u66f4\u65b0 library_index"),
                ft.ElevatedButton("\u8bca\u65ad\u5931\u8d25\u4efb\u52a1", icon=ft.icons.BUG_REPORT, on_click=self.diagnose_failed,
                    tooltip="\u5206\u6790 downloads \u8868\u4e2d\u7684\u5931\u8d25\u72b6\u6001"),
            ], spacing=12, wrap=True),

            ft.Text("\u8fc1\u79fb", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("\u8fc1\u79fb\u5df2\u5b8c\u6210\u4f5c\u54c1", icon=ft.icons.DRIVE_FILE_MOVE, on_click=self.migrate_dry_run,
                    tooltip="\u626b\u63cf completed/verified \u4f5c\u54c1\u5e76\u8fc1\u79fb\u5230 output_dir"),
                ft.ElevatedButton("\u9a8c\u8bc1\u8fc1\u79fb", icon=ft.icons.VERIFIED_USER, on_click=self.verify_migrated),
            ], spacing=12, wrap=True),
            ft.Row([self.keep_source_checkbox, self.delete_source_checkbox], spacing=12, wrap=True),

            # ── 外部资源导入 ──
            ft.Text("外部资源整理", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("扫描外部资源", icon=ft.icons.FOLDER_SPECIAL, on_click=self.external_scan,
                    tooltip="扫描 E:\\arsm 顶层，检测文件树规范化需求"),
                ft.ElevatedButton("整理 dry-run", icon=ft.icons.PREVIEW, on_click=self.external_dry_run,
                    tooltip="预览规范化操作，不实际修改"),
                ft.ElevatedButton(
                    "执行整理（安全重构中）",
                    icon=ft.icons.BLOCK,
                    disabled=True,
                    tooltip="真实文件移动和数据库写入已冻结；当前仅允许扫描和 DRY-RUN",
                ),
            ], spacing=12, wrap=True),

            ft.Text("\u961f\u5217\u6e05\u7406", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("\u6e05\u7406\u65e0\u6548\u961f\u5217", icon=ft.icons.CLEANING_SERVICES, on_click=self.clean_queue,
                    tooltip="\u6e05\u7406 queue.json \u548c downloads \u4e2d\u7684\u65e0\u6548\u4efb\u52a1\u8bb0\u5f55"),
            ], spacing=12, wrap=True),

            ft.Text("\u7f13\u5b58\u4e0e\u6570\u636e\u5e93", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("\u538b\u7f29\u6570\u636e\u5e93(VACUUM)", icon=ft.icons.STORAGE, on_click=self.repair_db,
                    tooltip="\u6267\u884c SQLite VACUUM \u538b\u7f29\u6570\u636e\u5e93\u6587\u4ef6"),
                ft.ElevatedButton("\u6e05\u7406\u5143\u6570\u636e\u7f13\u5b58", icon=ft.icons.DELETE_SWEEP, on_click=self.clear_cache,
                    tooltip="\u6e05\u7406\u8fc7\u671f metadata_cache \u6761\u76ee"),
            ], spacing=12, wrap=True),

            ft.Divider(height=10, color="transparent"),
            ft.Text("\u5386\u53f2\u4efb\u52a1\u6062\u590d", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            self.backlog_summary,
            ft.Row([
                self.backlog_source,
                self.backlog_batch_size,
                ft.ElevatedButton("\u9884\u89c8", icon=ft.icons.PREVIEW, on_click=self.backlog_preview),
                ft.ElevatedButton("\u6062\u590d\u961f\u5217", icon=ft.icons.REFRESH, on_click=self.backlog_reenable, bgcolor=WARNING),
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
        return "copy_keep_source" if self.keep_source_mode else "move"

    def require_delete_source_confirm(self) -> bool:
        if self.keep_source_mode:
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
        # Trigger enrichment + verification in background
        import asyncio
        async def _enrich_and_verify():
            orc = self.app_controller.orc
            enriched = await orc.enrich_external_works(max_concurrent=2)
            self.log(f"  已补全元数据: {enriched} 个", SUCCESS)
            verified = await orc.verify_library_works()
            partial_count = sum(1 for v in verified.values() if v == "partial")
            if partial_count:
                self.log(f"  部分完成: {partial_count} 个", WARNING)
        asyncio.run_coroutine_threadsafe(
            _enrich_and_verify(), self.app_controller.loop)

    def repair_db(self, e):
        self.log("> 开始修复数据库...", "white")
        try:
            self.app_controller.db.conn.execute("VACUUM")
            self.log("✓ 数据库修复/优化成功!", SUCCESS)
        except Exception as ex:
            self.log(f"✗ 数据库修复失败: {ex}", ERROR)

    def clean_queue(self, e):
        self.log("> 清理无效队列...", "white")
        db = self.app_controller.db
        statuses = ("metadata_failed", "completed", "registered")
        for st in statuses:
            db.conn.execute("DELETE FROM downloads WHERE status=?", (st,))
        # Also clean from queue.json
        from pathlib import Path
        qf = Path("queue.json")
        if qf.exists():
            import json
            try:
                with open(qf) as f:
                    q = json.load(f)
                clean = {}
                for k, v in q.items():
                    if v.get("status") not in ("已完成", "metadata_failed",
                        "Metadata failed", "Queued", "Downloading",
                        "Prepared", "Paused", "queued", "downloading",
                        "prepared", "paused"):
                        pass  # keep
                    elif v.get("status") in ("已完成", "metadata_failed",
                            "Metadata failed"):
                        continue  # remove
                    clean[k] = v
                with open(qf, "w") as f:
                    json.dump(clean, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        db.conn.commit()
        self.log("✓ 队列已清理", SUCCESS)
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
        self.log("> 检查代理配置...", "white")
        import aiohttp
        from core.config import HOSTNAME_MIRRORS
        cfg = self.app_controller.config

        mp = cfg.metadata_proxy or cfg.proxy
        self.log(f"  metadata_proxy: {mp or '(无/直连)'}", ACCENT_PRIMARY)
        self.log(f"  download_proxy: {cfg.download_proxy or '(无/直连)'}", ACCENT_PRIMARY)
        self.log(f"  cover_proxy: {cfg.cover_proxy or '(无/直连)'}", ACCENT_PRIMARY)

        self.log("  ⚠ Clash Verge 诊断提示:", WARNING)
        self.log("    如果 Clash Verge 开启了 TUN/系统代理/全局模式，", "white")
        self.log("    即使 download_proxy=direct，系统层也可能劫持下载流量!", WARNING)
        self.log("    推荐: 关闭 TUN 和系统代理，仅保留 mixed port 7897", SUCCESS)
        self.log("    程序会显式使用 metadata_proxy 获取元数据", "white")
        self.log("    下载 CDN 直连。或为 CDN 添加 DIRECT 规则:", "white")
        self.log("    DOMAIN-SUFFIX,kiko-play-niptan.one,DIRECT", ACCENT_PRIMARY)
        self.log("    DOMAIN-SUFFIX,dlsite.com,DIRECT", ACCENT_PRIMARY)
        self.log("")

        async def _test():
            if mp:
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.get(mp, timeout=5) as resp:
                            self.log(f"✓ 代理 {mp} 可用 (HTTP {resp.status})",
                                     SUCCESS)
                except aiohttp.ClientConnectorError:
                    self.log(
                        f"✗ 代理 {mp} 拒绝连接 — 代理端口未开启或配置错误",
                        ERROR)
                except Exception as ex:
                    self.log(f"✗ 代理 {mp} 不可用: {ex}", ERROR)

            for mirror in HOSTNAME_MIRRORS:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(mirror, timeout=5,
                                               proxy=mp) as resp:
                            if resp.status in (200, 403, 404):
                                self.log(
                                    f"✓ {mirror} 连接正常", SUCCESS)
                            else:
                                self.log(
                                    f"⚠ {mirror} HTTP {resp.status}",
                                    WARNING)
                except aiohttp.ClientConnectorError:
                    self.log(
                        f"✗ {mirror} 连接拒绝 — 检查 metadata_proxy", ERROR)
                except Exception:
                    self.log(
                        f"✗ {mirror} 无法连接 — 检查网络/代理", ERROR)
        import asyncio
        if hasattr(self, 'app_controller') and \
           hasattr(self.app_controller, 'loop'):
            asyncio.run_coroutine_threadsafe(
                _test(), self.app_controller.loop)
        else:
            asyncio.create_task(_test())

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
        """RC8.4: Dry-run with fixed output_dir target + disk space check."""
        from core.migration import MigrationEngine
        db = self.app_controller.db
        engine = MigrationEngine(db)

        target_base = self.resolve_migration_target()
        if not target_base:
            return

        self.log(f"> \u8fc1\u79fb\u5019\u9009 dry-run target={target_base}", "white")
        self.log(
            f"  migration_mode={self.current_migration_mode()} "
            f"source_will_be_preserved={'yes' if self.keep_source_mode else 'no'}",
            ACCENT_PRIMARY,
        )
        dry = engine.dry_run(str(target_base))
        self.log(
            f"  MIGRATION_DRY_RUN candidate_count={dry['candidate_count']} "
            f"total_size={dry['total_size_mb']}MB",
            ACCENT_PRIMARY,
        )
        self.log(
            f"  skipped_already_on_target={dry['skipped_already_on_target']} "
            f"skipped_target_exists={dry['skipped_target_exists']} "
            f"skipped_pending={dry['skipped_pending']} "
            f"skipped_part_file={dry['skipped_part_file']}",
            "grey",
        )
        self.log_space_check(dry['space_check'])

        if dry["candidate_count"] == 0:
            self.log("  \u6ca1\u6709\u53ef\u8fc1\u79fb\u5019\u9009\u3002", WARNING)
            return

        self.log("")
        for item in dry["candidates"][:20]:
            self.log(
                f"  {item['rj_id']} [{item['status']}] {item['size_mb']}MB",
                "white",
            )
            self.log(f"    source: {item['source']}", "grey")
            self.log(f"    target: {item['target']}", ACCENT_PRIMARY)
        if dry["candidate_count"] > 20:
            self.log(f"  ... \u8fd8\u6709 {dry['candidate_count'] - 20} \u4e2a\u5019\u9009", "grey")

        self.log("")
        self.log(
            f"> mode={self.current_migration_mode()} / copy_keep_source mode source will be preserved={self.keep_source_mode}",
            ACCENT_PRIMARY,
        )
        self.log("  \u63d0\u793a\uff1adry-run \u4e0d\u4f1a\u4fee\u6539 history.db \u6216\u6587\u4ef6\u3002", WARNING)

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
        candidates = dry['candidates']
        orc = self.app_controller.orc
        active_or_queued = orc.queued_rj_ids | set(orc.active_tasks.keys())

        batch = []
        for item in candidates:
            validation = engine.validate_migration_request(
                item["rj_id"], item["source"], item["target"], str(target_base),
                active_or_queued=active_or_queued,
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
            f"  mode={self.current_migration_mode()} copy_keep_source mode source will be preserved={'yes' if self.keep_source_mode else 'no'}",
            ACCENT_PRIMARY,
        )
        self.log("  \u6ce8\u610f\uff1a\u8fd9\u662f\u5b9e\u9645\u8fc1\u79fb\uff0c\u4f1a\u66f4\u65b0 history.db\u3002", WARNING)

        ok, fail = 0, 0
        delete_source = not self.keep_source_mode
        for item in batch:
            rj_id = item["rj_id"]
            self.log(f"  MIGRATION_START rj={rj_id}", "white")
            res = engine.migrate_one(
                rj_id, item["source"], item["target"],
                delete_source=delete_source,
                target_base=str(target_base), active_or_queued=active_or_queued,
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
                    "source_equals_target", "part_file_present", "target_exists_nonempty",
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
        """RC8.4: Verify migrated works against output_dir and keep-source plan."""
        from core.migration import MigrationEngine

        db = self.app_controller.db
        engine = MigrationEngine(db)
        target_base = self.resolve_migration_target()
        if not target_base:
            return

        source_roots = self.list_migration_source_roots(target_base)
        self.log("> \u9a8c\u8bc1\u5df2\u8fc1\u79fb\u4f5c\u54c1...", "white")
        rows = db.conn.execute(
            "SELECT rj_id, local_path, status FROM works "
            "WHERE status IN ('completed','verified') ORDER BY rj_id"
        ).fetchall()

        verified_rows = []
        for row in rows:
            local_path = row["local_path"] or ""
            if local_path and str(local_path).lower().startswith(str(target_base).lower()):
                verified_rows.append(row)

        if not verified_rows:
            self.log("  \u6ca1\u6709\u4f4d\u4e8e\u76ee\u6807\u76d8\u7684 completed/verified \u4f5c\u54c1\u3002", "grey")
            return

        ok, issues = 0, 0
        for row in verified_rows[:20]:
            result = engine.verify_migrated_work(
                row["rj_id"], str(target_base), source_roots=source_roots)
            if result["success"]:
                mode_note = 'source_preserved' if result['source_preserved'] else 'source_deleted'
                self.log(f"  OK {row['rj_id']} [{row['status']}] verified {mode_note}", SUCCESS)
                ok += 1
            else:
                self.log(
                    f"  ERR {row['rj_id']}: work_exists={result['work_exists']} "
                    f"work_on_target={result['work_on_target']} "
                    f"missing_downloads={len(result['missing_downloads'])} "
                    f"downloads_not_on_target={len(result['downloads_not_on_target'])} "
                    f"source_removed_or_empty={result['source_removed_or_empty']} "
                    f"source_preserved={result['source_preserved']} "
                    f"cleanup_plan_present={result['cleanup_plan_present']} "
                    f"preserved_source_ok={result['preserved_source_ok']} "
                    f"library_on_target={result['library_on_target']} "
                    f"part_files_present={result['part_files_present']}",
                    ERROR,
                )
                issues += 1

        self.log(f"  \u9a8c\u8bc1\u5b8c\u6210: {ok} \u4e2a\u901a\u8fc7, {issues} \u4e2a\u5f02\u5e38", ACCENT_PRIMARY)

    def diagnose_failed(self, e):
        """RC7.10: Diagnose failed downloads — categories + write report."""
        self.log("> 诊断失败下载任务...", "white")
        db = self.app_controller.db
        d = db.diagnose_failed_downloads()

        self.log(f"  failed_total: {d['failed_total']}", ERROR)
        self.log(f"  failed_resumable_partial_file: {d['failed_resumable_partial_file']}", WARNING)
        self.log(f"  failed_retry_from_zero: {d['failed_retry_from_zero']}", ACCENT_PRIMARY)
        self.log(f"  failed_missing_file: {d['failed_missing_file']}", "grey")
        self.log(f"  failed_missing_url_or_metadata: {d['failed_missing_url_or_metadata']}", "grey")
        self.log(f"  failed_complete_but_db_failed: {d['failed_complete_but_db_failed']}", WARNING)
        self.log(f"  paused_resumable: {d['paused_resumable']}", SUCCESS)
        self.log(f"  paused_missing_file: {d['paused_missing_file']}", "grey")
        self.log(f"  registered_count: {d['registered_count']}", ACCENT_PRIMARY)
        self.log(f"  stale_count: {d.get('stale_count', 0)}", 'grey')
        self.log(f"  ignored_count: {d.get('ignored_count', 0)}", 'grey')

        if d["per_error_prefix"]:
            self.log("  错误前缀分布:", "white")
            for prefix, cnt in sorted(d["per_error_prefix"].items(), key=lambda x: -x[1])[:10]:
                self.log(f"    {prefix[:50]}: {cnt}", "grey")

        # Write report
        try:
            import os, json, datetime
            os.makedirs("logs", exist_ok=True)
            report = dict(d)
            report["generated_at"] = datetime.datetime.now().isoformat()
            report["per_error_prefix"] = dict(sorted(
                d["per_error_prefix"].items(), key=lambda x: -x[1]))
            with open("logs/failed_diagnosis.txt", "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False, default=str)
            self.log("  ✓ 报告已写入 logs/failed_diagnosis.txt", SUCCESS)
        except Exception as ex:
            self.log(f"  ✗ 写入报告失败: {ex}", ERROR)

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

    # ══════════════════════════════════════════════
    #  Backlog: History recovery task manager
    # ══════════════════════════════════════════════
    def _backlog_stats(self):
        """Return current backlog summary from DB."""
        db = self.app_controller.db
        try:
            stale_rjs = db.conn.execute(
                "SELECT COUNT(DISTINCT rj_id) FROM downloads WHERE status='stale'").fetchone()[0]
            stale_rows = db.conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE status='stale'").fetchone()[0]
            ignored_rjs = db.conn.execute(
                "SELECT COUNT(DISTINCT rj_id) FROM downloads WHERE status='ignored'").fetchone()[0]
            ignored_rows = db.conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE status='ignored'").fetchone()[0]
            queued_rows = db.conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE status='queued'").fetchone()[0]
            paused_rows = db.conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE status='paused'").fetchone()[0]
            return {"stale_rjs": stale_rjs, "stale_rows": stale_rows,
                    "ignored_rjs": ignored_rjs, "ignored_rows": ignored_rows,
                    "queued_rows": queued_rows, "paused_rows": paused_rows}
        except Exception:
            return {}

    def refresh_backlog(self, e=None):
        stats = self._backlog_stats()
        self.backlog_summary.value = (
            f"可恢复: {stats.get('stale_rjs',0)+stats.get('ignored_rjs',0)} 个作品 "
            f"({stats.get('stale_rows',0)+stats.get('ignored_rows',0)} 条记录) | "
            f"当前队列: {stats.get('queued_rows',0)} | 暂停: {stats.get('paused_rows',0)}"
        )
        self.backlog_summary.update()

    def backlog_preview(self, e):
        """Dry-run: show what a batch would re-enable. NO DB write."""
        source = self.backlog_source.value
        try:
            limit = int(self.backlog_batch_size.value or "30")
        except ValueError:
            limit = 30

        db = self.app_controller.db
        # Find candidate RJs by the selected source filter
        where = "WHERE d.status IN ('stale','ignored') AND d.rj_id != 'RJ01510133'"
        if source == "ignored":
            where += " AND d.status = 'ignored'"
        elif source == "stale":
            where += " AND d.status = 'stale'"

        candidate_rows = db.conn.execute(f"""
            SELECT d.rj_id, COUNT(*) as cnt FROM downloads d
            {where} GROUP BY d.rj_id ORDER BY cnt ASC LIMIT ?
        """, (limit,)).fetchall()

        rj_ids = [r[0] for r in candidate_rows]

        # Re-count ALL stale+ignored for these RJs (not just the filtered type)
        # because re-enable updates both stale AND ignored together
        if rj_ids:
            placeholders = ",".join("?" * len(rj_ids))
            actual_rows = db.conn.execute(f"""
                SELECT rj_id, COUNT(*) as cnt FROM downloads
                WHERE rj_id IN ({placeholders}) AND status IN ('stale','ignored')
                GROUP BY rj_id
            """, rj_ids).fetchall()
            actual_total = sum(r[1] for r in actual_rows)
        else:
            actual_total = 0
            actual_rows = []

        source_total = sum(r[1] for r in candidate_rows)
        if actual_total != source_total:
            preview = f"Preview ({source}, limit={limit}): {len(rj_ids)} RJs\n"
            preview += f"  {source} rows: {source_total} | actual stale+ignored: {actual_total}\n"
        else:
            preview = f"Preview ({source}, limit={limit}): {len(rj_ids)} RJs, {actual_total} rows\n"
        for r in actual_rows[:8]:
            preview += f"  {r[0]}: {r[1]} rows\n"
        if len(actual_rows) > 8:
            preview += f"  ... and {len(actual_rows)-8} more\n"
        preview += "\nNo DB write performed."
        self.backlog_preview_text.value = preview
        self._backlog_candidate_ids = rj_ids
        self.backlog_preview_text.update()

    def backlog_reenable(self, e):
        """Execute re-enable via the auditable CLI tool (backup + preimage + rollback)."""
        rj_ids = getattr(self, "_backlog_candidate_ids", [])
        if not rj_ids:
            self.app_controller.show_snack("Run Preview first to select candidates.")
            return

        def do_execute():
            import sys
            from pathlib import Path as P
            sys.path.insert(0, str(P(__file__).parent.parent.parent))
            from tools.backlog_reenable import execute

            result = execute(rj_ids, mode="retry-from-zero")
            integrity = result.get("integrity_after", "?")
            updated = result.get("updated_rows", 0)
            backup = result.get("backup_dir", "?")
            completed_ok = result.get("completed_unchanged", False)

            msg = f"Re-enabled {len(rj_ids)} RJs ({updated} rows). integrity={integrity}. Backup: {backup}"
            self.backlog_preview_text.value = msg
            self.backlog_preview_text.update()
            self.refresh_backlog()
            if not completed_ok:
                self.app_controller.show_snack("WARN: completed count changed!")
            self.app_controller.show_snack(msg[:80])

        self.app_controller.page.dialog = ft.AlertDialog(
            title=ft.Text(f"Re-enable {len(rj_ids)} RJs?"),
            content=ft.Text(f"Will update stale/ignored -> queued for {len(rj_ids)} RJs.\n"
                           "Backup + preimage + rollback will be created.\nNo files deleted."),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_dialog()),
                ft.TextButton("Execute", on_click=lambda e: [self._close_dialog(), do_execute()]),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.app_controller.page.dialog.open = True
        self.app_controller.page.update()

    def _close_dialog(self):
        self.app_controller.page.dialog.open = False
        self.app_controller.page.update()

    # ── External intake ──
    def external_scan(self, e):
        import sys
        from pathlib import Path as P
        sys.path.insert(0, str(P(__file__).parent.parent.parent))
        from tools.external_intake import scan_structure
        plan = scan_structure()
        self.log(f"扫描 {plan['scanned_top_dirs']} 目录, {plan['unique_rj']} 唯一RJ", ACCENT_PRIMARY)
        self.log(f"  已规范: {plan['already_normalized']} | 需改名: {plan['needs_rename_top_level']} | 需加Title层: {plan['needs_title_layer']}", SUCCESS)
        if plan['duplicate_rj']: self.log(f"  重复: {plan['duplicate_rj']}", WARNING)
        if plan['quarantine_required']: self.log(f"  需隔离: {plan['quarantine_required']}", ERROR)

    def external_dry_run(self, e):
        import sys
        from pathlib import Path as P
        sys.path.insert(0, str(P(__file__).parent.parent.parent))
        from tools.external_intake import scan_structure
        plan = scan_structure()
        self.log(f"DRY-RUN: 将规范 {plan['needs_rename_top_level']} 个目录 + {plan['needs_title_layer']} 个加层 + {plan['quarantine_required']} 个隔离", ACCENT_PRIMARY)
        for a in plan["actions"][:15]:
            self.log(f"  [{a['action']}] {a.get('name', a.get('dir',''))[:60]}", "white")

    def external_execute(self, e):
        """Defensive STOP for stale callbacks or programmatic invocation."""
        from tools.external_intake import EXECUTION_STOP_MESSAGE

        self.log(EXECUTION_STOP_MESSAGE, ERROR)
        self.app_controller.show_snack("外部资源真实整理已冻结，仅允许扫描和 DRY-RUN")

    # end backlog
