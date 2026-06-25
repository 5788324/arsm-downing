#!/usr/bin/env python3
"""pause_all drain download_queue — queue 为空 + _queued_work_data 清空."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  pause_all drains queue\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    import json

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    rj = "RJ99971"
    db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "queued", 0, 100)
    db.set_metadata_cache(rj, "T", "C", "", {"title":"T"},
        [{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    # Enqueue one job
    await orc.resume_job(rj)
    assert not orc.download_queue.empty(), "queue should have item"
    assert rj in orc._queued_work_data, "should have work_data"
    print(f"  ✓ queued: queue_size=1, work_data=1")

    # pause_all
    orc.pause_all()
    assert orc.download_queue.empty(), f"queue should be empty after drain, size={orc.download_queue.qsize()}"
    assert len(orc._queued_work_data) == 0, f"_queued_work_data should be empty, got {len(orc._queued_work_data)}"
    print(f"  ✓ pause_all: queue empty, work_data cleared")

    # Cleanup
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
