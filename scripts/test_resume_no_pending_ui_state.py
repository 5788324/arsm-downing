#!/usr/bin/env python3
"""resume_job 结构化返回测试."""

import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  resume_job 结构化返回测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator

    cfg = ConfigManager.load(); db = LibraryVault(); kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # No cache → no_cache
    r = await orc.resume_job("RJ99999")
    assert r["status"] == "no_cache"
    print(f"  ✓ no_cache: {r}")

    # With cache but all completed → no_pending
    import json as _j
    # Track save_path must match what resume_job computes from dir_template
    spath = Path("Downloads") / "RJ99999 T" / "t"
    dl_id = orc._make_dl_id("RJ99999", "1", spath, "t")
    db.set_metadata_cache("RJ99999", "T", "C", "", {"title":"T"},
        [{"type":"audio","title":"t","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}])
    db.upsert_download(dl_id, "RJ99999", "t", str(spath), "completed", 100, 100)
    r2 = await orc.resume_job("RJ99999")
    assert r2["status"] == "no_pending", f"got {r2}"
    print(f"  ✓ no_pending: {r2}")

    # With pending → resumed (same dl_id, different status)
    db.upsert_download(dl_id, "RJ99999", "t", str(spath), "paused", 0, 200)
    r3 = await orc.resume_job("RJ99999")
    assert r3["status"] == "queued", f"got {r3}"
    assert r3["count"] >= 1
    print(f"  ✓ queued: {r3}")

    db.conn.execute("DELETE FROM downloads WHERE rj_id='RJ99999'"); db.conn.commit()
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id='RJ99999'"); db.conn.commit()
    await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__ == "__main__": sys.exit(asyncio.run(test()))
