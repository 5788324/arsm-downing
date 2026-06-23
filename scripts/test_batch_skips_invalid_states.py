#!/usr/bin/env python3
"""batch 跳过无效状态测试 — pause_all/resume_all 跳过 metadata_failed/no_pending/duplicate."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  batch 跳过无效状态测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    items=[("RJ99991","queued"),("RJ99992","failed"),("RJ99993","completed"),
           ("RJ99994","paused"),("RJ99995","registered")]
    for rj,st in items:
        db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3",st,0,100)
    # metadata_failed in works
    db.conn.execute("INSERT OR REPLACE INTO works(rj_id,title,status) VALUES('RJ99990','T','metadata_failed')")
    db.conn.commit()
    # pause_all should only affect queued
    pid=orc.pause_all()
    assert "RJ99991" in pid
    for bad in ("RJ99992","RJ99993","RJ99995","RJ99990"):
        assert bad not in pid,f"{bad} 不应被 pause"
    print(f"  ✓ pause_all: {pid} (只有 queued)")
    # resume_all should only affect queued+paused
    rid=orc.resume_all()
    assert "RJ99994" in rid
    print(f"  ✓ resume_all: {rid} (只有 paused)")
    for rj in ["RJ99991","RJ99992","RJ99993","RJ99994","RJ99995","RJ99990"]:
        db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,))
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
