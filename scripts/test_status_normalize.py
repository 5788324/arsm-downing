#!/usr/bin/env python3
"""状态归一测试 — 中文/英文状态全部归一正确."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  状态归一测试\n{'='*60}\n")
    from ui.views.download_view import DownloadView
    n = DownloadView.normalize_status
    tests = {
        "metadata_failed":"metadata_failed","Metadata failed":"metadata_failed",
        "Metadata failed: proxy http://x":"metadata_failed",
        "获取元数据失败":"metadata_failed","元数据失败":"metadata_failed",
        "No pending tracks":"no_pending","no_pending":"no_pending",
        "No pending tracks to resume":"no_pending","无可恢复文件":"no_pending",
        "重复 (跳过)":"duplicate","Duplicate: /tmp/x":"duplicate",
        "failed":"failed","Failed to fetch":"failed","下载失败":"failed",
        "Error: x":"failed",
        "队列中":"active","Queued":"active","Queued (cached)":"active",
        "下载中":"active","Downloading":"active","Prepared":"active",
        "Preparing":"active","Resuming...":"active",
        "已暂停":"paused","Paused":"paused","Paused (partial)":"paused",
        "已完成":"terminal","Completed":"terminal","completed":"terminal",
        "registered":"terminal",
    }
    for inp, exp in tests.items():
        assert n(inp)==exp,f"normalize({inp!r})={n(inp)!r} expected {exp!r}"
    print(f"  ✓ {len(tests)} 条全部归一正确")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
