#!/usr/bin/env python3
"""集成: boot_workers + restore_pending(auto_resume=False) → 无 WORKER_START."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  integration: no WORKER_START on cold boot\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg=ConfigManager.load(); cfg.auto_resume_on_start=False
    db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)

    work_starts=[]
    def track_ws(rj_id,st):
        if st=="Downloading":work_starts.append(rj_id)
    orc.set_callbacks(on_progress=lambda e:None,on_work_status=track_ws)

    rjs=[]
    for i in range(10):
        rj=f"RJ{99030000+i:08d}"; rjs.append(rj)
        db.upsert_download(f"{rj}:t1",rj,"t1",f"/tmp/{rj}/t1.mp3","downloading",30,100)
        db.set_metadata_cache(rj,f"T{i}","C","",{"title":f"T{i}"},[{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    # Cold boot: restore + workers
    await orc.restore_pending_downloads()
    worker_tasks=await orc.boot_workers()
    await asyncio.sleep(1.0)

    orc._shutting_down=True
    for t in worker_tasks:t.cancel()
    await asyncio.sleep(0.2)

    assert len(work_starts)==0,f"no WORKER_START on cold boot, got {len(work_starts)}"
    print(f"  ✓ WORKER_START count after cold boot = 0")

    for rj in rjs:
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
