#!/usr/bin/env python3
"""同路径多目录测试 — 两个 RJ01603020 目录不被覆盖."""

import asyncio
import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  同路径多目录测试")
    print(f"{'='*60}\n")

    from core.database import LibraryVault

    db = LibraryVault()
    tmp = tempfile.mkdtemp()

    d1 = Path(tmp) / "sub1" / "RJ01603020 AAA"
    d1.parent.mkdir()
    d1.mkdir()
    (d1 / "a.mp3").write_bytes(b"x" * 100)

    d2 = Path(tmp) / "sub2" / "RJ01603020 BBB"
    d2.parent.mkdir()
    d2.mkdir()
    (d2 / "b.wav").write_bytes(b"y" * 200)

    print(f"  创建: {d1}")
    print(f"  创建: {d2}")

    found = db.scan_library_paths([str(Path(tmp) / "sub1"), str(Path(tmp) / "sub2")])
    print(f"  发现: {found}")
    assert found == 2, f"应发现 2, 实际 {found}"

    entries = db.find_in_library("RJ01603020")
    assert len(entries) == 2, f"应有 2 条, 实际 {len(entries)}"
    for e in entries:
        print(f"  {e['work_dir']}")
    print(f"  ✓ 两个目录共存, 无覆盖")

    db.conn.execute("DELETE FROM library_index")
    db.conn.commit()
    shutil.rmtree(tmp)

    print(f"\n{'='*60}")
    print(f"  ✓ 同路径多目录测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
