#!/usr/bin/env python3
"""状态归一测试 — 通过 WorkStatus.normalize."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  状态归一测试\n{'='*60}\n")
    from core.status import WorkStatus as WS
    tests={
        "metadata_failed":"metadata_failed","Metadata failed":"metadata_failed",
        "Metadata failed: proxy http://x":"metadata_failed",
        "获取元数据失败":"metadata_failed","元数据失败":"metadata_failed",
        "No pending tracks":"no_pending","no_pending":"no_pending",
        "No pending tracks to resume":"no_pending","无可恢复文件":"no_pending",
        "重复 (跳过)":"duplicate","Duplicate: /tmp/x":"duplicate",
        "failed":"failed","Failed to fetch":"failed","下载失败":"failed",
        "Error: x":"failed",
        "队列中":"queued","Queued":"queued","Queued (cached)":"queued",
        "下载中":"downloading","Downloading":"downloading",
        "Prepared":"prepared","已就绪":"prepared",
        "Preparing":"preparing","准备中...":"preparing",
        "Resuming...":"resuming","恢复中...":"resuming",
        "已暂停":"paused","Paused":"paused","Paused (partial)":"paused",
        "已完成":"completed","Completed":"completed","completed":"completed",
        "registered":"completed",
        "Partially completed (2/3)":"partial","部分完成":"partial",
        "external":"external","verified":"verified","missing":"missing",
        "indexed":"indexed","":"queued","unknown":"queued",
        "already_queued":"queued","already_running":"downloading",
    }
    for inp,exp in tests.items():
        assert WS.normalize(inp).value==exp,f"normalize({inp!r})={WS.normalize(inp).value!r} expected {exp!r}"
    print(f"  ✓ {len(tests)} 条全部归一正确")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
