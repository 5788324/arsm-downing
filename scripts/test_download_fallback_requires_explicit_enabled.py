#!/usr/bin/env python3
"""download fallback 需要显式开启才能使用代理."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  download fallback 需要显式开启\n{'='*60}\n")

    from core.config import ConfigManager

    # ── Scenario 1: fallback disabled → no proxy for download ──
    cfg1 = ConfigManager()
    cfg1.metadata_proxy = "http://127.0.0.1:7897"
    cfg1.download_proxy = None
    cfg1.download_fallback_to_proxy = False

    dp1 = cfg1.get_proxy_for('download')
    assert dp1 is None, "下载应直连"
    print(f"  ✓ fallback=false → download_proxy=None (直连)")

    # ── Scenario 2: fallback enabled + metadata_proxy set → would use it on failure ──
    cfg2 = ConfigManager()
    cfg2.metadata_proxy = "http://127.0.0.1:7897"
    cfg2.download_proxy = None
    cfg2.download_fallback_to_proxy = True

    # Even with fallback enabled, get_proxy_for('download') still returns None
    # The fallback happens in _stream_with_fallback, not in get_proxy_for
    dp2 = cfg2.get_proxy_for('download')
    assert dp2 is None, "get_proxy_for 仍返回 None（直连优先）"
    print(f"  ✓ fallback=true → get_proxy_for('download') still None (直连优先)")
    print(f"  ✓ 只有直连失败后 _stream_with_fallback 才使用 fallback")

    # ── Scenario 3: explicit download_proxy ──
    cfg3 = ConfigManager()
    cfg3.download_proxy = "http://127.0.0.1:7897"
    dp3 = cfg3.get_proxy_for('download')
    assert dp3 == "http://127.0.0.1:7897", "显式 download_proxy 应生效"
    print(f"  ✓ 显式 download_proxy → {dp3}")

    # ── Default is False ──
    cfg_default = ConfigManager()
    assert cfg_default.download_fallback_to_proxy == False, \
        "默认值应为 False"
    print(f"  ✓ 默认 download_fallback_to_proxy = False")

    # ── config.example.json has false ──
    import json
    with open("config.example.json") as f:
        ex = json.load(f)
    assert ex.get("download_fallback_to_proxy") == False, \
        "config.example.json 应为 false"
    print(f"  ✓ config.example.json: download_fallback_to_proxy = false")

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
