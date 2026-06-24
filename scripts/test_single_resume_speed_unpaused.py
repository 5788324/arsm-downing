#!/usr/bin/env python3
"""resume 后 speed unpaused 测试."""
import asyncio, sys, time; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  resume speed unpaused 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    from core.speed import SpeedTracker
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    import json as _j
    rj="RJ99991"
    db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3","paused",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},
        [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])
    # Simulate pause
    orc.speed.pause_work(rj)
    assert orc.speed.work_speed(rj)==0
    # Resume via unified path
    await orc._resume_one(rj)
    # Feed speed data
    orc.speed.update(rj,"t1",0,0);time.sleep(0.3)
    orc.speed.update(rj,"t1",500000,500000)
    assert orc.speed.work_speed(rj)>0,f"resume后 speed 应为>0, 实际 {orc.speed.work_speed(rj)}"
    print(f"  ✓ resume 后 speed: {orc.speed.work_speed(rj):.0f} B/s")
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
