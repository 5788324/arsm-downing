#!/usr/bin/env python3
"""仓库状态显示测试 — 验证 works 表 completed/partial 正确."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  仓库状态显示测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    from core.models import WorkMetadata

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    rj_a = "RJ88881"
    rj_b = "RJ88882"

    # Clean
    for rj in (rj_a, rj_b):
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.commit()

    # Write completed
    meta_a = WorkMetadata(rj_id=rj_a, title="Complete Work", circle="TC",
                          cv=[], tags=[], price=0, source_url="", dl_count=0,
                          rating=0.0, release_date="", cover_url="")
    db.register(meta_a, 1000, Path("/tmp/rj_a"), status='completed')

    # Write partial
    meta_b = WorkMetadata(rj_id=rj_b, title="Partial Work", circle="TC",
                          cv=[], tags=[], price=0, source_url="", dl_count=0,
                          rating=0.0, release_date="", cover_url="")
    db.register(meta_b, 500, Path("/tmp/rj_b"), status='partial')

    # ── Query and verify ──
    print("── 查询 works 表 ──")
    rows = db.search("")
    found = {}
    for row in rows:
        if row["rj_id"] in (rj_a, rj_b):
            found[row["rj_id"]] = row["status"]
            print(f"  {row['rj_id']}: {row['title']} → {row['status']}")

    assert found.get(rj_a) == "completed", \
        f"complete work 状态应为 completed, 实际: {found.get(rj_a)}"
    assert found.get(rj_b) == "partial", \
        f"partial work 状态应为 partial, 实际: {found.get(rj_b)}"

    print("  ✓ completed 和 partial 正确区分")

    # ── Test STATUS_LABELS mapping ──
    from ui.views.library_view import STATUS_LABELS

    assert STATUS_LABELS["completed"][0] == "已完成"
    assert STATUS_LABELS["partial"][0] == "部分完成"
    assert STATUS_LABELS["missing"][0] == "文件缺失"
    print("  ✓ STATUS_LABELS 映射正确")

    # Clean
    for rj in (rj_a, rj_b):
        db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}")
    print(f"  ✓ 仓库状态显示测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
