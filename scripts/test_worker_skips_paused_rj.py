#!/usr/bin/env python3
"""worker 跳过 paused RJ — _is_ready_to_download 返回 False."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  worker skips paused RJ\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # All downloads paused → not ready
    rj = "RJ99972"
    db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "paused", 0, 100)
    db.commit()

    assert not orc._is_ready_to_download(rj), "all paused → not ready"
    print(f"  ✓ paused → _is_ready_to_download = False")

    # Mixed: one queued → ready
    rj2 = "RJ99973"
    db.upsert_download(f"{rj2}:t1", rj2, "t1", f"/tmp/{rj2}/t1.mp3", "queued", 0, 100)
    db.upsert_download(f"{rj2}:t2", rj2, "t2", f"/tmp/{rj2}/t2.mp3", "completed", 100, 100)
    db.commit()
    assert orc._is_ready_to_download(rj2), "has queued → ready"
    print(f"  ✓ queued → _is_ready_to_download = True")

    # All completed → not ready
    rj3 = "RJ99974"
    db.upsert_download(f"{rj3}:t1", rj3, "t1", f"/tmp/{rj3}/t1.mp3", "completed", 100, 100)
    db.commit()
    assert not orc._is_ready_to_download(rj3), "all completed → not ready"
    print(f"  ✓ completed → _is_ready_to_download = False")

    # Cleanup
    for rj in (rj, rj2, rj3):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
