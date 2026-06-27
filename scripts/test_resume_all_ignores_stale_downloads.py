#!/usr/bin/env python3
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load(); db = LibraryVault(); kernel = NetworkKernel(cfg); orc = Orchestrator(kernel, cfg, db)
    stale_rj = "RJ99110001"; paused_rj = "RJ99110002"
    try:
        db.upsert_download(f"{stale_rj}:t1", stale_rj, "t1", f"/tmp/{stale_rj}/t1.mp3", "stale", 0, 100)
        db.upsert_download(f"{paused_rj}:t1", paused_rj, "t1", f"/tmp/{paused_rj}/t1.mp3", "paused", 0, 100)
        db.set_metadata_cache(paused_rj, "T", "C", "", {"title": "T"}, [{"type": "audio", "title": "t1", "id": "1", "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])
        db.commit()
        rj_ids = orc.resume_all()
        assert stale_rj not in rj_ids, rj_ids
        assert paused_rj in rj_ids, rj_ids
        print("PASS resume_all_ignores_stale_downloads")
        return 0
    finally:
        for rj in (stale_rj, paused_rj):
            db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
            db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
        db.commit()
        await kernel.shutdown()

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
