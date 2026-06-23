#!/usr/bin/env python3
"""resume_all 调用 resume_job 测试."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  resume_all 调用 resume_job 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    import json as _j
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    for rj in ("RJ99991","RJ99992"):
        db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3","paused",0,100)
        db.set_metadata_cache(rj,"T","C","",{"title":"T"},
            [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])
    async def _batch():
        results=[]
        for rj_id in orc.resume_all():
            r=await orc.resume_job(rj_id)
            results.append((rj_id,r))
        return results
    results=await _batch()
    assert len(results)==2
    for rj_id,r in results:
        assert r["status"]=="resumed",f"{rj_id}: {r}"
    print(f"  ✓ 2/2 resumed")
    for rj in ("RJ99991","RJ99992"):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
