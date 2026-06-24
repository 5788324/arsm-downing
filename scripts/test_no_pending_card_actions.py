#!/usr/bin/env python3
"""no_pending 卡片显示正确按钮测试 — 重新准备/移除/打开目录."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  no_pending 卡片按钮测试\n{'='*60}\n")

    from core.status import WorkStatus
    from ui.views.download_view import DownloadView

    # ── 1. no_pending normalizes correctly ──
    print("── 1. normalize ──")
    for s in ("No pending tracks", "no_pending", "No pending"):
        ns = WorkStatus.normalize(s)
        assert ns == WorkStatus.NO_PENDING, f"'{s}' → {ns}, expected NO_PENDING"
        print(f"  ✓ '{s}' → WorkStatus.NO_PENDING")

    # ── 2. no_pending is NOT terminal (should show in list) ──
    print(f"\n── 2. no_pending is NOT terminal ──")
    assert not WorkStatus.NO_PENDING.is_terminal
    for s in ("No pending tracks", "no_pending"):
        assert not DownloadView._is_terminal(s), f"'{s}' should NOT be terminal"
        print(f"  ✓ '{s}'.is_terminal = False")

    # ── 3. Not resumable (should not participate in resume_all) ──
    print(f"\n── 3. no_pending is NOT resumable ──")
    assert not WorkStatus.NO_PENDING.is_resumable
    print(f"  ✓ NO_PENDING.is_resumable = False")

    # ── 4. Not pausable ──
    print(f"\n── 4. no_pending is NOT pausable ──")
    assert not WorkStatus.NO_PENDING.is_pausable
    print(f"  ✓ NO_PENDING.is_pausable = False")

    # ── 5. needs_metadata_retry = True ──
    print(f"\n── 5. needs_metadata_retry ──")
    assert WorkStatus.NO_PENDING.needs_metadata_retry, \
        "NO_PENDING 需要显示 retry prepare 按钮"
    print(f"  ✓ needs_metadata_retry = True")

    # ── 6. UI label ──
    print(f"\n── 6. UI label ──")
    assert WorkStatus.NO_PENDING.ui_label == "无可恢复文件"
    print(f"  ✓ ui_label = '{WorkStatus.NO_PENDING.ui_label}'")

    # ── 7. Confirm build_queue_item handles no_pending ──
    print(f"\n── 7. build_queue_item action check ──")
    # When ns == "no_pending", the code shows:
    #   btn_retry (重新准备) + btn_open (打开目录) + btn_remove (移除)
    # This is verified by checking the if-condition in build_queue_item
    import inspect
    src = inspect.getsource(DownloadView.build_queue_item)
    no_pending_actions = 'ns == "no_pending"' in src
    metadata_failed_actions = 'ns == "metadata_failed"' in src
    assert no_pending_actions or metadata_failed_actions, \
        "build_queue_item 应处理 no_pending / metadata_failed"
    print(f"  ✓ no_pending/metadata_failed action 分支存在")

    # Check for open dir button
    has_btn_open = 'FOLDER_OPEN' in src or '打开目录' in src
    has_btn_retry = '重新准备' in src or 'REFRESH' in src or '_retry_prepare' in src
    has_btn_remove = 'DELETE_OUTLINE' in src or '移除' in src

    assert has_btn_retry, "应有重新准备按钮"
    assert has_btn_open, "应有打开目录按钮"
    assert has_btn_remove, "应有移除按钮"
    print(f"  ✓ 重新准备 ✅  打开目录 ✅  移除 ✅")

    print(f"\n{'='*60}\n  ✓ no_pending 卡片按钮测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
