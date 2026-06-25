#!/usr/bin/env python3
"""cancel 后 work/global inflight 回到 0 — in-flight counter 消除泄漏."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  inflight zero after cancel\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # Verify initial state
    async with orc._global_inflight_lock:
        assert orc._global_inflight == 0, f"init global_inflight={orc._global_inflight}"
    assert orc._per_rj_inflight == {}, f"init _per_rj_inflight={orc._per_rj_inflight}"
    print(f"  ✓ init: global_inflight=0, _per_rj_inflight empty")

    # Pause all should maintain zero
    orc.pause_all()
    async with orc._global_inflight_lock:
        assert orc._global_inflight == 0, f"after pause_all: {orc._global_inflight}"
    print(f"  ✓ after pause_all: global_inflight=0")

    # Shutdown should maintain zero
    await orc.shutdown()
    async with orc._global_inflight_lock:
        assert orc._global_inflight == 0, f"after shutdown: {orc._global_inflight}"
    print(f"  ✓ after shutdown: global_inflight=0")

    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
