#!/usr/bin/env python3
"""pause_all UI 同步测试."""

import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  pause_all UI 同步测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator

    cfg = ConfigManager.load(); db = LibraryVault(); kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)
    emitted = {}

    def on_ws(rj_id, st):
        emitted[rj_id] = st

    orc.set_callbacks(lambda e: None, on_ws)
    for rj in ("RJ99991", "RJ99992"):
        db.upsert_download(f"{rj}:t1", rj, "t", f"/tmp/{rj}/t.mp3", "queued", 0, 100)

    orc.speed.update("RJ99991", "t1", 0, 0); time.sleep(0.3)
    orc.speed.update("RJ99991", "t1", 500_000, 500_000)

    ids = orc.pause_all()
    assert len(ids) == 2
    assert emitted.get("RJ99991") == "Paused"
    assert emitted.get("RJ99992") == "Paused"
    assert orc.speed.work_speed("RJ99991") == 0.0
    print(f"  ✓ {len(ids)} works paused, all emit Paused, speed=0")

    for rj in ("RJ99991","RJ99992"):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__ == "__main__": sys.exit(asyncio.run(test()))
