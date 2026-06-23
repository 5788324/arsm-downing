#!/usr/bin/env python3
"""no_pending 按钮测试 — 不显示 pause/resume."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  no_pending 按钮测试\n{'='*60}\n")
    from ui.views.download_view import DownloadView
    n=DownloadView.normalize_status
    for s in ("No pending tracks","no_pending","无可恢复文件",
              "No pending tracks to resume"):
        assert n(s)=="no_pending",f"{s!r} → {n(s)!r}"
        print(f"  ✓ {s} → no_pending")
    # ensure no_pending is NOT active or paused
    assert n("no_pending")!="active"
    assert n("no_pending")!="paused"
    print(f"  ✓ no_pending ≠ active/paused")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
