#!/usr/bin/env python3
"""already_queued 不持久化测试."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  already_queued 不持久化测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    import json as _j
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    rj="RJ99991"
    db.upsert_download(f"{rj}:t",rj,"t",f"/tmp/{rj}/t.mp3","paused",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},
        [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])
    r1=await orc._resume_one(rj);assert r1["status"]=="queued"
    r2=await orc._resume_one(rj);assert r2["status"]=="already_queued"
    # Check DB: no already_queued status
    rows=db.get_downloads_by_rj(rj)
    for r in rows:
        assert r["status"]!="already_queued",f"DB 不应有 already_queued: {r['status']}"
    print(f"  ✓ DB 无 already_queued")
    # Check normalize
    from core.status import WorkStatus
    assert WorkStatus.normalize("already_queued")==WorkStatus.QUEUED
    print(f"  ✓ normalize(already_queued)→queued")
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
