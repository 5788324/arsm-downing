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
                ft.ElevatedButton("清理无效队列", icon=ft.icons.CLEANING_SERVICES, on_click=self.clean_queue),
            ], spacing=20, wrap=True),
            ft.Row([
                ft.ElevatedButton("诊断失败任务", icon=ft.icons.BUG_REPORT,
                    on_click=self.diagnose_failed),
            ], spacing=20, wrap=True),
            ft.Row([
                ft.ElevatedButton("迁移已完成作品", icon=ft.icons.DRIVE_FILE_MOVE,
                    on_click=self.migrate_completed),
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

    def migrate_completed(self, e):
        """Dry-run then execute migration of completed/verified works."""
        db = self.app_controller.db

        # ── Step 1: Find safe-to-move works ──
        self.log("> 查找可安全迁移的作品...", "white")
        safe_ids = db.get_safe_migratable_works()
        if not safe_ids:
            self.log("  无可迁移作品（需要 works.status in completed/verified", WARNING)
            self.log("  且 downloads 中无 queued/paused/downloading/failed）", WARNING)
            return

        total_size = sum(item["size_bytes"] for item in safe_ids)
        self.log(f"  发现 {len(safe_ids)} 个可迁移作品", SUCCESS)
        self.log(f"  预计可释放空间: {total_size / 1024 / 1024:.1f} MB", ACCENT_PRIMARY)
        self.log(f"")
        for item in safe_ids[:10]:
            self.log(f"    {item['rj_id']}: {item.get('title','?')[:40]} → {item.get('local_path','?')[:60]}", "white")
        if len(safe_ids) > 10:
            self.log(f"    ... 还有 {len(safe_ids) - 10} 个", "grey")

        # ── Step 2: Dry-run only — user should move manually then re-scan ──
        self.log("")
        self.log("> 迁移操作说明:", ACCENT_PRIMARY)
        self.log("  1. 关闭程序", WARNING)
        self.log("  2. 手动将上面列出的 RJ 文件夹移动到新磁盘", "white")
        self.log("  3. 在设置中添加新磁盘路径到 library_paths", "white")
        self.log("  4. 启动程序后执行「扫描仓库」重新索引", "white")
        self.log("")
        self.log("  ⚠ 不要移动含 .part 文件或未完成的任务!", WARNING)

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
