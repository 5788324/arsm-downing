#!/usr/bin/env python3
"""Orchestrator 恢复测试 — 验证 restore_pending_downloads 重建任务并入队 (auto_resume=True)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  Orchestrator 恢复测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    import json as _json

    rj_code = "RJ99997"
    cfg = ConfigManager.load()
    # RC7.9: must set auto_resume_on_start=True for this test
    cfg.auto_resume_on_start = True
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # ── 1. 写 metadata_cache ──
    print("── 1. 准备测试数据 ──")
    meta_raw = {
        "title": "Test Restore", "circle": {"name": "TC"},
        "vas": [], "tags": [], "price": 0, "source_url": "",
        "dl_count": 0, "rate_average_2dp": 0.0,
        "release_date": "2024-01-01", "mainCoverUrl": ""
    }
    tracks_raw = [
        {"type": "audio", "title": "track_a.mp3", "id": "t1",
         "mediaDownloadUrl": "http://example.com/a.mp3", "size": 100},
        {"type": "audio", "title": "track_b.wav", "id": "t2",
         "mediaDownloadUrl": "http://example.com/b.wav", "size": 200},
        {"type": "audio", "title": "track_c.flac", "id": "t3",
         "mediaDownloadUrl": "http://example.com/c.flac", "size": 300},
    ]
    db.set_metadata_cache(rj_code, "Test Restore", "TC", "",
                          meta_raw, tracks_raw)

    # ── 2. 写 downloads: paused, completed, failed ──
    print("── 2. 写入 downloads 状态 ──")
    save_root = cfg.output_dir / f"{rj_code} Test Restore"
    states = [
        ("t1", "track_a.mp3", "paused", 50, 100),
        ("t2", "track_b.wav", "completed", 200, 200),
        ("t3", "track_c.flac", "failed", 0, 300),
    ]
    for tid, tname, status, dl_bytes, total in states:
        spath = str(save_root / tname)
        dl_id = orc._make_dl_id(rj_code, tid, save_root / tname, tname)
        db.upsert_download(dl_id, rj_code, tname, spath,
                           status, dl_bytes, total)
        print(f"  {dl_id}: {status} ({dl_bytes}/{total})")

    # ── 3. monkeypatch _process_download ──
    captured_targets = []

    async def fake_process_download(rj, meta, targets, root):
        nonlocal captured_targets
        captured_targets = list(targets)
        print(f"  _process_download called with {len(targets)} targets")

    # Save real method
    real_process = orc._process_download
    orc._process_download = fake_process_download

    # ── 4. 启动 worker 并恢复 ──
    print("\n── 3. 启动 worker + 恢复 ──")
    worker = asyncio.create_task(orc.boot_worker())

    orc.set_callbacks(
        lambda *a: None,
        lambda rj, st: print(f"  status: {rj} → {st}")
    )

    await orc.restore_pending_downloads()
    await asyncio.sleep(1.0)  # let worker consume

    # ── 5. 验证 ──
    print(f"\n── 4. 验证 ──")
    print(f"  恢复的 targets 数量: {len(captured_targets)}")
    assert len(captured_targets) == 1, \
        f"应只恢复 1 个(paused), 实际 {len(captured_targets)}"

    restored_track = captured_targets[0]
    print(f"  恢复的 track: {restored_track.title}")
    assert restored_track.id == "t1", \
        f"应恢复 t1, 实际 {restored_track.id}"

    # Cleanup
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass
    orc._process_download = real_process

    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?", (rj_code,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj_code,))
    db.conn.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}")
    print(f"  ✓ Orchestrator 恢复测试通过")
    print(f"  → 只恢复 paused, 不恢复 completed/failed")
    print(f"  → 任务正确重建并入 download_queue")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
