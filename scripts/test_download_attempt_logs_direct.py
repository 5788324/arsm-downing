#!/usr/bin/env python3
"""DOWNLOAD_ATTEMPT 日志打印 download_proxy=direct."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  DOWNLOAD_ATTEMPT 日志打印 direct\n{'='*60}\n")

    from core.config import ConfigManager
    from core.orchestrator import Orchestrator
    import inspect

    # ── 1. _stream_with_fallback logs "DOWNLOAD_DIRECT_FAIL" with proxy info ──
    src = inspect.getsource(Orchestrator._stream_with_fallback)
    assert "DOWNLOAD_DIRECT_FAIL" in src, "should log DOWNLOAD_DIRECT_FAIL"
    assert "DOWNLOAD_FALLBACK" in src, "should log DOWNLOAD_FALLBACK"
    print(f"  ✓ DOWNLOAD_DIRECT_FAIL 日志存在")
    print(f"  ✓ DOWNLOAD_FALLBACK 日志存在")

    # ── 2. download_file logs DOWNLOAD_ATTEMPT with download_proxy ──
    src_df = inspect.getsource(Orchestrator.download_file)
    assert "DOWNLOAD_ATTEMPT" in src_df, "should log DOWNLOAD_ATTEMPT"
    assert "download_proxy" in src_df, "should log download_proxy value"
    print(f"  ✓ DOWNLOAD_ATTEMPT 日志含 download_proxy")

    # ── 3. boot_workers logs proxy config ──
    src_bw = inspect.getsource(Orchestrator.boot_workers)
    assert "download_fallback_to_proxy" in src_bw or \
           "download_proxy" in src_bw, \
        "boot_workers should log proxy config"
    print(f"  ✓ boot_workers 日志含 proxy 配置")

    # ── 4. Verify config defaults produce correct log values ──
    cfg = ConfigManager()
    dp = cfg.get_proxy_for('download') or "direct"
    assert dp == "direct", f"default download proxy should be 'direct', got {dp}"
    print(f"  ✓ 默认 download_proxy = {dp}")

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
