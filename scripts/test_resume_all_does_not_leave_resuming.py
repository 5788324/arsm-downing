#!/usr/bin/env python3
"""resume_all 不允许长期停留在 resuming 状态测试."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  resume_all 不残留 resuming 测试\n{'='*60}\n")

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

    status_log = []

    def track_status(rj_id, st):
        status_log.append((rj_id, st))

    orc.set_callbacks(
        on_progress=lambda e: None,
        on_work_status=track_status)

    # ── Setup 5 simulated paused RJs ──
    print("── 1. 准备 5 个暂停任务 ──")
    rj_ids = []
    for i in range(1, 6):
        rj = f"RJ{99000000 + i:08d}"
        rj_ids.append(rj)
        db.upsert_download(f"{rj}:t1", rj, "track1", f"/tmp/{rj}/t1.mp3",
                           "paused", 0, 100)
        db.set_metadata_cache(rj, f"Test {i}", "Circle", "",
            {"title": f"Test {i}"},
            [{"type": "audio", "title": "track1", "id": "t1",
              "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])

    # ── 2. resume_all ──
    print(f"\n── 2. 执行 resume_all ──")
    status_log.clear()
    stats = await orc._resume_all_async()
    print(f"  stats: {stats}")

    # ── 3. Verify: all resolved to queued (not stuck in resuming) ──
    print(f"\n── 3. 验证状态流转 ──")
    last_status = {}
    for rj_id, st in status_log:
        last_status[rj_id] = st

    for rj in rj_ids:
        final = last_status.get(rj, "?")
        print(f"  {rj}: last emit = '{final}'")
        # Resuming... is transient — should be followed by Queued
        assert final != "Resuming...", \
            f"{rj} 不应长期停在 Resuming... 状态, 最后 emit: {final}"
        assert final == "Queued", \
            f"{rj} 最后状态应为 Queued, 实际: {final}"

    print(f"  ✓ 所有 5 个任务最终状态为 Queued (非 Resuming...)")

    # ── 4. Verify worker emits Downloading only when actually dequeueing ──
    print(f"\n── 4. 验证 Downloading 未被 emit ──")
    dl_emitted = [(r, s) for r, s in status_log if s == "Downloading"]
    print(f"  Downloading count: {len(dl_emitted)} (should be 0 until workers start)")
    assert len(dl_emitted) == 0, \
        f"resume_all 不应 emit Downloading, 实际: {len(dl_emitted)} 次"

    print(f"  ✓ resume_all 不 emit Downloading — worker 启动时才 emit")

    # Cleanup
    for rj in rj_ids:
        orc.cancelled_rjs.add(rj)
        orc.queued_rj_ids.discard(rj)
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
        db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ resume_all 不残留 resuming 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
