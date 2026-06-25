#!/usr/bin/env python3
"""集成测试: boot_workers + pause_all → 无新 WORKER_START."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  integration: no WORKER_START after pause\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    cfg.work_concurrency = 2
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # Track work_status emits
    work_starts = []
    def track_ws(rj_id, st):
        if st == "Downloading":
            work_starts.append(rj_id)
    orc.set_callbacks(on_progress=lambda e: None, on_work_status=track_ws)

    # Queue 10 RJs
    rjs = []
    for i in range(10):
        rj = f"RJ{99010000+i:08d}"
        rjs.append(rj)
        db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "queued", 0, 100)
        db.set_metadata_cache(rj, f"T{i}", "C", "", {"title":f"T{i}"},
            [{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    for rj in rjs:
        await orc.resume_job(rj)
    print(f"  queued {len(rjs)} RJs")

    # Start workers
    worker_tasks = await orc.boot_workers()
    await asyncio.sleep(0.3)  # let workers pick up tasks

    # Pause all
    work_starts.clear()
    orc.pause_all()
    await asyncio.sleep(0.5)  # let cancellations propagate

    # Stop workers
    orc._shutting_down = True
    for t in worker_tasks:
        t.cancel()
    await asyncio.sleep(0.2)

    # Verify: no Downloading emit after pause_all
    after_pause = len(work_starts)
    print(f"  WORKER_START after pause_all: {after_pause}")
    assert after_pause == 0, f"no new Downloading after pause_all, got {after_pause}"

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
