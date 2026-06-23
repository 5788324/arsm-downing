#!/usr/bin/env python3
"""pause_all 跳过无效状态测试."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  pause_all 跳过无效状态测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    for rj,st in [("RJ99991","queued"),("RJ99992","completed"),("RJ99993","failed")]:
        db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3",st,0,100)
    # Write metadata_failed works
    db.conn.execute("INSERT OR REPLACE INTO works(rj_id,title,status) VALUES('RJ99990','T','metadata_failed')")
    db.conn.commit()
    ids=orc.pause_all()
    assert "RJ99991" in ids,"queued 应被暂停"
    assert "RJ99992" not in ids,"completed 不应被暂停"
    assert "RJ99993" not in ids,"failed 不应被暂停"
    assert "RJ99990" not in ids,"metadata_failed 不应在 downloads 中因此不参与"
    print(f"  ✓ paused: {ids}, completed/failed 被排除")
    for rj in ("RJ99991","RJ99992","RJ99993","RJ99990"):
        db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,))
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
