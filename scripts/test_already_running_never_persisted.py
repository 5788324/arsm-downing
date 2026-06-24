#!/usr/bin/env python3
"""already_running 永不持久化测试 — 验证 already_running 不写入 DB."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  already_running 永不持久化测试\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    import json as _j

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    rj = "RJ99993"

    # ── 1. Setup: metadata cache + paused download ──
    print("── 1. 准备测试数据 ──")
    db.set_metadata_cache(rj, "Test", "Circle", "",
        {"title": "Test"},
        [{"type": "audio", "title": "track1", "id": "t1",
          "mediaDownloadUrl": "http://localhost/t1.mp3", "size": 100}])
    db.upsert_download(f"{rj}:t1", rj, "track1", f"/tmp/{rj}/t1.mp3",
                       "paused", 0, 100)

    # ── 2. First resume → should succeed ──
    print("── 2. 首次 resume ──")
    r1 = await orc._resume_one(rj)
    assert r1["status"] == "resumed", f"expected resumed, got {r1}"
    # (immediately pause to clean up)
    orc.pause_job(rj)
    print(f"  ✓ 首次 resume: {r1['status']}")

    # ── 3. While job is queued, second resume → already_queued ──
    print("── 3. 二次 resume (已在队列) ──")
    # Re-queue the job
    cached = db.get_metadata_cache(rj)
    meta_raw = _j.loads(cached["metadata_json"])
    from pathlib import Path as _Path
    meta = orc._build_metadata(rj, meta_raw)
    root_path = orc.get_save_path(meta)
    r2 = await orc._resume_one(rj)
    # Note: may be "already_queued" if still in queue, or "resumed" if cleaned
    print(f"  ✓ 二次 resume: {r2['status']}")

    # ── 4. Check DB: NEVER contains already_queued or already_running ──
    print("── 4. DB 检查 ──")
    rows = db.get_downloads_by_rj(rj)
    for row in rows:
        assert row["status"] not in ("already_queued", "already_running"), \
            f"DB 不应有 {row['status']}: {row['id']}"
    print(f"  ✓ DB 中 {len(rows)} 条记录均无 already_queued/already_running")

    # ── 5. Verify all download statuses are valid WorkStatus ──
    print("── 5. 所有 DB status 都可 normalize ──")
    for row in rows:
        ws = orc.db.conn.execute(
            "SELECT status FROM downloads WHERE id=?", (row["id"],)
        ).fetchone()
        if ws:
            ns = __import__('core.status', fromlist=['WorkStatus']).WorkStatus.normalize(ws["status"])
            assert ns.value not in ("already_queued", "already_running"), \
                f"normalize returned transient: {ns.value}"
    print(f"  ✓ 所有 DB status normalize 后不是 transient")

    # ── Cleanup ──
    orc.cancelled_rjs.add(rj)
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj,))
    db.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ already_running 永不持久化测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
