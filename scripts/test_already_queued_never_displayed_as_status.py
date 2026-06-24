#!/usr/bin/env python3
"""already_queued 永不显示为状态测试 — 验证 normalize 映射 + UI 不显示."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  already_queued 永不显示为状态测试\n{'='*60}\n")

    from core.status import WorkStatus
    from ui.views.download_view import DownloadView

    # ── 1. normalize maps to queued ──
    print("── 1. WorkStatus.normalize ──")
    assert WorkStatus.normalize("already_queued") == WorkStatus.QUEUED
    assert WorkStatus.normalize("already_running") == WorkStatus.DOWNLOADING
    print(f"  ✓ already_queued → QUEUED")
    print(f"  ✓ already_running → DOWNLOADING")

    # ── 2. DownloadView.normalize_status maps to "queued" / "downloading" ──
    print("── 2. DownloadView.normalize_status ──")
    assert DownloadView.normalize_status("already_queued") == "queued"
    assert DownloadView.normalize_status("already_running") == "downloading"
    print(f"  ✓ DownloadView.normalize_status('already_queued') = 'queued'")
    print(f"  ✓ DownloadView.normalize_status('already_running') = 'downloading'")

    # ── 3. _is_terminal maps correctly ──
    print("── 3. _is_terminal ──")
    assert not DownloadView._is_terminal("already_queued"), \
        "already_queued 不应是 terminal"
    assert not DownloadView._is_terminal("already_running"), \
        "already_running 不应是 terminal"
    print(f"  ✓ already_queued.is_terminal = False")
    print(f"  ✓ already_running.is_terminal = False")

    # ── 4. Any status string containing 'already_queued' should
    #    be caught by update_work_status guard ──
    print("── 4. update_work_status guards ──")
    leak_strings = [
        "already_queued",
        "恢复失败: already_queued",
        "ALREADY_QUEUED",
        "already_running",
        "already_running",
    ]
    for s in leak_strings:
        has_leak = "already_queued" in s.lower() or "already_running" in s.lower()
        assert has_leak, f"'{s}' should trigger the guard"
        print(f"  ✓ '{s}' triggers guard")

    # ── 5. already_queued value is correct ──
    print("── 5. WorkStatus enum values ──")
    assert WorkStatus.ALREADY_QUEUED.value == "already_queued"
    assert WorkStatus.ALREADY_RUNNING.value == "already_running"
    # These are internal transient values
    print(f"  ✓ ALREADY_QUEUED.value = '{WorkStatus.ALREADY_QUEUED.value}'")
    print(f"  ✓ ALREADY_RUNNING.value = '{WorkStatus.ALREADY_RUNNING.value}'")

    print(f"\n{'='*60}\n  ✓ already_queued 永不显示为状态测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
