#!/usr/bin/env python3
"""队列加载防重复测试 — 验证 terminal 任务不被加载 (RC7.4-bis DB 适配)."""

import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  队列加载防重复测试\n{'='*60}\n")

    # ── 1. _is_terminal covers all terminal states ──
    from ui.views.download_view import DownloadView
    from core.status import WorkStatus
    print("── 1. _is_terminal 覆盖所有终端状态 ──")
    terminal_states = [("已完成", True), ("Completed", True), ("completed", True),
                       ("registered", True), ("verified", True), ("external", True)]
    non_terminal = [("队列中", False), ("下载中", False), ("已暂停", False),
                    ("Paused", False), ("queued", False), ("downloading", False),
                    ("failed", False), ("获取元数据中...", False)]
    for s, expected in terminal_states + non_terminal:
        assert DownloadView._is_terminal(s) == expected, \
            f"_is_terminal('{s}') should be {expected}"
    print(f"  ✓ 所有 terminal/non-terminal 状态正确")

    # ── 2. Write test data to DB ──
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    terminals = ["RJ88880", "RJ88882"]
    actives = ["RJ88881", "RJ88883"]

    for rj in terminals:
        meta = WorkMetadata(rj_id=rj, title=f"Terminal {rj}", circle="",
                            cv=[], tags=[], price=0, source_url="",
                            dl_count=0, rating=0.0, release_date="", cover_url="")
        db.register(meta, 100, Path(f"/tmp/{rj}"), status="completed")
        db.upsert_download(f"{rj}:t1", rj, "track1", f"/tmp/{rj}/t1.mp3",
                           "registered", 100, 100)
    for rj in actives:
        meta = WorkMetadata(rj_id=rj, title=f"Active {rj}", circle="",
                            cv=[], tags=[], price=0, source_url="",
                            dl_count=0, rating=0.0, release_date="", cover_url="")
        db.register(meta, 100, Path(f"/tmp/{rj}"), status="prepared")
        db.upsert_download(f"{rj}:t1", rj, "track1", f"/tmp/{rj}/t1.mp3",
                           "queued", 0, 100)
    db.commit()

    # ── 3. Verify DB-derived behavior ──
    print("\n── 2. DB 派生验证 ──")
    pending = db.get_pending_rj_ids()
    for rj in terminals:
        assert rj not in pending, f"{rj} (terminal) 不应在 pending_rj_ids"
        print(f"  ✓ {rj} 不在 pending")
    for rj in actives:
        assert rj in pending, f"{rj} (active) 应在 pending_rj_ids"
        print(f"  ✓ {rj} 在 pending")

    # ── 4. load_queue simulation ──
    print("\n── 3. 模拟 load_queue ──")
    visible = set()
    hidden = set()
    for rj_id in sorted(pending):
        dl = db.get_downloads_summary(rj_id)
        ws = db.get_works_status(rj_id)
        ws_enum = WorkStatus.normalize(ws) if ws else None
        has_pending = any(dl.get(s, 0) > 0 for s in
                          ("queued", "paused", "downloading", "failed"))
        if ws_enum and ws_enum.is_terminal and not has_pending:
            hidden.add(rj_id)
            continue
        if has_pending:
            visible.add(rj_id)

    for rj in terminals:
        assert rj not in visible, f"{rj} (terminal) 不应 visible"
        print(f"  ✓ {rj} hidden (terminal + no pending)")
    for rj in actives:
        assert rj in visible, f"{rj} (active) 应 visible"
        print(f"  ✓ {rj} visible (has pending)")

    # Cleanup
    for rj in terminals + actives:
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.commit()

    print(f"\n{'='*60}\n  ✓ 队列加载防重复测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
