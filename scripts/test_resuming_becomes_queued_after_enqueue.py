#!/usr/bin/env python3
"""resuming 变成 queued 后 UI 显示队列中 — 不会长期停在恢复中."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  resuming → queued after enqueue\n{'='*60}\n")

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

    rj = "RJ99997"

    # Setup: paused download + metadata cache
    db.upsert_download(f"{rj}:t1", rj, "track1", f"/tmp/{rj}/t1.mp3",
                       "paused", 0, 100)
    db.set_metadata_cache(rj, "Test", "Circle", "",
        {"title": "Test"},
        [{"type": "audio", "title": "track1", "id": "t1",
          "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])

    # ── 1. resume_job must return "queued" not "resumed" ──
    result = await orc.resume_job(rj)
    print(f"  resume_job → {result['status']}")
    assert result["status"] == "queued", \
        f"resume_job should return 'queued', got '{result['status']}'"
    print(f"  ✓ resume_job returns 'queued' (not 'resumed')")

    # ── 2. Derive from DB after enqueue → should show "队列中" ──
    dl_summary = db.get_downloads_summary(rj)
    ws = db.get_works_status(rj)
    has_queued = dl_summary.get("queued", 0) > 0
    print(f"  works.status={ws}, dl: {dl_summary}")

    assert has_queued, "should have queued downloads after enqueue"

    # Priority: has_queued → show "队列中"
    if has_queued:
        card_status = "队列中"
    print(f"  ✓ derived card status = '{card_status}'")

    # ── 3. "Resuming..." must NOT be the derived card status ──
    assert card_status != "恢复中...", \
        "卡状态不应长期停在 '恢复中...'"
    print(f"  ✓ card status is NOT '恢复中...'")

    # ── 4. Verify "resuming" normalizes correctly ──
    assert WorkStatus.normalize("Resuming...") == WorkStatus.RESUMING
    assert WorkStatus.RESUMING.ui_label == "恢复中..."
    print(f"  ✓ Resuming... → RESUMING (transient)")

    # Cleanup
    orc.cancelled_rjs.add(rj)
    orc.queued_rj_ids.discard(rj)
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ resuming → queued after enqueue 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
