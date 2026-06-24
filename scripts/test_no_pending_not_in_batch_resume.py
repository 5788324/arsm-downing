#!/usr/bin/env python3
"""no_pending 不参与全部开始测试."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  no_pending 不参与全部开始测试\n{'='*60}\n")

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

    # ── Setup: one paused task with tracks, one with no pending tracks ──
    rj_ok = "RJ99995"
    rj_np = "RJ99996"

    print("── 1. 准备: 1 个可恢复 + 1 个无可恢复文件 ──")
    # OK: has paused track
    db.upsert_download(f"{rj_ok}:t1", rj_ok, "track1", f"/tmp/{rj_ok}/t1.mp3",
                       "paused", 0, 100)
    db.set_metadata_cache(rj_ok, "OK", "Circle", "",
        {"title": "OK"},
        [{"type": "audio", "title": "track1", "id": "t1",
          "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])

    # No pending: all tracks already completed
    db.upsert_download(f"{rj_np}:t1", rj_np, "track1", f"/tmp/{rj_np}/t1.mp3",
                       "completed", 100, 100)
    db.set_metadata_cache(rj_np, "NP", "Circle", "",
        {"title": "NP"},
        [{"type": "audio", "title": "track1", "id": "t1",
          "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])

    # ── 2. resume_all should include rj_ok but handle rj_np gracefully ──
    print(f"\n── 2. 执行 resume_all ──")
    status_log = {}
    def track_status(rj_id, st):
        status_log[rj_id] = st
    orc.set_callbacks(on_progress=lambda e: None, on_work_status=track_status)

    stats = await orc._resume_all_async()
    print(f"  stats: {stats}")

    # ── 3. Verify: rj_ok got queued, rj_np was not included ──
    print(f"\n── 3. 验证结果 ──")
    ok_final = status_log.get(rj_ok, "?")
    np_final = status_log.get(rj_np, "not_included")
    print(f"  {rj_ok}: {ok_final}")
    print(f"  {rj_np}: {np_final}")

    # rj_ok should emit Queued
    assert ok_final == "Queued", f"{rj_ok} 应为 Queued, 实际: {ok_final}"

    # rj_np should NOT emit through resume_all (tracks are all completed)
    # Note: rj_np might have 'paused' download rows but tracks are completed,
    # so resume_job finds no pending → emits "No pending tracks"
    # This is the expected behavior
    if np_final != "not_included":
        assert "no_pending" in WorkStatus.normalize(np_final).value or \
               np_final == "No pending tracks", \
               f"{rj_np} 应为 No pending tracks, 实际: {np_final}"
        print(f"  ✓ {rj_np} 正确显示 No pending tracks")
    else:
        print(f"  ✓ {rj_np} 未被 resume_all 包含")

    # Cleanup
    for rj in (rj_ok, rj_np):
        orc.cancelled_rjs.add(rj)
        orc.queued_rj_ids.discard(rj)
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ no_pending 不参与全部开始测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
