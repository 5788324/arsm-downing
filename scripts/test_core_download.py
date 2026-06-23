#!/usr/bin/env python3
"""最小下载核心测试 — 不依赖 Flet GUI。

用法:
    python scripts/test_core_download.py RJ01603020
    python scripts/test_core_download.py 01603020  (自动补前缀)

验证:
    1. 获取作品 metadata
    2. 获取 tracks
    3. 打印文件树和保存路径
"""

import asyncio
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel
from core.orchestrator import Orchestrator
from core.models import WorkMetadata


async def test_download(rj_input: str):
    """测试下���核心: fetch metadata + tracks + print tree."""

    # 规范化 RJ 号
    if not rj_input.upper().startswith("RJ"):
        rj_code = f"RJ{rj_input}"
    else:
        rj_code = rj_input.upper()
    rj_numeric = rj_code[2:]

    print(f"\n{'='*60}")
    print(f"  测试 RJ 码: {rj_code} (数字: {rj_numeric})")
    print(f"{'='*60}")

    config = ConfigManager.load()
    print(f"  Mirror: {config.mirror}")
    print(f"  Output: {config.output_dir}")

    db = LibraryVault()
    kernel = NetworkKernel(config)
    orc = Orchestrator(kernel, config, db)

    try:
        # ── 1. 获取 metadata ──
        print(f"\n── 1. 获取元数据 ──")
        meta_raw = await kernel.fetch(f"/api/workInfo/{rj_numeric}")
        if not meta_raw:
            print(f"  ✗ 无法获取元数据 (请检查网络/代理/mirror)")
            return 1

        print(f"  标题: {meta_raw.get('title', 'N/A')}")
        print(f"  社团: {meta_raw.get('circle', {}).get('name', 'N/A')}")
        print(f"  价格: {meta_raw.get('price', 0)} JPY")
        vas = meta_raw.get('vas', [])
        if vas:
            print(f"  声优: {', '.join(v.get('name','') for v in vas[:5])}")

        # ── 2. 获取 tracks ──
        print(f"\n── 2. 获取文件列表 ──")
        tracks_raw = await kernel.fetch(f"/api/tracks/{rj_numeric}?v=2")
        if not tracks_raw:
            print(f"  ✗ 无法获取文件列表")
            return 1

        print(f"  顶层条目: {len(tracks_raw)}")

        # ── 3. 构建文件树并打印 ──
        meta = WorkMetadata(
            rj_id=rj_code,
            title=meta_raw.get('title', 'Unknown'),
            circle=meta_raw.get('circle', {}).get('name', 'Unknown'),
            cv=[v.get('name', '') for v in meta_raw.get('vas', [])],
            tags=[t.get('name', '') for t in meta_raw.get('tags', [])],
            price=meta_raw.get('price', 0),
            source_url=meta_raw.get('source_url', ''),
            dl_count=meta_raw.get('dl_count', 0),
            rating=meta_raw.get('rate_average_2dp', 0.0),
            release_date=meta_raw.get('release_date', ''),
            cover_url=meta_raw.get('mainCoverUrl', '')
        )

        root_path = orc.get_save_path(meta)
        print(f"\n── 3. 文件树 ──")
        print(f"  保存路径: {root_path}")

        hierarchy = orc.parse_hierarchy(tracks_raw, root_path, root_path)

        def flatten_all(items):
            result = []
            for item in items:
                if item.type != 'folder':
                    result.append(item)
                result.extend(flatten_all(item.children))
            return result

        def print_tree(items, indent=0):
            for item in items:
                prefix = "  " * indent
                if item.type == 'folder':
                    print(f"  {prefix}📁 {item.title}/")
                    print_tree(item.children, indent + 1)
                else:
                    size_mb = item.size / 1024 / 1024 if item.size else 0
                    print(f"  {prefix}  📄 {item.title}  ({size_mb:.1f} MB)")

        print_tree(hierarchy)

        # ── 4. 统计 ──
        all_files = flatten_all(hierarchy)
        total_size = sum(f.size for f in all_files)
        print(f"\n── 4. 统计 ──")
        print(f"  文件总数: {len(all_files)}")
        print(f"  总大小: {total_size / 1024 / 1024:.1f} MB")
        if all_files:
            print(f"  最大文件: {max(all_files, key=lambda x: x.size).title}")

        # ── 5. 去重检查 ──
        deduped = Orchestrator.deduplicate_tracks(all_files)
        if len(deduped) != len(all_files):
            print(f"  ⚠ 去重后文件数: {len(deduped)} (有同名冲突)")

        print(f"\n{'='*60}")
        print(f"  ✓ 核心测试通过 — 元数据和文件列表获取成功")
        print(f"{'='*60}\n")
        return 0

    finally:
        await kernel.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/test_core_download.py RJ01603020")
        print("      python scripts/test_core_download.py 01603020")
        sys.exit(1)

    code = sys.argv[1]
    exit_code = asyncio.run(test_download(code))
    sys.exit(exit_code)
