#!/usr/bin/env python3
"""废弃 queue.json 测试 — 启动恢复只读 SQLite (RC7.4-bis 适配)."""
import asyncio, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  废弃 queue.json 测试\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    # Write test data to DB directly (simulating real user state)
    # RJ88880: terminal, no pending → should NOT be in download queue
    rj_term = "RJ88880"
    meta_term = WorkMetadata(rj_id=rj_term, title="Terminal", circle="",
                             cv=[], tags=[], price=0, source_url="",
                             dl_count=0, rating=0.0, release_date="", cover_url="")
    db.register(meta_term, 100, Path(f"/tmp/{rj_term}"), status="completed")
    # All downloads registered (no pending)
    for i in range(3):
        db.upsert_download(f"{rj_term}:t{i}", rj_term, f"track{i}",
                           f"/tmp/{rj_term}/t{i}.mp3", "registered", 100, 100)

    # RJ88881: has queued downloads → should BE in download queue
    rj_active = "RJ88881"
    meta_active = WorkMetadata(rj_id=rj_active, title="Active", circle="",
                               cv=[], tags=[], price=0, source_url="",
                               dl_count=0, rating=0.0, release_date="", cover_url="")
    db.register(meta_active, 100, Path(f"/tmp/{rj_active}"), status="prepared")
    db.upsert_download(f"{rj_active}:t1", rj_active, "track1",
                       f"/tmp/{rj_active}/t1.mp3", "queued", 0, 100)
    db.commit()

    # ── Verify DB state ──
    assert db.get_works_status(rj_term) == "completed"
    assert db.get_works_status(rj_active) == "prepared"
    dl_active = db.get_downloads_summary(rj_active)
    assert dl_active.get("queued", 0) >= 1

    # ── pending_rj_ids: only active, not terminal ──
    pending = db.get_pending_rj_ids()
    assert rj_term not in pending, "已完成 + 无 pending → 不在 pending_rj_ids"
    assert rj_active in pending, "有 queued → 在 pending_rj_ids"
    print(f"  ✓ terminal 不在 pending_rj_ids, active 在")

    # ── Simulate load_queue behavior ──
    visible = set()
    for rj_id in sorted(pending):
        dl = db.get_downloads_summary(rj_id)
        ws = db.get_works_status(rj_id)
        from core.status import WorkStatus
        ws_enum = WorkStatus.normalize(ws) if ws else None
        has_pending = any(dl.get(s, 0) > 0 for s in
                          ("queued", "paused", "downloading", "failed"))
        if ws_enum and ws_enum.is_terminal and not has_pending:
            continue  # hide
        if has_pending:
            visible.add(rj_id)

    assert "RJ88880" not in visible, "terminal 应被隐藏"
    assert "RJ88881" in visible, "有 queued 的应显示"
    print(f"  ✓ terminal hidden, active visible")

    # Cleanup
    for rj in (rj_term, rj_active):
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
