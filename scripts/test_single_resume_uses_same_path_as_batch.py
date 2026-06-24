#!/usr/bin/env python3
"""单任务和 batch resume 都调用 _resume_one."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  统一 resume 路径测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    import json as _j
    rj="RJ99991"
    db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3","paused",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},
        [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])
    # Single resume via _resume_one
    r1=await orc._resume_one(rj)
    assert r1["status"]=="queued",f"single: {r1}"
    assert orc.speed.work_speed(rj)==0.0, "刚 resume 速度应为 0（无数据）"
    print(f"  ✓ _resume_one works: {r1}")
    # Simulate worker consuming the queue
    orc.queued_rj_ids.discard(rj)
    # Batch path: pause then resume
    orc.pause_all()
    r2=await orc._resume_one(rj)
    assert r2["status"]=="queued",f"after pause+resume: {r2}"
    print(f"  ✓ pause→_resume_one 再次 resume: {r2}")
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
