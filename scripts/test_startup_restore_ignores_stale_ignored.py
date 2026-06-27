#!/usr/bin/env python3
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load(); cfg.auto_resume_on_start = False
    db = LibraryVault(); kernel = NetworkKernel(cfg); orc = Orchestrator(kernel, cfg, db)
    queued_rj = "RJ99110005"; stale_rj = "RJ99110006"; ignored_rj = "RJ99110007"
    try:
        db.upsert_download(f"{queued_rj}:t1", queued_rj, "t1", f"/tmp/{queued_rj}/t1.mp3", "queued", 0, 100)
        db.upsert_download(f"{queued_rj}:t2", queued_rj, "t2", f"/tmp/{queued_rj}/t2.mp3", "downloading", 20, 100)
        db.upsert_download(f"{stale_rj}:t1", stale_rj, "t1", f"/tmp/{stale_rj}/t1.mp3", "stale", 0, 100)
        db.upsert_download(f"{ignored_rj}:t1", ignored_rj, "t1", f"/tmp/{ignored_rj}/t1.mp3", "ignored", 0, 100)
        db.set_metadata_cache(queued_rj, "T", "C", "", {"title": "T"}, [{"type": "audio", "title": "t1", "id": "1", "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])
        db.commit()
        await orc.restore_pending_downloads()
        summary_q = db.get_downloads_summary(queued_rj)
        summary_s = db.get_downloads_summary(stale_rj)
        summary_i = db.get_downloads_summary(ignored_rj)
        assert summary_q.get("paused", 0) == 2, summary_q
        assert summary_s.get("stale", 0) == 1, summary_s
        assert summary_i.get("ignored", 0) == 1, summary_i
        print("PASS startup_restore_ignores_stale_ignored")
        return 0
    finally:
        for rj in (queued_rj, stale_rj, ignored_rj):
            db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
            db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
        db.commit()
        await kernel.shutdown()

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
