#!/usr/bin/env python3
"""resume 后 progress callback 触发测试 — speed unpaused + emit Queued."""
import asyncio, sys, time; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  resume progress callback 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    events=[];work_events=[]
    orc.set_callbacks(on_progress=events.append,on_work_status=lambda r,s:work_events.append((r,s)))
    rj="RJ99888"
    db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3","paused",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},
        [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])
    orc.speed.pause_work(rj);assert orc.speed.work_speed(rj)==0
    await orc._resume_one(rj)
    orc.speed.update(rj,"t1",0,0);time.sleep(0.3)
    orc.speed.update(rj,"t1",500000,500000)
    ws=orc.speed.work_speed(rj);assert ws>0,f"speed={ws}"
    print(f"  ✓ resume 后 speed: {ws:.0f} B/s")
    dl=[s for _,s in work_events if s=="Downloading"]
    assert dl,f"应有 Queued work event: {work_events}"
    print(f"  ✓ Downloading event: {dl}")
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
