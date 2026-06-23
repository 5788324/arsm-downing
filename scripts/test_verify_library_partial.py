#!/usr/bin/env python3
"""验证库完整性测试 — 缺文件时 status=partial."""

import asyncio
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  验证库完整性测试")
    print(f"{'='*60}\n")

    from core.database import LibraryVault

    db = LibraryVault()

    tmp = tempfile.mkdtemp()
    rj = "RJ99999"
    work_dir = Path(tmp) / "RJ99999 Test"
    work_dir.mkdir()

    # Write works entry
    db.conn.execute(
        "INSERT OR REPLACE INTO works(rj_id,title,local_path,status) VALUES(?,?,?,?)",
        (rj, "Test", str(work_dir), "external"))
    db.conn.commit()

    # Fake metadata tracks — expect 3 files
    tracks = [
        {"type": "audio", "title": "track1.mp3", "id": "1"},
        {"type": "audio", "title": "track2.wav", "id": "2"},
        {"type": "audio", "title": "track3.flac", "id": "3"},
    ]

    # Only create 1 of 3 files
    (work_dir / "track1.mp3").write_bytes(b"x" * 100)

    # Verify
    status = db.verify_library_item(rj, str(work_dir), tracks)
    print(f"  1/3 files → status: {status}")
    assert status == "partial", f"应为 partial, 实际 {status}"

    # Now create all files
    (work_dir / "track2.wav").write_bytes(b"y" * 200)
    (work_dir / "track3.flac").write_bytes(b"z" * 300)

    status2 = db.verify_library_item(rj, str(work_dir), tracks)
    print(f"  3/3 files → status: {status2}")
    assert status2 == "verified", f"应为 verified, 实际 {status2}"

    # Part file
    (work_dir / "extra.part").write_bytes(b"p" * 10)
    status3 = db.verify_library_item(rj, str(work_dir), tracks)
    print(f"  3/3 + .part → status: {status3}")
    assert status3 == "partial", f".part 应导致 partial, 实际 {status3}"

    # Missing directory
    shutil.rmtree(work_dir)
    status4 = db.verify_library_item(rj, str(work_dir), tracks)
    print(f"  dir deleted → status: {status4}")
    assert status4 == "missing", f"应为 missing, 实际 {status4}"

    # Cleanup
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.commit()

    print(f"\n{'='*60}")
    print(f"  ✓ 验证库完整性测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
