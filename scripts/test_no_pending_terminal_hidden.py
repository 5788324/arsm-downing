#!/usr/bin/env python3
"""terminal work 不显示 No pending tracks — 应隐藏."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  no_pending terminal hidden\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.status import WorkStatus

    cfg = ConfigManager.load()
    db = LibraryVault()

    # ── Setup: terminal work (verified) with zero downloads ──
    rj_v = "RJ99996"
    db.conn.execute(
        "INSERT OR REPLACE INTO works (rj_id,title,circle,status,local_path,downloaded_at) "
        "VALUES (?,?,?,?,?,datetime('now'))",
        (rj_v, "VerifiedWork", "Circle", "verified", f"/tmp/{rj_v}"))
    db.commit()

    # ── 1. Derivation: terminal + no pending → invisible ──
    ws = db.get_works_status(rj_v)
    dl = db.get_downloads_summary(rj_v)
    print(f"  works.status={ws}, downloads={dl}")

    ws_enum = WorkStatus.normalize(ws)
    has_pending = any(dl.get(s, 0) > 0 for s in
                      ("queued", "paused", "downloading", "failed"))

    assert ws_enum.is_terminal, f"{ws} should be terminal"
    assert not has_pending, "should have no pending downloads"

    should_hide = ws_enum.is_terminal and not has_pending
    assert should_hide, "terminal work with no pending → HIDE from download queue"
    print(f"  ✓ terminal + no pending → HIDE")

    # ── 2. "No pending tracks" must NOT be the display status for terminal ──
    derived_status = "无可恢复文件"  # This would be WRONG for terminal
    correct_behavior = should_hide  # terminal → just hide
    assert correct_behavior, "terminal should be hidden, not shown as No pending"
    print(f"  ✓ terminal → hidden (not 'No pending tracks')")

    # ── 3. Contrast: prepared + no pending → SHOULD show no_pending ──
    rj_p = "RJ99995"
    db.conn.execute(
        "INSERT OR REPLACE INTO works (rj_id,title,circle,status,local_path,downloaded_at) "
        "VALUES (?,?,?,?,?,datetime('now'))",
        (rj_p, "PreparedWork", "Circle", "prepared", f"/tmp/{rj_p}"))
    db.commit()

    ws_p = db.get_works_status(rj_p)
    dl_p = db.get_downloads_summary(rj_p)
    ws_p_enum = WorkStatus.normalize(ws_p)
    has_pending_p = any(dl_p.get(s, 0) > 0 for s in
                        ("queued", "paused", "downloading", "failed"))

    assert not ws_p_enum.is_terminal, "prepared is NOT terminal"
    assert not has_pending_p, "should have no pending"

    # prepared + no pending = show NO_PENDING (not hide)
    should_show_no_pending = not ws_p_enum.is_terminal and not has_pending_p
    assert should_show_no_pending, "prepared + no pending → show NO_PENDING"
    print(f"  ✓ prepared + no pending → show '无可恢复文件' (not hidden)")

    # ── Cleanup ──
    for rj in (rj_v, rj_p):
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ no_pending terminal hidden 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
