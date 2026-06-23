#!/usr/bin/env python3
"""批量控制 + 路径锁定 + 资源库重建 集成测试."""

import asyncio
import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  P3.5 集成测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # ── 1. Batch pause_all ──
    print("── 1. batch pause_all ──")
    # Write some queued/downloading states
    for rj, status in [("RJ99991", "queued"), ("RJ99992", "downloading"),
                        ("RJ99993", "completed"), ("RJ99994", "paused")]:
        db.upsert_download(f"{rj}:t1", rj, "track", f"/tmp/{rj}/t.mp3",
                           status, 0, 100)
    orc.pause_all()

    for rj, expected in [("RJ99991", "paused"), ("RJ99992", "paused"),
                          ("RJ99993", "completed"), ("RJ99994", "paused")]:
        rows = db.get_downloads_by_rj(rj)
        for r in rows:
            assert r["status"] == expected, \
                f"{rj} 应为 {expected}, 实际 {r['status']}"
    print(f"  ✓ pause_all: queued/downloading→paused, completed 不变")

    # ── 2. Path locking ──
    print("\n── 2. 路径锁定 ──")
    old_dir = cfg.output_dir
    assert db.conn.execute(
        "SELECT local_path FROM downloads WHERE rj_id='RJ99991'"
    ).fetchone()["local_path"] == f"/tmp/RJ99991/t.mp3"
    cfg.output_dir = Path("/different/path")
    # Path should still be old
    rows = db.get_downloads_by_rj("RJ99991")
    assert rows[0]["local_path"] == f"/tmp/RJ99991/t.mp3", \
        "路径不应随 output_dir 改变"
    cfg.output_dir = old_dir
    print(f"  ✓ 路径锁定: 旧任务保留原路径")

    # ── 3. Library rebuild ──
    print("\n── 3. 资源库重建 ──")
    tmp = tempfile.mkdtemp()
    rj_dir = Path(tmp) / "RJ01603020 TestRebuild"
    rj_dir.mkdir()
    (rj_dir / "f.mp3").write_bytes(b"z" * 300)

    result = db.rebuild_library([tmp])
    assert result["found"] == 1
    assert result["indexed"] == 1, f"应 indexed=1, {result}"

    row = db.conn.execute(
        "SELECT status FROM works WHERE rj_id='RJ01603020'"
    ).fetchone()
    assert row["status"] == "external"
    print(f"  ✓ rebuild: found={result['found']}, indexed={result['indexed']}")
    print(f"  ✓ works.status = external")

    # Cleanup
    for rj in ["RJ99991","RJ99992","RJ99993","RJ99994","RJ01603020"]:
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM library_index")
    db.conn.commit()
    await kernel.shutdown()
    shutil.rmtree(tmp)

    print(f"\n{'='*60}")
    print(f"  ✓ P3.5 集成测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
