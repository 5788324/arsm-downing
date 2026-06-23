#!/usr/bin/env python3
"""详情 from downloads 测试."""

import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  详情 from downloads 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator

    cfg = ConfigManager.load(); db = LibraryVault(); kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)
    rj = "RJ99999"
    db.upsert_download(f"{rj}:t1", rj, "t1.mp3", "/tmp/t1.mp3", "completed", 100, 100)

    detail = orc.get_track_detail_for_ui(rj)
    assert len(detail) == 1
    assert detail[0]["title"] == "t1.mp3"
    assert detail[0]["status"] == "completed"
    print(f"  ✓ from downloads: {detail[0]['title']} {detail[0]['status']}")

    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.conn.commit()
    await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__ == "__main__": sys.exit(asyncio.run(test()))
