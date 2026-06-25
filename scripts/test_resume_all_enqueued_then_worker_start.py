#!/usr/bin/env python3
"""resume_all enqueued → worker start (global_paused cleared)."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  resume_all enqueued then worker start\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load(); cfg.work_concurrency=2; db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)
    rj="RJ99935"
    db.upsert_download(f"{rj}:t1",rj,"t1",f"/tmp/{rj}/t1.mp3","paused",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},[{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    # Simulate: pause_all then resume_all
    orc.pause_all(); assert orc.global_paused
    stats=await orc._resume_all_async()
    assert not orc.global_paused,f"global_paused should be False, got {orc.global_paused}"
    assert not orc.download_queue.empty(),"queue should have items"
    print(f"  ✓ global_paused=False, queue has items")

    orc.pause_all()
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
