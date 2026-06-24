#!/usr/bin/env python3
"""derive: works.verified + no pending downloads → 不显示在下载列表."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  derive: verified 不显示在下载列表\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    rj = "RJ99998"
    # Simulate: works.status=verified, no pending downloads
    db.conn.execute(
        "INSERT OR REPLACE INTO works (rj_id,title,circle,status,local_path,downloaded_at) "
        "VALUES (?,?,?,?,?,datetime('now'))",
        (rj, "Verified Work", "Circle", "verified", f"/tmp/{rj}"))

    # ── 1. get_works_status should return "verified" ──
    ws = db.get_works_status(rj)
    assert ws == "verified", f"works.status should be 'verified', got '{ws}'"
    print(f"  ✓ works.status = '{ws}'")

    # ── 2. get_downloads_summary should be empty ──
    dl = db.get_downloads_summary(rj)
    assert len(dl) == 0, f"downloads should be empty, got {dl}"
    print(f"  ✓ downloads empty")

    # ── 3. get_pending_rj_ids should NOT include this RJ ──
    pending = db.get_pending_rj_ids()
    assert rj not in pending, f"verified RJ should NOT be in pending_rj_ids"
    print(f"  ✓ not in pending_rj_ids")

    # ── 4. Derivation should mark invisible ──
    from core.status import WorkStatus
    ws_enum = WorkStatus.normalize(ws)
    assert ws_enum.is_terminal, "verified should be terminal"
    assert ws_enum == WorkStatus.VERIFIED
    print(f"  ✓ verified is terminal")

    # ── Cleanup ──
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ derive verified hidden 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
