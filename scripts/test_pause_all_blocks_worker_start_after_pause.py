#!/usr/bin/env python3
"""pause_all 后 worker 不再启动 — global_paused 阻止 WORKER_START."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  pause_all blocks worker start after pause\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # Queue 10 RJs
    rjs = []
    for i in range(10):
        rj = f"RJ{99000000+i:08d}"
        rjs.append(rj)
        db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "queued", 0, 100)
        db.set_metadata_cache(rj, f"T{i}", "C", "", {"title":f"T{i}"},
            [{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])

    db.commit()

    # Enqueue
    for rj in rjs:
        await orc.resume_job(rj)

    assert not orc.download_queue.empty()
    print(f"  queued {len(rjs)} RJs, queue size={orc.download_queue.qsize()}")

    # pause_all
    orc.pause_all()
    assert orc.global_paused == True, "global_paused should be True"
    assert orc.download_queue.empty(), "queue should be empty"
    assert len(orc.queued_rj_ids) == 0, "queued_rj_ids should be empty"
    print(f"  ✓ pause_all: global_paused=True, queue empty, queued_rj_ids empty")

    # Unpaused worker start should be blocked by global_paused
    # Simulate worker: get from queue (empty → no work)
    worker_starts = 0
    while not orc.download_queue.empty():
        try:
            rj_id = orc.download_queue.get_nowait()
            if not orc.global_paused and rj_id not in orc.cancelled_rjs:
                worker_starts += 1
        except asyncio.QueueEmpty:
            break
    assert worker_starts == 0, f"no WORKER_START after pause_all, got {worker_starts}"
    print(f"  ✓ worker start count after pause_all = 0")

    # Cleanup
    for rj in rjs:
        orc.cancelled_rjs.add(rj)
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
