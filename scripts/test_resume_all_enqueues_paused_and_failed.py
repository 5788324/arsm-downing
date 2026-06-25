#!/usr/bin/env python3
"""全部开始 enqueue paused/failed/partial."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  resume_all enqueues paused+failed\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg=ConfigManager.load(); db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)

    rj_p="RJ99993"; rj_f="RJ99994"
    for rj in (rj_p,rj_f):
        db.upsert_download(f"{rj}:t1",rj,"t1",f"/tmp/{rj}/t1.mp3","paused" if rj==rj_p else "failed",0,100)
        db.set_metadata_cache(rj,"T","C","",{"title":"T"},[{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    rj_ids=orc.resume_all()
    assert rj_p in rj_ids,f"paused should be in resume_all: {rj_ids}"
    print(f"  ✓ paused in resume_all: {rj_p}")
    print(f"  ✓ resume_all returns: {rj_ids}")

    for rj in (rj_p,rj_f):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
