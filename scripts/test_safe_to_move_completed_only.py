#!/usr/bin/env python3
"""只有 completed/verified + 无 pending downloads 才能安全迁移."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  safe_to_move: 只返回 completed/verified\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    # Safe: completed + all registered
    rj_safe = "RJ99991"
    meta = WorkMetadata(rj_id=rj_safe, title="Safe", circle="", cv=[], tags=[],
                        price=0, source_url="", dl_count=0, rating=0.0,
                        release_date="", cover_url="")
    db.register(meta, 1000, Path(f"/tmp/{rj_safe}"), status="completed")
    db.upsert_download(f"{rj_safe}:t1", rj_safe, "t1", f"/tmp/{rj_safe}/t1.mp3",
                       "registered", 100, 100)

    # Unsafe: completed but has queued downloads
    rj_unsafe_q = "RJ99992"
    meta2 = WorkMetadata(rj_id=rj_unsafe_q, title="UnsafeQ", circle="", cv=[], tags=[],
                         price=0, source_url="", dl_count=0, rating=0.0,
                         release_date="", cover_url="")
    db.register(meta2, 1000, Path(f"/tmp/{rj_unsafe_q}"), status="completed")
    db.upsert_download(f"{rj_unsafe_q}:t1", rj_unsafe_q, "t1",
                       f"/tmp/{rj_unsafe_q}/t1.mp3", "queued", 0, 100)

    # Unsafe: verified but has paused downloads
    rj_unsafe_p = "RJ99993"
    meta3 = WorkMetadata(rj_id=rj_unsafe_p, title="UnsafeP", circle="", cv=[], tags=[],
                         price=0, source_url="", dl_count=0, rating=0.0,
                         release_date="", cover_url="")
    db.register(meta3, 1000, Path(f"/tmp/{rj_unsafe_p}"), status="verified")
    db.upsert_download(f"{rj_unsafe_p}:t1", rj_unsafe_p, "t1",
                       f"/tmp/{rj_unsafe_p}/t1.mp3", "paused", 50, 100)

    db.commit()

    # ── get_safe_migratable_works ──
    safe = db.get_safe_migratable_works()
    safe_ids = {s["rj_id"] for s in safe}
    print(f"  safe works: {safe_ids}")

    assert rj_safe in safe_ids, f"{rj_safe} should be safe to move"
    assert rj_unsafe_q not in safe_ids, f"{rj_unsafe_q} (has queued) should be UNSAFE"
    assert rj_unsafe_p not in safe_ids, f"{rj_unsafe_p} (has paused) should be UNSAFE"

    print(f"  ✓ {rj_safe} safe (completed + all registered)")
    print(f"  ✓ {rj_unsafe_q} unsafe (has queued)")
    print(f"  ✓ {rj_unsafe_p} unsafe (has paused)")

    # Cleanup
    for rj in (rj_safe, rj_unsafe_q, rj_unsafe_p):
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
