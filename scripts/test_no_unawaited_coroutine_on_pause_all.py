#!/usr/bin/env python3
"""pause_all 不产生 unawaited coroutine RuntimeWarning."""
import asyncio, sys, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  pause_all 无 RuntimeWarning\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    rj = "RJ99975"
    db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "queued", 0, 100)
    db.set_metadata_cache(rj, "T", "C", "", {"title":"T"},
        [{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    # Enqueue
    await orc.resume_job(rj)
    print(f"  queue size: {orc.download_queue.qsize()}")

    # pause_all with RuntimeWarning → error
    warnings.simplefilter("error", RuntimeWarning)
    try:
        orc.pause_all()
    except RuntimeWarning as e:
        print(f"  ✗ RuntimeWarning raised: {e}")
        return 1

    # Verify queue is drained
    assert orc.download_queue.empty(), "queue should be empty"

    print(f"  ✓ no RuntimeWarning, queue empty")

    # Cleanup
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
