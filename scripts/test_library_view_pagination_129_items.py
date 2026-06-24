#!/usr/bin/env python3
"""资源库分页测试 — 验证 129 个作品可通过分页完整访问."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  资源库分页 129 项测试\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    # ── 1. Insert 129 test works ──
    print("── 1. 插入 129 个测试作品 ──")
    for i in range(1, 130):
        rj = f"RJ{90000000 + i:08d}"
        meta = WorkMetadata(rj_id=rj, title=f"Test Item {i:03d}",
                            circle=f"Circle {i % 10}", cv=[], tags=[],
                            price=0, source_url="", dl_count=0,
                            rating=0.0, release_date="", cover_url="")
        db.register(meta, i * 100, Path(f"/tmp/{rj}"), status="external")

    # ── 2. Verify search returns all without limit ──
    print("── 2. search() 返回全部 (不设 limit) ──")
    all_results = db.search("", offset=0, limit=0)
    test_count = sum(1 for r in all_results if r["rj_id"].startswith("RJ900"))
    assert test_count >= 129, f"应该返回 >=129 项, 实际 {test_count}"
    print(f"  ✓ search(limit=0) 返回 {test_count} 项 (>=129)")

    # ── 3. Verify pagination ──
    print("── 3. 分页验证 ──")
    LIBRARY_PAGE_SIZE = 30
    seen = set()
    page_count = 0
    for page in range(10):
        results = db.search("", offset=page * LIBRARY_PAGE_SIZE,
                            limit=LIBRARY_PAGE_SIZE, status_filter="external")
        for r in results:
            if r["rj_id"].startswith("RJ900"):
                seen.add(r["rj_id"])
        page_count += 1
        if page_count * LIBRARY_PAGE_SIZE >= 129:
            break
    assert len(seen) >= 129, f"分页应覆盖 >=129 项, 实际 {len(seen)}"
    print(f"  ✓ 分页覆盖 {len(seen)} 个不同 RJ (>=129)")

    # ── 4. Verify status filter ──
    print("── 4. 状态过滤 ──")
    ext_results = db.search("", limit=0, status_filter="external")
    ext_count = sum(1 for r in ext_results if r["rj_id"].startswith("RJ900"))
    assert ext_count >= 129, f"external 过滤应返回 >=129, 实际 {ext_count}"
    print(f"  ✓ status_filter='external' 返回 {ext_count} 项")

    # Non-existent filter returns empty
    empty = db.search("", limit=0, status_filter="nonexistent")
    assert len(empty) == 0, f"不存在的状态应返回空, 实际 {len(empty)}"
    print(f"  ✓ 不存在状态返回空列表")

    # ── 5. Count by status ──
    print("── 5. count_library_by_status ──")
    counts = db.count_library_by_status()
    assert counts["__total__"] >= 129, f"总数应 >=129, 实际 {counts['__total__']}"
    assert counts.get("external", 0) >= 129, f"external 计数应 >=129, 实际 {counts.get('external',0)}"
    print(f"  ✓ 总数={counts['__total__']}, external={counts.get('external',0)}")

    # ── Cleanup ──
    print("── 清理 ──")
    for i in range(1, 130):
        rj = f"RJ{90000000 + i:08d}"
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.commit()

    print(f"\n{'='*60}\n  ✓ 资源库分页测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
