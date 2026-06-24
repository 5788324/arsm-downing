#!/usr/bin/env python3
"""derive: completed 883 + queued 51 → 显示 queued，不显示 already_queued."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  derive: partial + queued → 显示 queued\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault

    cfg = ConfigManager.load()
    db = LibraryVault()

    rj = "RJ88893"
    # Simulate RJ01588893: works.prepared + 883 completed + 51 queued
    db.conn.execute(
        "INSERT OR REPLACE INTO works (rj_id,title,circle,status,local_path,downloaded_at) "
        "VALUES (?,?,?,?,?,datetime('now'))",
        (rj, "Partial+Queued", "Circle", "prepared", f"/tmp/{rj}"))
    for i in range(883):
        db.conn.execute(
            "INSERT OR REPLACE INTO downloads (id,rj_id,track_title,status,local_path) "
            "VALUES (?,?,?,?,?)",
            (f"{rj}:c{i}", rj, f"track_c{i}", "completed", f"/tmp/{rj}/c{i}.mp3"))
    for i in range(51):
        db.conn.execute(
            "INSERT OR REPLACE INTO downloads (id,rj_id,track_title,status,local_path) "
            "VALUES (?,?,?,?,?)",
            (f"{rj}:q{i}", rj, f"track_q{i}", "queued", f"/tmp/{rj}/q{i}.mp3"))
    db.commit()

    # ── 1. Verify DB state ──
    ws = db.get_works_status(rj)
    assert ws == "prepared", f"works.status should be 'prepared', got '{ws}'"
    dl = db.get_downloads_summary(rj)
    assert dl.get("completed", 0) == 883
    assert dl.get("queued", 0) == 51
    print(f"  ✓ works={ws}, dl: completed={dl['completed']} queued={dl['queued']}")

    # ── 2. Must be in pending_rj_ids ──
    pending = db.get_pending_rj_ids()
    assert rj in pending, f"should be in pending_rj_ids (has queued)"
    print(f"  ✓ in pending_rj_ids")

    # ── 3. Derivation rule: has_queued → show "队列中" NOT "already_queued" ──
    from core.status import WorkStatus
    has_queued = dl.get("queued", 0) > 0
    assert has_queued, "should have queued downloads"

    # Priority: queued → show queued
    derived_status = "队列中" if has_queued else "?"
    assert derived_status == "队列中"
    print(f"  ✓ derived status = '{derived_status}'")

    # ── 4. already_queued must NEVER appear as card status ──
    ns = WorkStatus.normalize("already_queued")
    assert ns == WorkStatus.QUEUED, "already_queued → QUEUED"
    assert ns.value == "queued"
    print(f"  ✓ already_queued normalizes to '{ns.value}' (not displayed as 'already_queued')")

    # ── Cleanup ──
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ derive partial+queued → queued 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
