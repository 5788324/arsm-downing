#!/usr/bin/env python3
"""resume_all 重开 global_paused=False — 新任务可以正常启动."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  resume_all reopens global_paused\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load(); db = LibraryVault(); kernel = NetworkKernel(cfg); orc = Orchestrator(kernel, cfg, db)

    rj = "RJ99984"
    db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "paused", 0, 100)
    db.set_metadata_cache(rj, "T","C","",{"title":"T"},
        [{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    # pause_all then resume
    orc.pause_all()
    assert orc.global_paused
    stats = await orc._resume_all_async()
    assert not orc.global_paused, f"global_paused should be False after resume, got {orc.global_paused}"
    print(f"  ✓ resume_all: global_paused=False, stats={stats}")

    # New queue should be filled
    assert not orc.download_queue.empty(), "queue should have items after resume"
    print(f"  ✓ queue has items after resume")

    orc.pause_all()
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
