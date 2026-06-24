#!/usr/bin/env python3
"""防止重复入队测试 — 同一个 RJ 不会被 resume 入队两次."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  防重复入队测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    import json as _j
    rj="RJ99991"
    db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3","paused",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},
        [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])
    r1=await orc._resume_one(rj)
    assert r1["status"]=="resumed",f"first: {r1}"
    assert rj in orc.queued_rj_ids,"入队后应在 queued_rj_ids"
    # Second resume should be blocked
    r2=await orc._resume_one(rj)
    assert r2["status"]=="already_queued",f"second: {r2}"
    print(f"  ✓ 第一次: {r1['status']}, 第二次: {r2['status']}")
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
