#!/usr/bin/env python3
"""move 更新 downloads.local_path."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  move 更新 downloads.local_path\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    rj = "RJ99996"
    old_path = f"/tmp/{rj}"
    new_path = f"/new/{rj}"

    meta = WorkMetadata(rj_id=rj, title="DLMovable", circle="", cv=[], tags=[],
                        price=0, source_url="", dl_count=0, rating=0.0,
                        release_date="", cover_url="")
    db.register(meta, 500, Path(old_path), status="completed")
    for i in range(2):
        db.upsert_download(f"{rj}:t{i}", rj, f"t{i}",
                           f"{old_path}/sub/t{i}.mp3", "registered", 100, 100)
    db.commit()

    result = db.move_work_to_path(rj, old_path, new_path)
    assert result["success"], f"move failed: {result}"

    # All downloads paths should use REPLACE(old_path, new_path)
    for row in db.conn.execute("SELECT id,local_path FROM downloads WHERE rj_id=?", (rj,)):
        assert row["local_path"].startswith(new_path), \
            f"{row['id']}: expected {new_path} prefix, got {row['local_path']}"
        assert old_path not in row["local_path"], \
            f"{row['id']}: should not contain old path"
        print(f"  ✓ {row['id']}: {row['local_path']}")

    # Cleanup
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
