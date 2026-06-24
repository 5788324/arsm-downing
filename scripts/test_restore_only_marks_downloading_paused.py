#!/usr/bin/env python3
"""restore downloading→paused 测试."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  restore downloading→paused 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    for rj,st in [("RJ99991","downloading"),("RJ99992","paused"),("RJ99993","queued")]:
        db.upsert_download(f"{rj}:t",rj,"t",f"/tmp/{rj}/t.mp3",st,500,1000)
    await orc.restore_pending_downloads()
    rows=db.get_downloads_by_rj("RJ99991")
    statuses={r["status"] for r in rows}
    assert "paused" in statuses and "downloading" not in statuses,f"RJ99991: {statuses}"
    rows2=db.get_downloads_by_rj("RJ99992")
    assert rows2[0]["status"]=="paused"
    print(f"  ✓ downloading→paused, paused/queued 保留")
    for rj in ("RJ99991","RJ99992","RJ99993"):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
