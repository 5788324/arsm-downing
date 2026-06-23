#!/usr/bin/env python3
"""纯数字目录扫描测试 — 01603020 也能识别为 RJ01603020."""

import asyncio
import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  纯数字目录扫描测试")
    print(f"{'='*60}\n")

    from core.database import LibraryVault

    db = LibraryVault()
    tmp = tempfile.mkdtemp()
    (Path(tmp) / "01603020").mkdir()
    (Path(tmp) / "01603020" / "test.mp3").write_bytes(b"x" * 100)

    print(f"── 扫描 01603020 目录 ──")
    found = db.scan_library_paths([tmp])
    print(f"  发现: {found}")
    assert found == 1

    entries = db.find_in_library("RJ01603020")
    assert len(entries) == 1
    print(f"  ✓ 识别为 {entries[0]['rj_id']} (zfill 8)")

    db.conn.execute("DELETE FROM library_index")
    db.conn.commit()
    shutil.rmtree(tmp)

    print(f"\n{'='*60}")
    print(f"  ✓ 纯数字目录扫描测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
