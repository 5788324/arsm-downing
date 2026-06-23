#!/usr/bin/env python3
"""library_index 扫描测试 — 验证扫描逻辑."""

import asyncio
import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  library_index 扫描测试")
    print(f"{'='*60}\n")

    from core.database import LibraryVault

    db = LibraryVault()

    # ── 1. Create temp library with fake RJ folders ──
    print("── 1. 创建临时仓库目录 ──")
    tmp_lib = tempfile.mkdtemp()

    # Create RJ01603020 folder with files
    rj_dir = Path(tmp_lib) / "RJ01603020 Test Work"
    rj_dir.mkdir()
    (rj_dir / "file1.mp3").write_bytes(b"x" * 100)
    (rj_dir / "file2.wav").write_bytes(b"y" * 200)

    # Create nested folder
    sub_dir = Path(tmp_lib) / "extra" / "RJ01234567 Nested"
    sub_dir.parent.mkdir()
    sub_dir.mkdir()
    (sub_dir / "track.flac").write_bytes(b"z" * 500)

    print(f"  创建: {rj_dir}")
    print(f"  创建: {sub_dir}")

    # ── 2. Scan ──
    print(f"\n── 2. 扫描 library_paths ──")
    found = db.scan_library_paths([tmp_lib])
    print(f"  发现: {found} 个作品")
    assert found >= 2, f"应发现 >=2, 实际 {found}"

    # ── 3. Verify ──
    print(f"\n── 3. 验证 library_index ──")
    entries_020 = db.find_in_library("RJ01603020")
    entries_345 = db.find_in_library("RJ01234567")

    assert len(entries_020) >= 1, "RJ01603020 应在 library_index 中"
    assert len(entries_345) >= 1, "RJ01234567 应在 library_index 中"

    for e in entries_020:
        print(f"  {e['rj_id']}: {e['work_dir']} "
              f"({e['file_count']} files, {e['size_bytes']} bytes)")
    for e in entries_345:
        print(f"  {e['rj_id']}: {e['work_dir']} "
              f"({e['file_count']} files, {e['size_bytes']} bytes)")

    assert entries_020[0]["file_count"] == 2
    assert entries_345[0]["file_count"] == 1

    print(f"  ✓ 扫描结果正确")

    # Cleanup
    db.conn.execute("DELETE FROM library_index")
    db.conn.commit()
    shutil.rmtree(tmp_lib)

    print(f"\n{'='*60}")
    print(f"  ✓ library_index 扫描测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
