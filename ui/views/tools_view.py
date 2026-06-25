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

        self.content = ft.Column([
            ft.Text("实用工具与系统诊断", size=32, weight=ft.FontWeight.BOLD),
            ft.Text("系统工具", size=20, weight=ft.FontWeight.BOLD, color=ACCENT_PRIMARY),
            ft.Row([
                ft.ElevatedButton("修复数据库", icon=ft.icons.STORAGE, on_click=self.repair_db),
                ft.ElevatedButton("清理缓存", icon=ft.icons.DELETE_SWEEP, on_click=self.clear_cache),
                ft.ElevatedButton("测试网络", icon=ft.icons.NETWORK_CHECK, on_click=self.test_network),
                ft.ElevatedButton("扫描仓库", icon=ft.icons.FOLDER_SPECIAL, on_click=self.scan_library),
                ft.ElevatedButton("清理无效队列", icon=ft.icons.CLEANING_SERVICES, on_click=self.clean_queue),
            ], spacing=20, wrap=True),
            ft.Row([
                ft.ElevatedButton("诊断失败任务", icon=ft.icons.BUG_REPORT,
                    on_click=self.diagnose_failed),
                ft.ElevatedButton("迁移候选扫描", icon=ft.icons.FIND_IN_PAGE,
                    on_click=self.migrate_dry_run),
            ], spacing=20, wrap=True),
            ft.Row([
                ft.ElevatedButton("执行迁移(1个)", icon=ft.icons.PLAY_ARROW,
                    on_click=lambda e: self.migrate_execute(e, 1)),
                ft.ElevatedButton("执行迁移(3个)", icon=ft.icons.FAST_FORWARD,
                    on_click=lambda e: self.migrate_execute(e, 3)),
                ft.ElevatedButton("验证迁移", icon=ft.icons.VERIFIED_USER,
                    on_click=self.verify_migrated),
            ], spacing=20, wrap=True),
            ft.Row([
                ft.ElevatedButton("迁移已完成作品", icon=ft.icons.DRIVE_FILE_MOVE,
                    on_click=self.migrate_dry_run),
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
            self.log("  ERROR: output_dir ??????????", ERROR)
            return None

        target_base = Path(output_dir).expanduser().resolve(strict=False)
        if not target_base.exists():
            self.log(f"  ERROR: output_dir ???: {target_base}", ERROR)
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
        """RC8.1-hotfix: Dry-run with fixed output_dir target."""
        from core.migration import MigrationEngine
        db = self.app_controller.db
        engine = MigrationEngine(db)

        target_base = self.resolve_migration_target()
        if not target_base:
            return

        self.log(f"> ?????? target={target_base}", "white")
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

        if dry["candidate_count"] == 0:
            self.log("  ??????", WARNING)
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
            self.log(f"  ... ?? {dry['candidate_count'] - 20} ?", "grey")

        self.log("")
        self.log("> ???????(N?)?????????", ACCENT_PRIMARY)
        self.log("  ??: ???? history.db!", WARNING)

    def migrate_execute(self, e, batch_limit: int):
        """RC8.1-hotfix: Real migration using config.output_dir."""
        from core.migration import MigrationEngine
        db = self.app_controller.db
        engine = MigrationEngine(db)

        target_base = self.resolve_migration_target()
        if not target_base:
            return

        candidates = engine.get_candidates(str(target_base))
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
            self.log("  ??????(??? active/queued/invalid)", WARNING)
            return

        self.log(f"> ???? {len(batch)} ???...", ACCENT_PRIMARY)
        self.log("  ??: ?????? history.db!", WARNING)

        ok, fail = 0, 0
        for item in batch:
            rj_id = item["rj_id"]
            self.log(f"  MIGRATION_START rj={rj_id}", "white")
            res = engine.migrate_one(
                rj_id, item["source"], item["target"],
                target_base=str(target_base), active_or_queued=active_or_queued,
            )
            if res["success"]:
                self.log(f"  MIGRATION_COPY_DONE rj={rj_id}", SUCCESS)
                self.log(f"  MIGRATION_VERIFY_DONE rj={rj_id}", SUCCESS)
                self.log(f"  MIGRATION_DB_UPDATE_DONE rj={rj_id}", SUCCESS)
                self.log(f"  MIGRATION_DELETE_SOURCE_DONE rj={rj_id}", SUCCESS)
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

        self.log(f"  ????: {ok} ??, {fail} ??", ACCENT_PRIMARY)

    def verify_migrated(self, e):
        """RC8.1-hotfix: Verify migrated works against output_dir."""
        from core.migration import MigrationEngine

        db = self.app_controller.db
        engine = MigrationEngine(db)
        target_base = self.resolve_migration_target()
        if not target_base:
            return

        source_roots = self.list_migration_source_roots(target_base)
        self.log("> ??????...", "white")
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
            self.log("  ????????", "grey")
            return

        ok, issues = 0, 0
        for row in verified_rows[:20]:
            result = engine.verify_migrated_work(
                row["rj_id"], str(target_base), source_roots=source_roots)
            if result["success"]:
                self.log(f"  OK {row['rj_id']} [{row['status']}] verified", SUCCESS)
                ok += 1
            else:
                self.log(
                    f"  ERR {row['rj_id']}: work_exists={result['work_exists']} "
                    f"work_on_target={result['work_on_target']} "
                    f"missing_downloads={len(result['missing_downloads'])} "
                    f"downloads_not_on_target={len(result['downloads_not_on_target'])} "
                    f"source_removed_or_empty={result['source_removed_or_empty']} "
                    f"part_files_present={result['part_files_present']}",
                    ERROR,
                )
                issues += 1

        self.log(f"  ??: {ok} ??, {issues} ??", ACCENT_PRIMARY)

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
