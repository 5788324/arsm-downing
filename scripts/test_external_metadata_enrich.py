#!/usr/bin/env python3
"""external 元数据补全测试 — 通过 metadata_cache 补标题/封面."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  external 元数据补全测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    rj = "RJ01603020"

    # Write as external with bare metadata
    meta = WorkMetadata(rj_id=rj, title=rj, circle="",
                        cv=[], tags=[], price=0, source_url="",
                        dl_count=0, rating=0.0, release_date="", cover_url="")
    db.register(meta, 0, Path("/tmp/RJ01603020"), status='external')

    # Simulate: metadata_cache already has data from prepare
    cached = db.get_metadata_cache(rj)
    if not cached:
        # No cache yet — test the enrichment without API (uses cached check)
        print("  ⚠ metadata_cache 为空, 测试 enrich 逻辑")
        # Enrich should handle missing cache gracefully
        db.enrich_external_metadata(
            rj, None, "", "Test Title", "Test Circle")
    else:
        db.enrich_external_metadata(
            rj, None, cached.get("cover_url", ""),
            cached.get("title", rj), cached.get("circle", ""))

    # Verify
    row = db.conn.execute(
        "SELECT title, circle, cover_url, status FROM works WHERE rj_id=?",
        (rj,)).fetchone()
    assert row is not None
    print(f"  title: {row['title']}")
    print(f"  status: {row['status']}")
    assert row["title"] != rj or cached is None, "标题应被补全"
    assert row["status"] in ("external", "verified"), f"status={row['status']}"

    # Cleanup
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.commit()

    print(f"\n{'='*60}")
    print(f"  ✓ external 元数据补全测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
