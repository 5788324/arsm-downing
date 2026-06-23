#!/usr/bin/env python3
"""WorkStatus actions 测试 — is_pausable/is_resumable/needs_metadata_retry."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  WorkStatus actions 测试\n{'='*60}\n")
    from core.status import WorkStatus as WS
    # is_pausable
    assert WS.QUEUED.is_pausable and WS.DOWNLOADING.is_pausable and WS.PREPARED.is_pausable
    assert not WS.PAUSED.is_pausable and not WS.COMPLETED.is_pausable
    assert not WS.METADATA_FAILED.is_pausable and not WS.NO_PENDING.is_pausable
    print("  ✓ is_pausable 正确")
    # is_resumable
    assert WS.QUEUED.is_resumable and WS.PAUSED.is_resumable
    assert not WS.COMPLETED.is_resumable and not WS.METADATA_FAILED.is_resumable
    print("  ✓ is_resumable 正确")
    # needs_metadata_retry
    assert WS.METADATA_FAILED.needs_metadata_retry and WS.NO_PENDING.needs_metadata_retry
    assert not WS.PAUSED.needs_metadata_retry
    print("  ✓ needs_metadata_retry 正确")
    # normalize
    for s,exp in [("获取元数据失败",WS.METADATA_FAILED),("No pending tracks",WS.NO_PENDING),
                  ("Queued (cached)",WS.QUEUED),("已暂停",WS.PAUSED)]:
        assert WS.normalize(s)==exp,f"{s}→{WS.normalize(s)} expected {exp}"
    print(f"  ✓ normalize 正确")
    # ui_label
    assert WS.METADATA_FAILED.ui_label=="元数据失败"
    assert WS.PARTIAL.ui_label=="部分完成"
    print(f"  ✓ ui_label 正确")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
