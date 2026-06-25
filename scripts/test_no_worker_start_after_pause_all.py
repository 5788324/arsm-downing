#!/usr/bin/env python3
"""pause_all 后不出现新 WORKER_START — worker 跳过 paused RJ."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  no WORKER_START after pause_all\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    rj = "RJ99977"
    db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "queued", 0, 100)
    db.set_metadata_cache(rj, "T", "C", "", {"title":"T"},
        [{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    # Enqueue
    await orc.resume_job(rj)
    assert rj in orc.queued_rj_ids, "should be in queued_rj_ids"
    assert not orc.download_queue.empty(), "queue should have item"

    # pause_all drains queue
    orc.pause_all()

    # Verify: queue empty, queued_rj_ids empty
    assert orc.download_queue.empty(), "queue should be empty after pause_all"
    assert rj not in orc.queued_rj_ids, "should not be in queued_rj_ids"
    assert len(orc._queued_work_data) == 0, "work_data should be empty"
    print(f"  ✓ queue empty, queued_rj_ids cleared, work_data cleared")

    # Worker should NOT start this RJ (not in queue, not in work_data)
    assert not orc._is_ready_to_download(rj), "should not be ready after pause_all"
    print(f"  ✓ _is_ready_to_download = False → no WORKER_START")

    # Cleanup
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
