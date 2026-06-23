#!/usr/bin/env python3
"""中文 metadata_failed 按钮测试 — 获取元数据失败 显示 retry_prepare."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  中文 metadata_failed 按钮测试\n{'='*60}\n")
    from ui.views.download_view import DownloadView
    n=DownloadView.normalize_status
    for s in ("获取元数据失败","元数据失败","元数据代理失败",
              "Metadata failed: proxy 127.0.0.1:7890"):
        assert n(s)=="metadata_failed",f"{s!r} → {n(s)!r}"
        print(f"  ✓ {s} → metadata_failed")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
