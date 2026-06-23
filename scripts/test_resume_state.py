#!/usr/bin/env python3
"""下载状态恢复测试 — 验证 downloads 表正确记录/恢复状态。

用法:
    python scripts/test_resume_state.py RJ01603020
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigManager
from core.database import LibraryVault


async def test(rj_input: str):
    if not rj_input.upper().startswith("RJ"):
        rj_code = f"RJ{rj_input}"
    else:
        rj_code = rj_input.upper()

    print(f"\n{'='*60}")
    print(f"  下载状态恢复测试: {rj_code}")
    print(f"{'='*60}\n")

    config = ConfigManager.load()
    db = LibraryVault()

    # Clean slate
    db.conn.execute("DELETE FROM downloads WHERE rj_id = ?", (rj_code,))
    db.conn.commit()

    # ── 1. 模拟创建任务 ──
    print("── 1. 创建模拟下载任务 ──")
    test_tracks = [
        ("track_01", "Track One.mp3", 1024000),
        ("track_02", "Track Two.wav", 2048000),
        ("track_03", "Track Three.flac", 512000),
    ]
    for tid, tname, tsize in test_tracks:
        dl_id = f"{rj_code}:{tid}"
        local = f"Downloads/{rj_code}/{tname}"
        db.upsert_download(dl_id, rj_code, tname, local,
                            'queued', 0, tsize)
        print(f"  ✓ {dl_id} → queued ({tsize} bytes)")

    # ── 2. 模拟开始下载 ──
    print("\n── 2. 模拟下载中 ──")
    for tid, tname, tsize in test_tracks:
        dl_id = f"{rj_code}:{tid}"
        local = f"Downloads/{rj_code}/{tname}"
        db.upsert_download(dl_id, rj_code, tname, local,
                            'downloading', tsize // 2, tsize)
        print(f"  → {dl_id} downloading {tsize//2}/{tsize} bytes")

    # ── 3. 模拟暂停 ──
    print("\n── 3. 模拟暂停 track_02 ──")
    db.upsert_download(f"{rj_code}:track_02", rj_code, "Track Two.wav",
                        f"Downloads/{rj_code}/Track Two.wav",
                        'paused', 1024000, 2048000)
    print(f"  ✓ {rj_code}:track_02 → paused")

    # ── 4. 模拟完成 track_01 ──
    print("\n── 4. 模拟完成 track_01 ──")
    db.upsert_download(f"{rj_code}:track_01", rj_code, "Track One.mp3",
                        f"Downloads/{rj_code}/Track One.mp3",
                        'completed', 1024000, 1024000)
    print(f"  ✓ {rj_code}:track_01 → completed")

    # ── 5. 模拟失败 track_03 ──
    print("\n── 5. 模拟失败 track_03 ──")
    db.upsert_download(f"{rj_code}:track_03", rj_code, "Track Three.flac",
                        f"Downloads/{rj_code}/Track Three.flac",
                        'failed', 0, 512000, error="Connection reset")
    print(f"  ✓ {rj_code}:track_03 → failed")

    # ── 6. 查询所有状态 ──
    print("\n── 6. 查询所有下载状态 ──")
    all_dl = db.get_downloads_by_rj(rj_code)
    statuses = {}
    for row in all_dl:
        statuses[row["id"]] = row["status"]
        print(f"  {row['id']}: {row['status']} "
              f"({row['downloaded_bytes']}/{row['total_bytes']} bytes)")

    assert len(all_dl) == 3, f"期望 3 条, 实际 {len(all_dl)}"
    assert statuses[f"{rj_code}:track_01"] == "completed"
    assert statuses[f"{rj_code}:track_02"] == "paused"
    assert statuses[f"{rj_code}:track_03"] == "failed"

    # ── 7. 模拟程序退出后重新查询 ──
    print("\n── 7. 模拟程序退出后恢复 ──")
    # Re-open DB
    db2 = LibraryVault()
    try:
        pending = db2.get_pending_downloads()
        print(f"  待恢复任务 ({len(pending)}):")
        for row in pending:
            print(f"    {row['id']}: {row['status']} "
                  f"({row['downloaded_bytes']}/{row['total_bytes']})")

        # completed 不应出现在 pending 中
        pending_ids = {r["id"] for r in pending}
        assert f"{rj_code}:track_01" not in pending_ids, \
            "completed 任务不应出现在待恢复列表!"

        # paused & downloading 应出现
        assert f"{rj_code}:track_02" in pending_ids, \
            "paused 任务应在待恢复列表!"
    finally:
        db2.conn.close()

    # ── 8. 清理 terminal 状态 ──
    print("\n── 8. 清理 terminal 状态 ──")
    db.clear_terminal_downloads(rj_code)
    remaining = db.get_downloads_by_rj(rj_code)
    print(f"  清理后剩余: {len(remaining)} 条")
    for row in remaining:
        print(f"    {row['id']}: {row['status']}")
    # Only paused/downloading/queued should remain
    remaining_ids = {r["id"] for r in remaining}
    assert f"{rj_code}:track_01" not in remaining_ids, "completed 应被清除!"
    assert f"{rj_code}:track_03" not in remaining_ids, "failed 应被清除!"
    assert f"{rj_code}:track_02" in remaining_ids, "paused 应保留!"

    # Clean up
    db.conn.execute("DELETE FROM downloads WHERE rj_id = ?", (rj_code,))
    db.conn.commit()

    print(f"\n{'='*60}")
    print(f"  ✓ 下载状态恢复测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "RJ01603020"
    sys.exit(asyncio.run(test(code)))
