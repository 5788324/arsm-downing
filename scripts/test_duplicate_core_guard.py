#!/usr/bin/env python3
"""核心层重复保护测试 — prepare_work 默认阻断已存在 RJ."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  核心层重复保护测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    cfg = ConfigManager.load()
    db = LibraryVault()

    rj = "RJ88885"
    db.upsert_library_entry(rj, "/tmp/lib", f"/tmp/lib/{rj} Test",
                            1000, 5, 'found')
    print(f"── library_index 已注册 {rj}")

    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)
    orc.set_callbacks(
        lambda e: None,
        lambda rj_id, st: print(f"  status: {rj_id} → {st}")
    )

    # ── Without allow_duplicate → blocked ──
    print(f"\n── prepare_work(allow_duplicate=False) ──")
    meta, targets, root, cached = await orc.prepare_work(rj, force_refresh=False)
    assert meta is None, "重复时应返回 None"
    print(f"  ✓ 重复被阻断 (meta=None)")

    # ── With allow_duplicate → allowed ──
    print(f"\n── prepare_work(allow_duplicate=True) ──")
    # Monkeypatch fetch to avoid real API call
    api_called = False
    original = kernel.fetch

    async def fake_fetch(endpoint, params=None):
        nonlocal api_called
        api_called = True
        if "workInfo" in endpoint:
            return {"title": "Test", "circle": {"name": "TC"},
                    "vas": [], "tags": [], "price": 0, "source_url": "",
                    "dl_count": 0, "rate_average_2dp": 0.0,
                    "release_date": "", "mainCoverUrl": ""}
        return [{"type": "audio", "title": "t.mp3", "id": "1",
                 "mediaDownloadUrl": "http://x.com/t.mp3", "size": 100}]

    kernel.fetch = fake_fetch
    meta2, targets2, root2, cached2 = await orc.prepare_work(
        rj, force_refresh=True, allow_duplicate=True)
    kernel.fetch = original

    assert meta2 is not None, "allow_duplicate=True 时应允许"
    assert api_called, "应调用 API"
    print(f"  ✓ allow_duplicate=True 允许下载")

    # Cleanup
    db.conn.execute("DELETE FROM library_index")
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj,))
    db.invalidate_cache(rj)
    db.conn.commit()
    await kernel.shutdown()

    print(f"\n{'='*60}")
    print(f"  ✓ 核心层重复保护测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
