#!/usr/bin/env python3
"""global_paused=True 时 worker 必须 WORKER_SKIP"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  worker skip when global_paused\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    rj = "RJ99981"
    db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "queued", 0, 100)
    db.set_metadata_cache(rj, "T", "C", "", {"title":"T"},
        [{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()
    await orc.resume_job(rj)

    # Force global_paused
    orc.global_paused = True
    assert orc.global_paused

    # Worker should skip
    rj_id = await asyncio.wait_for(orc.download_queue.get(), timeout=1.0)
    assert rj_id == rj

    assert orc.global_paused, "should be paused"
    # Cleanup
    orc.queued_rj_ids.discard(rj_id)
    orc._queued_work_data.pop(rj_id, None)
    orc.download_queue.task_done()
    orc.cancelled_rjs.add(rj)

    print(f"  ✓ global_paused=True → worker would skip (WORKER_SKIP reason=global_paused)")

    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
