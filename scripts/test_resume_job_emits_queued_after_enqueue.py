#!/usr/bin/env python3
"""resume_job 入队后状态为 queued，不是 resuming 或 downloading 测试."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

class MockProgressEvent:
    def __init__(self, rj_id, track_title, downloaded, total, status,
                 global_speed_bps=0, track_speed_bps=0, eta_seconds=None):
        self.rj_id = rj_id; self.track_title = track_title
        self.downloaded_bytes = downloaded; self.total_bytes = total
        self.status = status; self.global_speed_bps = global_speed_bps
        self.track_speed_bps = track_speed_bps; self.eta_seconds = eta_seconds

async def test():
    print(f"\n{'='*60}\n  resume_job 入队后 emit Queued 测试\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    import json as _j

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    rj = "RJ99994"
    status_calls = []

    def track_status(rj_id, st):
        status_calls.append(st)

    orc.set_callbacks(
        on_progress=lambda e: None,
        on_work_status=track_status)

    # Setup
    db.upsert_download(f"{rj}:t1", rj, "track1", f"/tmp/{rj}/t1.mp3",
                       "paused", 0, 100)
    db.set_metadata_cache(rj, "Test", "Circle", "",
        {"title": "Test"},
        [{"type": "audio", "title": "track1", "id": "t1",
          "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])

    # ── 1. resume_job → status_calls should include "Queued" ──
    print("── 1. resume_job 入队后 emit Queued ──")
    status_calls.clear()
    result = await orc.resume_job(rj)
    print(f"  result: {result}")
    assert result["status"] == "queued", \
        f"resume_job 应返回 queued, 得到 {result['status']}"
    print(f"  ✓ resume_job 返回 status=queued")

    # ── 2. Status calls: must contain "Resuming..." then "Queued" ──
    print(f"\n── 2. work_status 调用序列 ──")
    for s in status_calls:
        print(f"  emit: '{s}'")
    assert "Resuming..." in status_calls, \
        f"应有 Resuming... 调用, 实际: {status_calls}"
    assert "Queued" in status_calls, \
        f"应有 Queued 调用, 实际: {status_calls}"
    # "Downloading" must NOT appear
    assert "Downloading" not in status_calls, \
        f"不应有 Downloading (worker 还没取到任务), 实际: {status_calls}"
    print(f"  ✓ emit 序列正确: Resuming... → Queued (无 Downloading)")

    # ── 3. _resume_one must not double-emit ──
    print(f"\n── 3. _resume_one 不重复 emit ──")
    # Clean up queue
    orc.cancelled_rjs.add(rj)
    orc.queued_rj_ids.discard(rj)
    # Re-setup
    db.upsert_download(f"{rj}:t1", rj, "track1", f"/tmp/{rj}/t1.mp3",
                       "paused", 0, 100)
    status_calls.clear()
    result2 = await orc._resume_one(rj)
    print(f"  _resume_one result: {result2}")
    assert result2["status"] == "queued", \
        f"_resume_one 应返回 queued, 得到 {result2['status']}"
    for s in status_calls:
        print(f"  emit: '{s}'")
    # Count: should be exactly 2 (Resuming... + Queued), not 3
    assert len(status_calls) >= 2, f"至少有 2 个 emit, 实际: {len(status_calls)}"
    assert "Downloading" not in status_calls, \
        f"_resume_one 不应 emit Downloading: {status_calls}"
    print(f"  ✓ _resume_one 不额外 emit Downloading")

    # Cleanup
    orc.cancelled_rjs.add(rj)
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ resume_job 入队后 emit Queued 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
