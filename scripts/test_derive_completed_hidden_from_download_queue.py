#!/usr/bin/env python3
"""derive: works.completed + registered downloads → 不显示在下载列表."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  derive: completed 不显示在下载列表\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault

    cfg = ConfigManager.load()
    db = LibraryVault()

    rj = "RJ99999"
    # Simulate RJ01244084 scenario: works.completed + downloads.registered
    db.conn.execute(
        "INSERT OR REPLACE INTO works (rj_id,title,circle,status,local_path,downloaded_at) "
        "VALUES (?,?,?,?,?,datetime('now'))",
        (rj, "Completed Work", "Circle", "completed", f"/tmp/{rj}"))
    for i in range(25):
        db.conn.execute(
            "INSERT OR REPLACE INTO downloads (id,rj_id,track_title,status,local_path) "
            "VALUES (?,?,?,?,?)",
            (f"{rj}:t{i}", rj, f"track{i}", "registered", f"/tmp/{rj}/t{i}.mp3"))
    db.commit()

    # ── 1. works.status = completed ──
    ws = db.get_works_status(rj)
    assert ws == "completed", f"expected 'completed', got '{ws}'"
    print(f"  ✓ works.status = 'completed'")

    # ── 2. downloads all registered → no pending ──
    dl = db.get_downloads_summary(rj)
    assert dl.get("registered", 0) == 25
    assert dl.get("queued", 0) == 0
    assert dl.get("paused", 0) == 0
    assert dl.get("downloading", 0) == 0
    assert dl.get("failed", 0) == 0
    print(f"  ✓ downloads: registered={dl['registered']}, no pending")

    # ── 3. Not in pending_rj_ids ──
    pending = db.get_pending_rj_ids()
    assert rj not in pending, f"completed RJ should NOT be in pending_rj_ids"
    print(f"  ✓ not in pending_rj_ids")

    # ── 4. Derivation: terminal + no pending → invisible ──
    from core.status import WorkStatus
    ws_enum = WorkStatus.normalize(ws)
    assert ws_enum.is_terminal, "completed should be terminal"
    has_pending = any(dl.get(s, 0) > 0 for s in
                      ("queued", "paused", "downloading", "failed"))
    assert not has_pending
    should_hide = ws_enum.is_terminal and not has_pending
    assert should_hide, "should be hidden from download queue"
    print(f"  ✓ terminal={ws_enum.is_terminal}, has_pending={has_pending} → HIDE")

    # ── Cleanup ──
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ derive completed hidden 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
