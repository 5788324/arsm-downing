#!/usr/bin/env python3
"""有 pending downloads 时不提示没有可恢复任务."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  resume_all has tasks when pending\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg=ConfigManager.load(); db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)

    rj="RJ99995"
    db.upsert_download(f"{rj}:t1",rj,"t1",f"/tmp/{rj}/t1.mp3","paused",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},[{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    rj_ids=orc.resume_all()
    assert len(rj_ids)>0,f"should find restorable tasks, got {rj_ids}"
    assert rj in rj_ids
    print(f"  ✓ resume_all found {len(rj_ids)} restorable RJs")

    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
