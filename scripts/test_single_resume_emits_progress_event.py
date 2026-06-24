#!/usr/bin/env python3
"""resume 后 emit downloading 测试."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  resume emit downloading 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    import json as _j
    emitted={};orc.set_callbacks(lambda e:None,lambda r,s:emitted.update({r:s}))
    rj="RJ99991"
    db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3","paused",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},
        [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])
    r=await orc._resume_one(rj)
    assert r["status"]=="resumed"
    assert emitted.get(rj)=="Downloading",f"应在 resume 后 emit Downloading, 实际: {emitted.get(rj)}"
    print(f"  ✓ emit: {emitted[rj]}")
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
