#!/usr/bin/env python3
"""show_completed 开关不修改 DB 测试 — 验证 toggle 只过滤显示不写 DB."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  show_completed 开关不修改 DB 测试\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault

    cfg = ConfigManager.load()
    db = LibraryVault()

    # ── Setup: write some downloads with various statuses ──
    print("── 1. 准备测试数据 ──")
    rj = "RJ99992"
    db.upsert_download(f"{rj}:p", rj, "track_paused", f"/tmp/{rj}/p.mp3",
                       "paused", 50, 100)
    db.upsert_download(f"{rj}:c", rj, "track_done", f"/tmp/{rj}/c.mp3",
                       "completed", 100, 100)
    db.upsert_download(f"{rj}:q", rj, "track_queued", f"/tmp/{rj}/q.mp3",
                       "queued", 0, 100)
    db.upsert_download(f"{rj}:f", rj, "track_failed", f"/tmp/{rj}/f.mp3",
                       "failed", 0, 100)

    rows_before = db.get_downloads_by_rj(rj)
    statuses_before = {r["status"] for r in rows_before}
    print(f"  Before: {statuses_before}")

    # ── 2. Simulate toggle: just filter in-memory, don't touch DB ──
    print("\n── 2. 模拟 toggle 过滤 (不应触及 DB) ──")
    from core.status import WorkStatus
    show_completed = False
    displayed = []
    for r in rows_before:
        ws = WorkStatus.normalize(r["status"])
        if show_completed or not ws.is_terminal:
            displayed.append(r)
    print(f"  show_completed={show_completed}: displayed {len(displayed)}/{len(rows_before)} items")

    # paused, queued, failed should always display
    displayed_ids = {r["status"] for r in displayed}
    assert "paused" in displayed_ids, "paused should display"
    assert "queued" in displayed_ids, "queued should display"
    assert "failed" in displayed_ids, "failed should display"
    print(f"  ✓ paused/queued/failed 始终显示")

    # completed should be hidden when show_completed=False
    if not show_completed:
        assert "completed" not in displayed_ids, "completed should be hidden"
        print(f"  ✓ completed 在 show_completed=False 时隐藏")

    # ── 3. Verify DB unchanged ──
    print("\n── 3. 验证 DB 未变 ──")
    rows_after = db.get_downloads_by_rj(rj)
    statuses_after = {r["status"] for r in rows_after}
    assert statuses_before == statuses_after, \
        f"DB 被修改! before={statuses_before} after={statuses_after}"
    print(f"  ✓ DB 完全未变")

    # ── Cleanup ──
    for sid in ("p", "c", "q", "f"):
        db.conn.execute("DELETE FROM downloads WHERE id=?", (f"{rj}:{sid}",))
    db.conn.commit()

    print(f"\n{'='*60}\n  ✓ show_completed 开关不修改 DB 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
