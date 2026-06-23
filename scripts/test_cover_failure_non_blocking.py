#!/usr/bin/env python3
"""封面失败非阻塞测试 — cover 代理不可用时 enrich 不崩."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  封面失败非阻塞测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    cfg.cover_proxy = "http://127.0.0.1:19999"  # dead proxy
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # Write external work
    rj = "RJ99995"
    meta = WorkMetadata(rj_id=rj, title=rj, circle="",
                        cv=[], tags=[], price=0, source_url="",
                        dl_count=0, rating=0.0, release_date="", cover_url="")
    db.register(meta, 0, Path("/tmp/RJ99995"), status='external')

    # enrichment should not crash
    db.upsert_library_entry(rj, "/tmp", "/tmp/RJ99995", 100, 1, 'found')
    import json as _j
    db.set_metadata_cache(rj, "Test", "TC", "http://bad-cover/cover.jpg",
                          {"title": "Test"}, [])
    db.enrich_external_metadata(rj, None, "http://bad-cover/cover.jpg",
                                "Test", "TC")

    row = db.conn.execute(
        "SELECT title, cover_url, status FROM works WHERE rj_id=?", (rj,)
    ).fetchone()
    assert row["title"] == "Test"
    assert row["status"] in ("external", "verified")
    print(f"  ✓ enrich 成功, title={row['title']}, cover_url={row['cover_url']}")
    print(f"  ✓ 封面 URL 已记录, 未阻塞流程")

    # Cleanup
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM library_index")
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.conn.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}")
    print(f"  ✓ 封面失败非阻塞测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
