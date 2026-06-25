#!/usr/bin/env python3
"""冷启动 normalized queued/downloading/resuming → paused."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  startup normalizes queued→paused\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg=ConfigManager.load(); cfg.auto_resume_on_start=False
    db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)

    rj="RJ99991"
    db.upsert_download(f"{rj}:t1",rj,"t1",f"/tmp/{rj}/t1.mp3","queued",0,100)
    db.upsert_download(f"{rj}:t2",rj,"t2",f"/tmp/{rj}/t2.mp3","downloading",30,100)
    db.upsert_download(f"{rj}:t3",rj,"t3",f"/tmp/{rj}/t3.mp3","resuming",10,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},[])
    db.commit()

    await orc.restore_pending_downloads()
    dl=db.get_downloads_summary(rj)
    assert dl.get("paused",0)==3,f"all should be paused, got {dl}"
    print(f"  ✓ {dl} (all paused)")
    assert orc.download_queue.empty()
    print(f"  ✓ queue empty")

    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
