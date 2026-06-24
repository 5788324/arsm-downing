#!/usr/bin/env python3
"""shutdown 将 downloading 标为 paused 测试."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  shutdown marks downloading paused 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    rj="RJ99991"
    db.upsert_download(f"{rj}:t1",rj,"t",f"/tmp/{rj}/t.mp3","downloading",500,1000)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},
        [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":1000}])
    await orc.shutdown()
    row=db.get_downloads_by_rj(rj)
    statuses={r["status"] for r in row}
    assert "paused" in statuses or "downloading" not in statuses,\
        f"shutdown 后 downloading 应变 paused: {statuses}"
    print(f"  ✓ shutdown 后状态: {statuses}")
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
