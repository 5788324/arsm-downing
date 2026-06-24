#!/usr/bin/env python3
"""pause_all 不包含已暂停任务测试."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  pause_all 排除已暂停测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    for rj,st in [("RJ99991","paused"),("RJ99992","queued")]:
        db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3",st,0,100)
    ids=orc.pause_all()
    assert "RJ99991" not in ids,f"paused 不应被再暂停: {ids}"
    assert "RJ99992" in ids,f"queued 应被暂停: {ids}"
    print(f"  ✓ paused 被排除, queued 被暂停: {ids}")
    for rj in ("RJ99991","RJ99992"):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.commit();await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
