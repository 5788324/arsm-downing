#!/usr/bin/env python3
"""show_completed 开关保持活跃项测试 — 验证切换不丢失 paused/queued etc."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  show_completed 开关保持活跃项测试\n{'='*60}\n")

    from core.status import WorkStatus
    from ui.views.download_view import DownloadView

    # ── 1. _is_terminal covers only: completed, registered, verified, external ──
    print("── 1. _is_terminal vs WorkStatus.is_terminal ──")
    terminal_vals = ["completed", "registered", "verified", "external", "indexed"]
    non_terminal_vals = ["queued", "downloading", "paused", "failed",
                         "metadata_failed", "no_pending", "partial",
                         "preparing", "prepared", "resuming"]

    for v in terminal_vals:
        ws = WorkStatus[v.upper()] if v.upper() in WorkStatus.__members__ else None
        if ws:
            assert ws.is_terminal, f"{v} should be terminal"
            assert DownloadView._is_terminal(v), f"_is_terminal({v}) should be True"
            print(f"  ✓ {v} is terminal ({ws.is_terminal})")
        else:
            print(f"  - {v} not in WorkStatus enum (skipped)")

    for v in non_terminal_vals:
        ws = WorkStatus[v.upper()] if v.upper() in WorkStatus.__members__ else None
        if ws:
            assert not ws.is_terminal, f"{v} should NOT be terminal"
            assert not DownloadView._is_terminal(v), f"_is_terminal({v}) should be False"
            print(f"  ✓ {v} is NOT terminal ({ws.is_terminal})")
        else:
            print(f"  - {v} not in WorkStatus enum (skipped)")

    # ── 2. Chinese status strings ──
    print("\n── 2. 中文状态字符串 ──")
    # paused should NOT be terminal
    assert not DownloadView._is_terminal("已暂停"), "已暂停 should NOT be terminal"
    print(f"  ✓ '已暂停' is NOT terminal")
    # completed should be terminal
    assert DownloadView._is_terminal("已完成"), "已完成 should be terminal"
    print(f"  ✓ '已完成' is terminal")
    # queued should NOT be terminal
    assert not DownloadView._is_terminal("队列中"), "队列中 should NOT be terminal"
    print(f"  ✓ '队列中' is NOT terminal")
    # partial should NOT be terminal
    assert not DownloadView._is_terminal("部分完成"), "部分完成 should NOT be terminal"
    print(f"  ✓ '部分完成' is NOT terminal")
    # failed should NOT be terminal
    assert not DownloadView._is_terminal("错误: xyz"), "错误 should NOT be terminal"
    print(f"  ✓ '错误: ...' is NOT terminal")
    # metadata_failed should NOT be terminal
    assert not DownloadView._is_terminal("获取元数据失败"), "元数据失败 should NOT be terminal"
    print(f"  ✓ '获取元数据失败' is NOT terminal")
    # external should be terminal (hidden when show_completed=false)
    assert DownloadView._is_terminal("external"), "external should be terminal"
    assert DownloadView._is_terminal("外部资源"), "外部资源 should be terminal"
    print(f"  ✓ 'external' / '外部资源' is terminal")

    print(f"\n{'='*60}\n  ✓ show_completed 开关保持活跃项测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
