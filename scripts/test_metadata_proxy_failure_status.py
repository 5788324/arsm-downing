#!/usr/bin/env python3
"""metadata_proxy 失败状态测试."""

import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  metadata_proxy 失败状态测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    cfg.metadata_proxy = "http://127.0.0.1:19999"  # dead port
    cfg.proxy = None
    db = LibraryVault(); kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    emitted = {}
    def on_ws(rj_id, st):
        emitted[rj_id] = st
    orc.set_callbacks(lambda e: None, on_ws)

    import aiohttp
    original = kernel.fetch
    async def fake_fetch(*a, **kw):
        raise aiohttp.ClientConnectionError("Connection refused")
    kernel.fetch = fake_fetch

    meta, targets, root, cached = await orc.prepare_work("RJ99999")
    assert meta is None
    st = emitted.get("RJ99999", "")
    assert "Failed" in st or "failed" in st.lower()
    print(f"  ✓ status: {st}")

    kernel.fetch = original
    await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__ == "__main__": sys.exit(asyncio.run(test()))
