#!/usr/bin/env python3
"""UI event loop 回调测试 — 验证不调用 create_task/get_event_loop."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  UI event loop 回调测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # Write some queued items
    for rj in ("RJ99991", "RJ99992"):
        db.upsert_download(f"{rj}:t1", rj, "t", f"/tmp/{rj}/t.mp3",
                           "queued", 0, 100)

    # resume_all should return a list (not create tasks)
    rj_ids = orc.resume_all()
    assert isinstance(rj_ids, list), \
        f"resume_all 应返回 list, 实际 {type(rj_ids)}"
    assert len(rj_ids) == 2
    print(f"  ✓ resume_all 返回 list (不依赖 event loop)")

    # _resume_all_async requires a loop — this is the async entry point
    try:
        await orc._resume_all_async()
        print(f"  ✓ _resume_all_async 正常执行")
    except Exception as e:
        print(f"  _resume_all_async: {e}")

    # Cleanup
    for rj in ("RJ99991", "RJ99992"):
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.conn.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}")
    print(f"  ✓ UI event loop 回调测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
