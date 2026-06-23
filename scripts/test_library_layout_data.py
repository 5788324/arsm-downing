#!/usr/bin/env python3
"""资源库布局数据测试 — 验证卡片生成不为空."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  资源库布局数据测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    # Write test works
    for status in ("completed", "partial", "external"):
        rj = f"RJ9990{status[0]}"
        meta = WorkMetadata(rj_id=rj, title=f"Test {status}",
                            circle="TC", cv=[], tags=[], price=0,
                            source_url="", dl_count=0, rating=0.0,
                            release_date="", cover_url="")
        db.register(meta, 100, Path(f"/tmp/{rj}"), status=status)

    results = db.search("")
    # Filter our test entries
    test_entries = [r for r in results if r["rj_id"].startswith("RJ9990")]
    assert len(test_entries) == 3, f"应有 3 条, 实际 {len(test_entries)}"

    statuses = {r["status"] for r in test_entries}
    assert "completed" in statuses
    assert "partial" in statuses
    assert "external" in statuses
    print(f"  ✓ 3 works with distinct statuses loaded")

    # Verify STATUS_LABELS covers all
    from ui.views.library_view import STATUS_LABELS
    for s in ("completed", "partial", "external", "verified", "missing"):
        assert s in STATUS_LABELS, f"STATUS_LABELS 缺 {s}"
        print(f"  ✓ STATUS_LABELS[{s}] = {STATUS_LABELS[s][0]}")

    # Cleanup
    for rj in ("RJ9990c", "RJ9990p", "RJ9990e"):
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.commit()

    print(f"\n{'='*60}")
    print(f"  ✓ 资源库布局数据测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
