#!/usr/bin/env python3
"""UI 状态过滤测试 — 验证 completed/registered 默认不显示."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  UI 状态过滤测试")
    print(f"{'='*60}\n")

    # Test the DownloadView._is_terminal logic directly
    # (since we can't easily run Flet in headless mode)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ui.views.download_view import DownloadView

    assert DownloadView._is_terminal("已完成")
    assert DownloadView._is_terminal("Completed")
    assert DownloadView._is_terminal("completed")
    assert DownloadView._is_terminal("registered")

    assert not DownloadView._is_terminal("下载中")
    assert not DownloadView._is_terminal("队列排队中")
    assert not DownloadView._is_terminal("已暂停")
    assert not DownloadView._is_terminal("Paused")
    assert not DownloadView._is_terminal("部分完成 (2/3)")
    assert not DownloadView._is_terminal("")

    print("  ✓ _is_terminal 正确过滤 completed/registered")

    # Test _is_failed
    assert DownloadView._is_failed("failed")
    assert DownloadView._is_failed("Failed to fetch metadata")
    assert not DownloadView._is_failed("下载中")
    assert not DownloadView._is_failed("Completed")

    print("  ✓ _is_failed 正确识别失败状态")

    print(f"\n{'='*60}")
    print(f"  ✓ UI 状态过滤测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
