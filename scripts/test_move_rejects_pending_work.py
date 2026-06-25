#!/usr/bin/env python3
"""move 拒绝 pending 作品 — safe guard."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  move 拒绝 pending 作品\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    # Setup: work with queued download
    rj = "RJ99994"
    meta = WorkMetadata(rj_id=rj, title="Pending", circle="", cv=[], tags=[],
                        price=0, source_url="", dl_count=0, rating=0.0,
                        release_date="", cover_url="")
    db.register(meta, 1000, Path(f"/tmp/{rj}"), status="prepared")
    db.upsert_download(f"{rj}:t1", rj, "t1", f"/tmp/{rj}/t1.mp3",
                       "queued", 0, 100)
    db.commit()

    # try to move → should reject
    result = db.move_work_to_path(rj, f"/tmp/{rj}", f"/new/{rj}")
    assert result["success"] == False, f"should reject pending work: {result}"
    assert "pending" in result["error"].lower(), f"error should mention pending: {result}"
    print(f"  ✓ rejected: {result['error']}")

    # Cleanup
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
