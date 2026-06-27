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
    ignored_rj = "RJ99110003"; failed_rj = "RJ99110004"
    try:
        db.upsert_download(f"{ignored_rj}:t1", ignored_rj, "t1", f"/tmp/{ignored_rj}/t1.mp3", "ignored", 0, 100)
        db.upsert_download(f"{failed_rj}:t1", failed_rj, "t1", f"/tmp/{failed_rj}/t1.mp3", "failed", 0, 100)
        db.set_metadata_cache(failed_rj, "T", "C", "", {"title": "T"}, [{"type": "audio", "title": "t1", "id": "1", "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])
        db.commit()
        rj_ids = orc.resume_all()
        assert ignored_rj not in rj_ids, rj_ids
        assert failed_rj in rj_ids, rj_ids
        print("PASS resume_all_ignores_ignored_downloads")
        return 0
    finally:
        for rj in (ignored_rj, failed_rj):
            db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
            db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
        db.commit()
        await kernel.shutdown()

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
