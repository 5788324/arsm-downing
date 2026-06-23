#!/usr/bin/env python3
"""prepare_work 测试 — 验证预准备流程."""

import asyncio
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  prepare_work 测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator

    rj_code = "RJ01603020"
    cfg = ConfigManager.load()
    tmpdir = tempfile.mkdtemp()
    cfg.output_dir = Path(tmpdir)

    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    orc.set_callbacks(
        lambda e: None,
        lambda rj, st: print(f"  status: {rj} → {st}")
    )

    # ── 1. First prepare — should fetch from API ──
    print("── 1. 第一次 prepare_work (联网获取) ──")
    meta, targets, root_path, from_cache = await orc.prepare_work(rj_code)
    assert meta is not None, "meta 不应为 None"
    assert len(targets) > 0, "targets 不应为空"
    assert root_path.exists(), f"文件夹未创建: {root_path}"
    assert from_cache is False, "首次应为 False"

    # Verify works.status = 'prepared'
    row = db.conn.execute(
        "SELECT status FROM works WHERE rj_id=?", (rj_code,)
    ).fetchone()
    assert row is not None
    assert row["status"] == "prepared", f"works status 应为 prepared, 实际: {row['status']}"

    # Verify downloads are queued
    dls = db.get_downloads_by_rj(rj_code)
    assert len(dls) > 0, "downloads 不应为空"
    for d in dls:
        assert d["status"] in ("queued", "completed"), \
            f"download 状态应为 queued/completed: {d['id']} = {d['status']}"

    print(f"  ✓ 文件夹已创建: {root_path}")
    print(f"  ✓ works.status = prepared")
    print(f"  ✓ {len(dls)} downloads 已写入 queued")

    # ── 2. Second prepare — cache hit, no API ──
    print(f"\n── 2. 第二次 prepare_work (缓存命中) ──")
    # Monkeypatch fetch to ensure no API call
    original_fetch = kernel.fetch
    api_called = False

    async def monitored_fetch(*args, **kwargs):
        nonlocal api_called
        api_called = True
        raise AssertionError("API should not be called on cache hit!")

    kernel.fetch = monitored_fetch

    meta2, targets2, root_path2, from_cache2 = await orc.prepare_work(rj_code)
    kernel.fetch = original_fetch

    assert meta2 is not None
    assert from_cache2 is True, f"二次应为缓存命中, 实际: {from_cache2}"
    assert not api_called, "第二次不应调用 API!"
    print(f"  ✓ 缓存命中, 未调用 API")

    # Cleanup
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj_code,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj_code,))
    db.invalidate_cache(rj_code)
    db.conn.commit()
    await kernel.shutdown()
    import shutil
    shutil.rmtree(tmpdir)

    print(f"\n{'='*60}")
    print(f"  ✓ prepare_work 测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "RJ01603020"
    sys.exit(asyncio.run(test()))
