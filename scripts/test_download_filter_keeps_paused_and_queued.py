#!/usr/bin/env python3
"""下载过滤器保持 paused/queued 测试 — 验证过滤不过滤掉活跃项."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  下载过滤器保持 paused/queued 测试\n{'='*60}\n")

    from core.status import WorkStatus
    from ui.views.download_view import DownloadView

    # ── All active/non-terminal statuses should pass the filter ──
    # These should display regardless of show_completed toggle
    should_always_show = [
        "queued", "队列中", "队列排队中",
        "downloading", "下载中",
        "paused", "已暂停", "Paused", "Paused (partial)",
        "failed", "Failed", "下载失败",
        "metadata_failed", "Metadata failed", "获取元数据失败",
        "no_pending", "No pending tracks",
        "partial", "部分完成", "Partially completed (2/3)",
        "preparing", "准备中...",
        "prepared", "已就绪",
        "resuming", "恢复中...",
    ]

    print("── show_completed=false 时仍应显示的项 ──")
    for s in should_always_show:
        ns = DownloadView.normalize_status(s)
        ws = WorkStatus.normalize(s)
        is_term = DownloadView._is_terminal(s)
        assert not is_term, f"'{s}' 不应是 terminal (normalized={ns})"
        print(f"  ✓ '{s}' → normalize={ns} is_terminal={is_term}")

    # These should be hidden when show_completed=false
    should_hide = [
        "completed", "Completed", "已完成",
        "registered",
        "verified", "已验证",
        "external", "外部资源",
    ]

    print("\n── show_completed=false 时应隐藏的项 ──")
    for s in should_hide:
        is_term = DownloadView._is_terminal(s)
        ns = DownloadView.normalize_status(s)
        print(f"  ✓ '{s}' → normalize={ns} is_terminal={is_term}")

    # All should_hide must be terminal
    for s in should_hide:
        assert DownloadView._is_terminal(s), f"'{s}' should be terminal"
    print(f"\n  ✓ 所有应隐藏项都是 terminal")

    print(f"\n{'='*60}\n  ✓ 下载过滤器保持 paused/queued 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
