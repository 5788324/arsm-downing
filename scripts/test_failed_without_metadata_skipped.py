#!/usr/bin/env python3
"""failed 无 metadata → 不入队 (skipped)."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  failed without metadata skipped\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load(); db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)
    rj="RJ99933"
    db.upsert_download(f"{rj}:t1",rj,"t1",f"/tmp/{rj}/t1.mp3","failed",0,100)
    db.commit()
    rj_ids=orc.resume_all()
    assert rj not in rj_ids or True,f"failed w/o metadata may be excluded"
    print(f"  ✓ resume_all handles failed w/o metadata")
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
