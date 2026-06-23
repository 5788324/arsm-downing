#!/usr/bin/env python3
"""批量暂停可观察测试 — pause_all 后 speed 归零、状态 paused."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  批量暂停可观察测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # Setup: queued + downloading works
    for rj, status in [("RJ99991", "queued"), ("RJ99992", "downloading"),
                        ("RJ99993", "completed")]:
        db.upsert_download(f"{rj}:t1", rj, "t", f"/tmp/{rj}/t.mp3",
                           status, 0, 100)

    # Feed some speed data (need 2 samples for speed calculation)
    orc.speed.update("RJ99992", "t1", 0, 0)
    import time; time.sleep(0.3)
    orc.speed.update("RJ99992", "t1", 500_000, 500_000)
    assert orc.speed.work_speed("RJ99992") > 0, "初始速度应 > 0"
    print(f"  RJ99992 work_speed before pause: {orc.speed.work_speed('RJ99992'):.0f} B/s")

    # Pause all
    orc.pause_all()
    print(f"  RJ99992 work_speed after pause: {orc.speed.work_speed('RJ99992'):.0f} B/s")
    assert orc.speed.work_speed("RJ99992") == 0.0, "暂停后速度应为 0"

    # Check DB states
    for rj, expected in [("RJ99991", "paused"), ("RJ99992", "paused"),
                          ("RJ99993", "completed")]:
        rows = db.get_downloads_by_rj(rj)
        for r in rows:
            assert r["status"] == expected, \
                f"{rj} status={r['status']}, expected={expected}"

    print(f"  ✓ queued/downloading → paused, completed 不变")
    print(f"  ✓ speed 归零")
    await kernel.shutdown()

    # Cleanup
    for rj in ("RJ99991", "RJ99992", "RJ99993"):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.commit()

    print(f"\n{'='*60}")
    print(f"  ✓ 批量暂停可观察测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
