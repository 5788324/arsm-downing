#!/usr/bin/env python3
"""全遗留字符串归一测试 — 所有 legacy 状态通过 WorkStatus.normalize."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  全遗留字符串归一测试\n{'='*60}\n")
    from core.status import WorkStatus as WS
    tests={
        "metadata_failed":WS.METADATA_FAILED,"Metadata failed":WS.METADATA_FAILED,
        "Metadata failed: proxy http://x":WS.METADATA_FAILED,
        "获取元数据失败":WS.METADATA_FAILED,"元数据失败":WS.METADATA_FAILED,
        "元数据代理失败":WS.METADATA_FAILED,
        "No pending tracks":WS.NO_PENDING,"no_pending":WS.NO_PENDING,
        "No pending tracks to resume":WS.NO_PENDING,"无可恢复文件":WS.NO_PENDING,
        "重复 (跳过)":WS.DUPLICATE,"Duplicate: /tmp/x":WS.DUPLICATE,
        "failed":WS.FAILED,"Failed to fetch":WS.FAILED,"下载失败":WS.FAILED,
        "Error: x":WS.FAILED,
        "队列中":WS.QUEUED,"Queued":WS.QUEUED,"Queued (cached)":WS.QUEUED,
        "下载中":WS.DOWNLOADING,"Downloading":WS.DOWNLOADING,
        "Prepared":WS.PREPARED,"已就绪":WS.PREPARED,
        "Preparing":WS.PREPARING,"准备中...":WS.PREPARING,
        "Resuming...":WS.RESUMING,"恢复中...":WS.RESUMING,
        "已暂停":WS.PAUSED,"Paused":WS.PAUSED,"Paused (partial)":WS.PAUSED,
        "已完成":WS.COMPLETED,"Completed":WS.COMPLETED,"completed":WS.COMPLETED,
        "registered":WS.COMPLETED,
        "Partially completed (2/3)":WS.PARTIAL,"部分完成":WS.PARTIAL,
        "external":WS.EXTERNAL,"verified":WS.VERIFIED,"missing":WS.MISSING,
        "indexed":WS.INDEXED,"":WS.QUEUED,"unknown":WS.QUEUED,
    }
    for inp,exp in tests.items():
        assert WS.normalize(inp)==exp,f"{inp!r}→{WS.normalize(inp)} expected {exp}"
    print(f"  ✓ {len(tests)} 条遗留状态全部归一正确")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
