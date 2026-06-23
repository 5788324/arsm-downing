#!/usr/bin/env python3
"""Orchestrator 级缓存测试 — monkeypatch 验证第二次不请求 API。

用法:
    python scripts/test_orchestrator_cache.py RJ01603020
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import LibraryVault


async def test(rj_input: str):
    if not rj_input.upper().startswith("RJ"):
        rj_code = f"RJ{rj_input}"
    else:
        rj_code = rj_input.upper()

    print(f"\n{'='*60}")
    print(f"  Orchestrator 级缓存测试: {rj_code}")
    print(f"{'='*60}\n")

    db = LibraryVault()

    # Clean old cache
    db.invalidate_cache(rj_code)
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj_code,))
    db.conn.commit()

    from core.config import ConfigManager
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    config = ConfigManager.load()
    kernel = NetworkKernel(config)

    # ── 第 1 次: 真实联网 ──
    print("── 第 1 次 queue_job: 允许联网 ──")
    orc1 = Orchestrator(kernel, config, db)
    orc1.set_callbacks(
        lambda *a: None,  # no-op progress
        lambda rj, st: print(f"  status: {rj} → {st}")
    )

    # Start worker in background so queue gets consumed
    worker = asyncio.create_task(orc1.boot_worker())

    await orc1.queue_job(rj_code, force_refresh=True)
    await asyncio.sleep(0.5)  # let worker pick up the task

    # Cancel the download task (we don't want to actually download)
    orc1.pause_job(rj_code)
    await asyncio.sleep(0.5)

    worker.cancel()
    try: await worker
    except asyncio.CancelledError: pass

    print(f"  ✓ 第 1 次完成，缓存已写入")

    # ── 第 2 次: monkeypatch 验证不走 API ──
    print(f"\n── 第 2 次 queue_job: monkeypatch kernel.fetch ──")
    api_called = False
    original_fetch = kernel.fetch

    async def monitored_fetch(*args, **kwargs):
        nonlocal api_called
        api_called = True
        raise AssertionError(
            f"BUG: kernel.fetch called on second run! "
            f"Cache should have been used. args={args}")

    kernel.fetch = monitored_fetch

    orc2 = Orchestrator(kernel, config, db)
    orc2.set_callbacks(
        lambda *a: None,
        lambda rj, st: print(f"  status: {rj} → {st}")
    )

    try:
        worker2 = asyncio.create_task(orc2.boot_worker())
        await orc2.queue_job(rj_code, force_refresh=False)
        await asyncio.sleep(0.5)
        orc2.pause_job(rj_code)
        await asyncio.sleep(0.5)
        worker2.cancel()
        try: await worker2
        except asyncio.CancelledError: pass
    finally:
        kernel.fetch = original_fetch

    if api_called:
        print(f"\n  ✗ 失败: kernel.fetch 在第 2 次被调用了")
        print(f"  → 缓存没有生效，二次查询仍然走了 API")
        return 1

    print(f"  ✓ kernel.fetch 未被调用 — 缓存生效")
    print(f"\n{'='*60}")
    print(f"  ✓ Orchestrator 级缓存测试通过")
    print(f"{'='*60}\n")

    # Cleanup
    db.invalidate_cache(rj_code)
    await kernel.shutdown()
    return 0


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "RJ01603020"
    sys.exit(asyncio.run(test(code)))
