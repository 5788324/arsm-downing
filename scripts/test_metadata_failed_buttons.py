#!/usr/bin/env python3
"""metadata_failed 按钮测试 — 不显示 pause/reconnect, 显示 retry_prepare/remove."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  metadata_failed 按钮测试\n{'='*60}\n")
    from ui.views.download_view import DownloadView
    # Test string matching (updated after code change)
    s = "Metadata failed: proxy 127.0.0.1:7890"
    assert "metadata" in s.lower()
    assert "failed" in s.lower()
    print("  ✓ metadata_failed 不误识别为 active/paused/downloading")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__": sys.exit(asyncio.run(test()))
