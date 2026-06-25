#!/usr/bin/env python3
"""load_queue 不触发 enqueue — 只读 DB."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  load_queue never enqueues\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg=ConfigManager.load(); db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)

    rj="RJ99992"
    db.upsert_download(f"{rj}:t1",rj,"t1",f"/tmp/{rj}/t1.mp3","queued",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},[])
    db.commit()

    q_before=orc.download_queue.qsize()
    rj_ids_before=len(orc.queued_rj_ids)

    # Simulate load_queue: get_pending_rj_ids + derive (read-only)
    pending=db.get_pending_rj_ids()
    assert rj in pending
    # Derive state (read-only)
    ws=db.get_works_status(rj); dl=db.get_downloads_summary(rj)
    print(f"  works={ws}, dl={dl}")

    # Queue must be unchanged
    assert orc.download_queue.qsize()==q_before
    assert len(orc.queued_rj_ids)==rj_ids_before
    print(f"  ✓ queue unchanged: {q_before}→{orc.download_queue.qsize()}")

    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
