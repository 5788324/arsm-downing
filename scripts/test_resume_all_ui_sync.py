#!/usr/bin/env python3
"""resume_all UI 同步测试."""

import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  resume_all UI 同步测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator

    cfg = ConfigManager.load(); db = LibraryVault(); kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)
    import json as _j

    for rj, st in [("RJ99991","paused"),("RJ99992","queued"),("RJ99993","completed")]:
        db.upsert_download(f"{rj}:t1", rj, "t", f"/tmp/{rj}/t.mp3", st, 0, 100)
        db.set_metadata_cache(rj, "T", "C", "", {"title":"T"},
            [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])

    rj_ids = orc.resume_all()
    assert len(rj_ids) == 2, f"应为 2 (paused+queued), 实际 {len(rj_ids)}"
    assert "RJ99993" not in rj_ids, "completed 不应被 resume"
    print(f"  ✓ resume_all rj_ids: {rj_ids}")
    print(f"  ✓ completed 不在恢复列表中")

    for rj in ("RJ99991","RJ99992","RJ99993"):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.conn.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__ == "__main__": sys.exit(asyncio.run(test()))
