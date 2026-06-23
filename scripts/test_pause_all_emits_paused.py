#!/usr/bin/env python3
"""pause_all emit paused 测试 — 验证 speed=0, status=paused."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  pause_all emit paused 测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # Setup: queued + downloading
    for rj, status in [("RJ99991", "queued"), ("RJ99992", "downloading")]:
        db.upsert_download(f"{rj}:t1", rj, "t", f"/tmp/{rj}/t.mp3",
                           status, 0, 100)

    import time
    orc.speed.update("RJ99992", "t1", 0, 0)
    time.sleep(0.3)
    orc.speed.update("RJ99992", "t1", 500_000, 500_000)

    # Capture emitted statuses
    emitted = {}

    def on_progress(e):
        pass

    def on_work_status(rj_id, status):
        emitted[rj_id] = status

    orc.set_callbacks(on_progress, on_work_status)

    # Pause all
    orc.pause_all()

    # Check: speed zero
    assert orc.speed.work_speed("RJ99992") == 0.0, "speed 应为 0"
    # Check: emitted "Paused" for each
    assert emitted.get("RJ99991") == "Paused", f"RJ99991: {emitted.get('RJ99991')}"
    assert emitted.get("RJ99992") == "Paused", f"RJ99992: {emitted.get('RJ99992')}"
    print(f"  ✓ pause_all emit Paused: {emitted}")
    print(f"  ✓ speed=0")

    # Cleanup
    for rj in ("RJ99991", "RJ99992"):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}")
    print(f"  ✓ pause_all emit paused 测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
