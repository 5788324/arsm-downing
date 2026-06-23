#!/usr/bin/env python3
"""去重检测测试 — 验证 library_index 中已存在时返回 duplicate 信息."""

import asyncio
import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  去重检测测试")
    print(f"{'='*60}\n")

    from core.database import LibraryVault

    db = LibraryVault()

    # ── 1. Insert known entry ──
    rj_code = "RJ01603020"
    lib_path = "/fake/library"
    work_dir = f"{lib_path}/RJ01603020 Test"

    db.upsert_library_entry(rj_code, lib_path, work_dir, 1000, 5, 'found')
    print(f"── 1. 已写入: {rj_code} @ {work_dir}")

    # ── 2. Check for duplicate ──
    print(f"\n── 2. 查重 ──")
    entries = db.find_in_library(rj_code)
    assert len(entries) >= 1, f"应找到 {rj_code}"
    print(f"  发现 {len(entries)} 条记录")

    for e in entries:
        print(f"    {e['rj_id']} → {e['work_dir']} [{e['status']}]")

    # ── 3. Non-existent RJ ──
    print(f"\n── 3. 不存在的 RJ ──")
    missing = db.find_in_library("RJ00000000")
    assert len(missing) == 0, "不存在的 RJ 应返回空"
    print(f"  ✓ 未找到 (正确)")

    # ── 4. Upsert duplicate (same rj_id + library_path) ──
    print(f"\n── 4. 更新已存在记录 ──")
    db.upsert_library_entry(rj_code, lib_path, work_dir,
                            2000, 10, 'found')
    entries2 = db.find_in_library(rj_code)
    assert len(entries2) == 1, "同 rj+path 不应重复"
    assert entries2[0]["file_count"] == 10
    print(f"  ✓ 更新正确, 仍为 1 条, file_count=10")

    # Cleanup
    db.conn.execute("DELETE FROM library_index")
    db.conn.commit()

    print(f"\n{'='*60}")
    print(f"  ✓ 去重检测测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
