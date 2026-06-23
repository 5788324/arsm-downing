#!/usr/bin/env python3
"""详情 from metadata_cache 测试."""

import asyncio, sys, json as _j
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  详情 from metadata_cache 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator

    cfg = ConfigManager.load(); db = LibraryVault(); kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)
    rj = "RJ99999"
    tracks = [{"type":"audio","title":"t1.mp3","id":"1","mediaDownloadUrl":"http://x/a.mp3","size":100}]
    db.set_metadata_cache(rj, "Test", "TC", "", {"title":"Test"}, tracks)

    # No active tracks, no downloads — should fallback to metadata_cache
    detail = orc.get_track_detail_for_ui(rj)
    assert len(detail) == 1
    assert detail[0]["title"] == "t1.mp3"
    assert detail[0]["total"] == 100
    print(f"  ✓ fallback to metadata_cache: {detail[0]['title']} ({detail[0]['total']} bytes)")

    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,)); db.conn.commit()
    await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__ == "__main__": sys.exit(asyncio.run(test()))
