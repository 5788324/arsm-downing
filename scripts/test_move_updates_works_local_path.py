#!/usr/bin/env python3
"""move 更新 works.local_path."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  move 更新 works.local_path\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    rj = "RJ99995"
    old_path = f"/tmp/{rj}"
    new_path = f"/new/{rj}"

    meta = WorkMetadata(rj_id=rj, title="Movable", circle="", cv=[], tags=[],
                        price=0, source_url="", dl_count=0, rating=0.0,
                        release_date="", cover_url="")
    db.register(meta, 1000, Path(old_path), status="completed")
    # All downloads registered (no pending)
    for i in range(3):
        db.upsert_download(f"{rj}:t{i}", rj, f"t{i}", f"{old_path}/t{i}.mp3",
                           "registered", 100, 100)
    db.commit()

    # ── Move ──
    result = db.move_work_to_path(rj, old_path, new_path)
    print(f"  result: {result}")
    assert result["success"], f"move failed: {result}"
    assert result["updated"] >= 1, f"should update at least 1 row"

    # ── Verify works.local_path updated ──
    row = db.conn.execute("SELECT local_path FROM works WHERE rj_id=?", (rj,)).fetchone()
    assert row["local_path"] == new_path, \
        f"works.local_path should be {new_path}, got {row['local_path']}"
    print(f"  ✓ works.local_path = {new_path}")

    # ── Verify downloads.local_path updated ──
    dl_rows = db.conn.execute(
        "SELECT id, local_path FROM downloads WHERE rj_id=?", (rj,)).fetchall()
    for r in dl_rows:
        assert r["local_path"].startswith(new_path), \
            f"downloads.local_path should start with {new_path}, got {r['local_path']}"
    print(f"  ✓ {len(dl_rows)} downloads.local_path updated")

    # Cleanup
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
