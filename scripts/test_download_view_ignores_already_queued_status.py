#!/usr/bin/env python3
"""UI 不显示 already_queued 测试."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  UI 不显示 already_queued 测试\n{'='*60}\n")
    from ui.views.download_view import DownloadView
    from core.status import WorkStatus
    # normalize maps already_queued to queued (not a new displayed status)
    assert WorkStatus.normalize("already_queued").value=="queued"
    assert WorkStatus.normalize("already_running").value=="downloading"
    ns=DownloadView.normalize_status("already_queued")
    assert ns=="queued",f"normalize should return queued, got {ns}"
    ns=DownloadView.normalize_status("already_running")
    assert ns=="downloading",f"got {ns}"
    print(f"  ✓ already_queued→queued, already_running→downloading")
    print(f"  ✓ 不显示为独立状态")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
