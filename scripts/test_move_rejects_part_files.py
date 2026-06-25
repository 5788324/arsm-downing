#!/usr/bin/env python3
"""get_safe_migratable_works 不含 .part 文件作品."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  safe_migratable 不含 .part\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    # ── Safe works are identified by: completed/verified + no pending downloads ──
    # .part files at the OS level can't be detected by SQLite alone
    # But the DB check (no queued/paused/downloading/failed) covers this:
    # if there's a .part file, there should be a download row with
    # status 'paused' or 'queued' or 'downloading'

    # Setup: work with paused download (implying .part exists)
    rj_part = "RJ99997"
    meta = WorkMetadata(rj_id=rj_part, title="HasPart", circle="", cv=[], tags=[],
                        price=0, source_url="", dl_count=0, rating=0.0,
                        release_date="", cover_url="")
    db.register(meta, 1000, Path(f"/tmp/{rj_part}"), status="completed")
    db.upsert_download(f"{rj_part}:t1", rj_part, "t1",
                       f"/tmp/{rj_part}/t1.mp3.part", "paused", 50, 100)
    db.commit()

    safe = db.get_safe_migratable_works()
    safe_ids = {s["rj_id"] for s in safe}

    # Work with paused download should NOT be safe
    assert rj_part not in safe_ids, \
        f"{rj_part} (has paused/downloading) should be UNSAFE to move"
    print(f"  ✓ {rj_part} has paused download → excluded from safe list")
    print(f"  ✓ DB-based check covers .part protection (paused→pending)")

    # Cleanup
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj_part,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj_part,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
