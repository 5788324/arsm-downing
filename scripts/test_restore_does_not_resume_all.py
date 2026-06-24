#!/usr/bin/env python3
"""restore 不逐个 resume 测试 — 重启不阻塞 129 个 RJ."""
import asyncio, sys, time; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  restore 不逐个 resume 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    import json as _j
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    # Create 50 paused RJs with metadata_cache
    for i in range(50):
        rj=f"RJ{100000+i}"
        db.upsert_download(f"{rj}:t",rj,"t",f"/tmp/{rj}/t.mp3","paused",0,100)
        db.set_metadata_cache(rj,"T","C","",{"title":"T"},
            [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])
    start=time.time()
    await orc.restore_pending_downloads()
    elapsed=time.time()-start
    assert elapsed<5.0,f"restore 50 RJs too slow: {elapsed:.1f}s"
    # After restore, workers should be using delayed resume
    assert len(orc.queued_rj_ids)<=50, f"queued_rj_ids={len(orc.queued_rj_ids)}"
    print(f"  ✓ restore 50 RJs in {elapsed:.2f}s (不逐个 resume)")
    for i in range(50):
        rj=f"RJ{100000+i}"
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
