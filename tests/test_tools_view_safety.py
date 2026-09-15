from pathlib import Path


def test_tools_view_has_no_fake_or_direct_destructive_maintenance():
    source = Path("ui/views/tools_view.py").read_text(encoding="utf-8")
    assert "time.sleep" not in source
    assert "DELETE FROM downloads" not in source
    assert 'execute("VACUUM")' not in source
    assert "RJ01510133" not in source
    assert "preview_queue_cleanup" in source
    assert "cleanup_metadata_cache" in source
    assert "vacuum_database" in source
    assert "run_blocking" in source
    assert "diagnose_download_failures" in source
    assert "get_backlog_summary" in source
    assert "self.app_controller.db.conn.execute" not in source
    assert "_backlog_stats" not in source
    assert "预览队列清理" in source
    assert "预览迁移计划" in source
    assert "on_click=self.migrate_execute" not in source


def test_network_diagnostic_does_not_get_proxy_url_as_destination():
    source = Path("ui/views/tools_view.py").read_text(encoding="utf-8")
    assert "session.get(mirror, proxy=proxy)" in source
    assert "session.get(proxy" not in source
    assert "s.get(mp" not in source


def test_tools_view_uses_beginner_friendly_guidance():
    source = Path("ui/views/tools_view.py").read_text(encoding="utf-8")
    assert "日常使用建议" in source
    assert "去设置扫描目录" in source
    assert "不删除媒体文件" in source
    assert "不修改任务状态" in source
    assert "config.json 设置 external_intake_root" not in source
    assert "library_paths 中的 RJ 目录" not in source
    assert "分析 downloads 表" not in source


def test_tools_view_constructs_with_flet_027():
    from types import SimpleNamespace
    from ui.views.tools_view import ToolsView

    view = ToolsView(SimpleNamespace())
    assert view.external_settings_btn.text == "去设置扫描目录"