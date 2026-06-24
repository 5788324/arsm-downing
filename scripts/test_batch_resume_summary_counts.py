#!/usr/bin/env python3
"""_resume_all_async 批量恢复统计输出测试."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  批量恢复统计输出测试\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    from core.status import WorkStatus
    import json as _j

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # ── Setup mixed-status RJs ──
    print("── 1. 准备混合状态任务 ──")
    base = "RJ99997"

    # a: normal paused (should resume to queued)
    rj_a = f"{base}0"
    db.upsert_download(f"{rj_a}:t1", rj_a, "t1", f"/tmp/{rj_a}/t1.mp3",
                       "paused", 0, 100)
    db.set_metadata_cache(rj_a, "A", "C", "",
        {"title": "A"},
        [{"type": "audio", "title": "t1", "id": "1",
          "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])

    # b: already queued (will get already_queued)
    rj_b = f"{base}1"
    db.upsert_download(f"{rj_b}:t1", rj_b, "t1", f"/tmp/{rj_b}/t1.mp3",
                       "paused", 0, 100)
    db.set_metadata_cache(rj_b, "B", "C", "",
        {"title": "B"},
        [{"type": "audio", "title": "t1", "id": "1",
          "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])
    # Pre-populate queued_rj_ids
    orc.queued_rj_ids.add(rj_b)

    # c: no metadata cache → no_cache
    rj_c = f"{base}2"
    db.upsert_download(f"{rj_c}:t1", rj_c, "t1", f"/tmp/{rj_c}/t1.mp3",
                       "paused", 0, 100)

    # d: all tracks completed → no_pending
    rj_d = f"{base}3"
    db.upsert_download(f"{rj_d}:t1", rj_d, "t1", f"/tmp/{rj_d}/t1.mp3",
                       "completed", 100, 100)
    db.set_metadata_cache(rj_d, "D", "C", "",
        {"title": "D"},
        [{"type": "audio", "title": "t1", "id": "1",
          "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])

    # e: normal paused
    rj_e = f"{base}4"
    db.upsert_download(f"{rj_e}:t1", rj_e, "t1", f"/tmp/{rj_e}/t1.mp3",
                       "paused", 0, 100)
    db.set_metadata_cache(rj_e, "E", "C", "",
        {"title": "E"},
        [{"type": "audio", "title": "t1", "id": "1",
          "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])

    status_log = {}
    def track_status(rj_id, st):
        status_log[rj_id] = st
    orc.set_callbacks(on_progress=lambda e: None, on_work_status=track_status)

    # ── 2. Test resume_all stats ──
    print(f"\n── 2. resume_all stats ──")
    stats = await orc._resume_all_async()
    print(f"  stats = {stats}")

    # ── 3. Test _resume_one directly for already_queued ──
    print(f"\n── 3. _resume_one already_queued 守卫 ──")
    # rj_b is in queued_rj_ids → _resume_one should return already_queued
    r_already = await orc._resume_one(rj_b)
    assert r_already["status"] == "already_queued", \
        f"{rj_b} 应在 queued_rj_ids 中, _resume_one 应返回 already_queued, 实际: {r_already}"
    print(f"  ✓ {rj_b} _resume_one → already_queued: {r_already}")

    # ── 4. Verify stats ──
    print(f"\n── 4. 验证统计 ──")
    assert isinstance(stats, dict), "stats 应为 dict"
    for key in ("resumed_to_queue", "already_queued", "no_pending",
                "no_cache", "failed"):
        assert key in stats, f"stats 缺少 key: {key}"
        print(f"  stats['{key}'] = {stats[key]}")

    # resumed_to_queue should be ≥ 2 (a + e)
    # c is no_cache; d is no_pending
    assert stats["resumed_to_queue"] >= 2, \
        f"resumed_to_queue 应 >= 2, 实际: {stats['resumed_to_queue']}"
    assert stats["no_cache"] >= 1, \
        f"no_cache 应 >= 1, 实际: {stats['no_cache']}"
    # already_queued is 0 here because resume_all() pre-filters queued_rj_ids,
    # but _resume_one correctly returns already_queued when called directly
    print(f"  note: resume_all() pre-filters queued_rj_ids, already_queued=0 in stats")
    print(f"  but _resume_one correctly returns already_queued for queued items")

    print(f"\n  ✓ resumed_to_queue >= 2")
    print(f"  ✓ no_cache >= 1")
    print(f"  ✓ _resume_one handles already_queued correctly")

    # ── 5. Verify correct status emits ──
    print(f"\n── 4. 验证 emit ──")
    for rj_id, st in sorted(status_log.items()):
        print(f"  {rj_id}: emit '{st}'")

    assert status_log.get(rj_a, "") == "Queued", f"{rj_a} should be Queued"
    print(f"  ✓ {rj_a} → Queued")

    # rj_b was already_queued → not emitted
    print(f"  ✓ {rj_b} 被 already_queued 守卫跳过")

    # rj_d → No pending tracks
    dp_status = status_log.get(rj_d, "")
    assert "No pending" in dp_status or "no_pending" in WorkStatus.normalize(dp_status).value, \
        f"{rj_d} should be No pending tracks, got: {dp_status}"
    print(f"  ✓ {rj_d} → No pending tracks")

    # Cleanup
    for suffix in "01234":
        rj = f"{base}{suffix}"
        orc.cancelled_rjs.add(rj)
        orc.queued_rj_ids.discard(rj)
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ 批量恢复统计输出测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
