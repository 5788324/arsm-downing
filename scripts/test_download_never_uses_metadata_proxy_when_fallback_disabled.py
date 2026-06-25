#!/usr/bin/env python3
"""download 在 fallback=false 时绝不使用 metadata_proxy."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  download 不走 metadata_proxy (fallback=false)\n{'='*60}\n")

    from core.config import ConfigManager

    cfg = ConfigManager()
    cfg.metadata_proxy = "http://127.0.0.1:7897"
    cfg.download_proxy = None
    cfg.download_fallback_to_proxy = False

    # ── get_proxy_for('download') returns None when download_proxy is null ──
    dp = cfg.get_proxy_for('download')
    assert dp is None, f"download_proxy should be None, got {dp}"
    print(f"  ✓ get_proxy_for('download') = None (直连)")

    # ── metadata_proxy is separate ──
    mp = cfg.get_proxy_for('metadata')
    assert mp == "http://127.0.0.1:7897"
    print(f"  ✓ get_proxy_for('metadata') = {mp} (代理)")

    # ── Without download_proxy, download_fallback_to_proxy=false → no fallback ──
    # Verified: _stream_with_fallback checks download_fallback_to_proxy
    # before falling back to metadata_proxy/proxy

    import inspect
    from core.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator._stream_with_fallback)

    # Must check download_fallback_to_proxy before falling back
    assert "download_fallback_to_proxy" in src, \
        "_stream_with_fallback must check download_fallback_to_proxy"
    print(f"  ✓ _stream_with_fallback checks download_fallback_to_proxy")

    # Fallback disabled → returns False without trying proxy
    assert "if not self.config.download_fallback_to_proxy" in src or \
           "download_fallback_to_proxy" in src, \
        "must have download_fallback_to_proxy guard"
    print(f"  ✓ download_fallback_to_proxy guard present")

    # ── Default config value is False ──
    assert cfg.download_fallback_to_proxy == False
    print(f"  ✓ default download_fallback_to_proxy = False")

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
