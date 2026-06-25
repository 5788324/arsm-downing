#!/usr/bin/env python3
"""pause_generation 递增 — pause_all 后旧 queue items 无效"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  pause generation invalidates old items\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg=ConfigManager.load(); db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)

    gen1 = orc.pause_generation
    orc.pause_all()
    gen2 = orc.pause_generation
    assert gen2 > gen1, f"generation should increase: {gen1} → {gen2}"
    print(f"  ✓ pause_generation: {gen1} → {gen2}")

    # global_paused should be True
    assert orc.global_paused
    print(f"  ✓ global_paused = {orc.global_paused}")
    # queue should be empty
    assert orc.download_queue.empty()
    print(f"  ✓ queue empty after pause")

    await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
