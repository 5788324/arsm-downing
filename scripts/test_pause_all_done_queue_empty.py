#!/usr/bin/env python3
"""pause_all 后 queue empty + queued_rj_ids empty."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  pause_all done queue empty\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg=ConfigManager.load(); db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)

    rj = "RJ99982"
    db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3", "queued", 0, 100)
    db.set_metadata_cache(rj, "T","C","",{"title":"T"},
        [{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()
    await orc.resume_job(rj)

    orc.pause_all()
    assert orc.download_queue.empty(), "queue empty"
    assert len(orc.queued_rj_ids) == 0, "queued_rj_ids empty"
    assert orc.global_paused, "global_paused True"
    print(f"  ✓ queue empty, queued_rj_ids empty, global_paused=True")

    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
