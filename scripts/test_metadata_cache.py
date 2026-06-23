#!/usr/bin/env python3
"""元数据缓存测试 — 验证首次联网、二次缓存命中。

用法:
    python scripts/test_metadata_cache.py RJ01603020
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigManager
from core.database import LibraryVault


async def test(rj_input: str):
    if not rj_input.upper().startswith("RJ"):
        rj_code = f"RJ{rj_input}"
    else:
        rj_code = rj_input.upper()

    print(f"\n{'='*60}")
    print(f"  元数据缓存测试: {rj_code}")
    print(f"{'='*60}\n")

    config = ConfigManager.load()
    db = LibraryVault()

    # ── 第 1 次: 缓存应该为空 ──
    print("── 第 1 次查询 ──")
    cached1 = db.get_metadata_cache(rj_code)
    if cached1:
        print(f"  ⚠ 缓存意外命中 (可能上次测试遗留)")
        db.invalidate_cache(rj_code)
        print(f"  → 已清除旧缓存")
    else:
        print(f"  ✓ 缓存 MISS — 需要联网获取")

    # ── 模拟 Orchestrator 的逻辑: 调用 API 获取并写入缓存 ──
    from core.network import NetworkKernel
    kernel = NetworkKernel(config)
    try:
        rj_numeric = rj_code[2:]
        print(f"\n── 联网获取元数据 ──")
        t0 = time.time()
        meta_raw = await kernel.fetch(f"/api/workInfo/{rj_numeric}")
        t1 = time.time()
        if not meta_raw:
            print("  ✗ 获取元数据失败")
            return 1
        print(f"  ✓ 标题: {meta_raw.get('title','')[:50]}...")
        print(f"  ✓ 耗时: {t1-t0:.2f}s")

        t0 = time.time()
        tracks_raw = await kernel.fetch(f"/api/tracks/{rj_numeric}?v=2")
        t1 = time.time()
        if not tracks_raw:
            print("  ✗ 获取 tracks 失败")
            return 1
        print(f"  ✓ Tracks 条目: {len(tracks_raw)}")
        print(f"  ✓ 耗时: {t1-t0:.2f}s")

        # 写入缓存
        circle = meta_raw.get('circle', {}).get('name', 'Unknown')
        db.set_metadata_cache(
            rj_id=rj_code,
            title=meta_raw.get('title', ''),
            circle=circle,
            cover_url=meta_raw.get('mainCoverUrl', ''),
            metadata_raw=meta_raw,
            tracks_raw=tracks_raw,
        )
        print(f"  ✓ 已写入 metadata_cache")

        # ── 第 2 次: 缓存应该命中 ──
        print(f"\n── 第 2 次查询 ──")
        cached2 = db.get_metadata_cache(rj_code)
        if cached2 is None:
            print(f"  ✗ 缓存 MISS — 写入失败或过期")
            return 1

        import json as _json
        meta2 = _json.loads(cached2["metadata_json"])
        tracks2 = _json.loads(cached2["tracks_json"])
        title2 = meta2.get('title', '')
        print(f"  ✓ 缓存 HIT")
        print(f"  ✓ 标题: {title2[:50]}...")
        print(f"  ✓ Tracks 条目: {len(tracks2)}")
        print(f"  ✓ fetched_at: {cached2['fetched_at']}")

        # 验证数据一致性
        assert title2 == meta_raw.get('title', ''), "标题不一致!"
        assert len(tracks2) == len(tracks_raw), "Tracks 数量不一致!"

        print(f"\n{'='*60}")
        print(f"  ✓ 元数据缓存测试通过")
        print(f"{'='*60}\n")
        return 0

    finally:
        await kernel.shutdown()
        # Clean up test cache
        db.invalidate_cache(rj_code)


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "RJ01603020"
    sys.exit(asyncio.run(test(code)))
