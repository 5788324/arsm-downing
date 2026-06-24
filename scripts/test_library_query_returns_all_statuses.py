#!/usr/bin/env python3
"""资源库查询返回所有状态测试 — 验证 search() 不按状态过滤返回全部."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  资源库查询返回所有状态测试\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()

    # ── Insert works with every status ──
    statuses = ["completed", "partial", "external", "verified",
                "missing", "indexed", "metadata_failed", "prepared"]
    for i, st in enumerate(statuses):
        rj = f"RJ{99000000 + i:08d}"
        meta = WorkMetadata(rj_id=rj, title=f"Status {st}",
                            circle="Test", cv=[], tags=[], price=0,
                            source_url="", dl_count=0, rating=0.0,
                            release_date="", cover_url="")
        db.register(meta, 100, Path(f"/tmp/{rj}"), status=st)

    # ── search() with no status_filter returns all ──
    results = db.search("", offset=0, limit=0)
    test_rjs = [r for r in results if r["rj_id"].startswith("RJ990")]
    found_statuses = {r["status"] for r in test_rjs}
    print(f"  查询返回 {len(test_rjs)} 个测试作品")

    for st in statuses:
        assert st in found_statuses, f"状态 {st} 应该在结果中!"
        print(f"  ✓ 状态 '{st}' 存在")

    # ── count_library_by_status covers all ──
    counts = db.count_library_by_status()
    for st in statuses:
        assert counts.get(st, 0) >= 1, f"计数中应有 {st}"
    print(f"  ✓ count_library_by_status 包含所有状态: {counts}")

    # ── Cleanup ──
    for i in range(len(statuses)):
        rj = f"RJ{99000000 + i:08d}"
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.commit()

    print(f"\n{'='*60}\n  ✓ 资源库查询返回所有状态测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
