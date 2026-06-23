#!/usr/bin/env python3
"""队列加载防重复测试 — 验证 terminal 任务不被重新启动."""

import asyncio
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  队列加载防重复测试")
    print(f"{'='*60}\n")

    # ── 1. Test _is_terminal covers all terminal states ──
    from ui.views.download_view import DownloadView
    print("── 1. _is_terminal 覆盖所有终端状态 ──")
    for status in ("已完成", "Completed", "completed", "registered"):
        assert DownloadView._is_terminal(status), \
            f"{status} 应为 terminal"
        print(f"  ✓ {status} → terminal")

    for status in ("队列中", "下载中", "已暂停", "Paused",
                   "获取元数据中...", "queued", "downloading", "failed"):
        assert not DownloadView._is_terminal(status), \
            f"{status} 不应为 terminal"
        print(f"  ✓ {status} → non-terminal")

    # ── 2. Write a queue.json with mixed states ──
    print("\n── 2. 模拟 queue.json 含 terminal 任务 ──")
    import ui.views.download_view as dv
    original_file = dv.QUEUE_FILE
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    dv.QUEUE_FILE = Path(tmp.name)

    saved = {
        "88880": {"status": "已完成", "tracks": {}},
        "88881": {"status": "下载中", "tracks": {}},
        "88882": {"status": "Completed", "tracks": {}},
        "88883": {"status": "已暂停", "tracks": {}},
    }
    with open(dv.QUEUE_FILE, "w") as f:
        json.dump(saved, f)

    # ── 3. load_queue should skip terminal, keep active ──
    print("── 3. 调用 load_queue ──")
    class FakeApp:
        start_call = 0
        def start_download(self, rj):
            FakeApp.start_call += 1
        def resume_download(self, rj):
            pass
        def cancel_download(self, rj):
            pass
        def pause_download(self, rj):
            pass

    view = DownloadView.__new__(DownloadView)
    view.app_controller = FakeApp()
    view.active_downloads = {}
    view.queue_list = type('obj', (object,), {
        'controls': [], 'update': lambda: None})()

    # Mock build_queue_item to just add to active_downloads
    def mock_build(rj):
        view.active_downloads[rj] = {"status": view.active_downloads.get(rj, {}).get("status", ""), "tracks": {}}
    view.build_queue_item = mock_build
    view.save_queue = lambda: None

    view.load_queue()

    print(f"  loaded: {list(view.active_downloads.keys())}")
    print(f"  start_download calls: {FakeApp.start_call}")

    assert "RJ88880" not in view.active_downloads, "已完成 应被跳过"
    assert "RJ88882" not in view.active_downloads, "Completed 应被跳过"
    assert "RJ88881" in view.active_downloads, "下载中 应被加载"
    assert "RJ88883" in view.active_downloads, "已暂停 应被加载"
    assert FakeApp.start_call == 0, \
        "不应调用 start_download (应交给 Orchestrator 恢复)"

    print("  ✓ terminal 任务未被加载")
    print("  ✓ 无重复 start_download 调用")

    # Cleanup
    dv.QUEUE_FILE = original_file
    import os as _os
    _os.unlink(tmp.name)

    print(f"\n{'='*60}")
    print(f"  ✓ 队列加载防重复测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
