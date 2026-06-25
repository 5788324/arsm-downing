#!/usr/bin/env python3
"""auto_resume=False 时冷启动不 enqueue — restore_pending 不 put queue."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  auto_resume=False cold boot no enqueue\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    cfg.auto_resume_on_start = False
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # Simulate 35 restorable RJs (queued + downloading in DB)
    rjs = []
    for i in range(35):
        rj = f"RJ{99020000+i:08d}"
        rjs.append(rj)
        db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "queued", 0, 100)
        db.upsert_download(f"{rj}:t2", rj, "t2", f"/tmp/{rj}/t2.mp3", "downloading", 50, 100)
        db.set_metadata_cache(rj, f"T{i}", "C", "", {"title":f"T{i}"},
            [{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    await orc.restore_pending_downloads()
    await asyncio.sleep(0.1)

    # Verify: queue must be empty
    assert orc.download_queue.empty(), f"queue should be empty, got {orc.download_queue.qsize()}"
    assert len(orc.queued_rj_ids) == 0, f"queued_rj_ids should be empty, got {len(orc.queued_rj_ids)}"

    # Verify: DB queued/downloading → paused
    for rj in rjs[:3]:
        dl = db.get_downloads_summary(rj)
        assert dl.get("paused", 0) >= 2, f"{rj} should have 2 paused, got {dl}"
        assert dl.get("queued", 0) == 0
        assert dl.get("downloading", 0) == 0
        print(f"  ✓ {rj}: paused={dl.get('paused',0)}, queued=0, downloading=0")

    print(f"  ✓ queue empty, queued_rj_ids empty, downloads → paused")

    # Cleanup
    for rj in rjs:
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
