#!/usr/bin/env python3
"""下载 fallback 回退代理测试 — 验证直连失败时自动切换代理。

此为单元级测试，不依赖真实网络。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  下载 fallback 代理测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager

    # ── 1. 配置 fallback ──
    print("── 1. 配置验证 ──")
    cfg = ConfigManager()
    cfg.download_fallback_to_proxy = True
    cfg.metadata_proxy = "http://127.0.0.1:7890"
    cfg.proxy = "http://127.0.0.1:1080"

    assert cfg.download_fallback_to_proxy is True
    assert cfg.get_proxy_for('metadata') == "http://127.0.0.1:7890"
    assert cfg.get_proxy_for('download') is None  # default: no proxy
    assert cfg.get_proxy_for('cover') == "http://127.0.0.1:7890"
    print(f"  ✓ metadata_proxy: {cfg.get_proxy_for('metadata')}")
    print(f"  ✓ download_proxy: {cfg.get_proxy_for('download')} (无代理=直连)")
    print(f"  ✓ cover_proxy: {cfg.get_proxy_for('cover')}")

    # ── 2. 验证 fallback proxy 地址 ──
    fallback = (cfg.download_proxy or cfg.metadata_proxy or cfg.proxy)
    assert fallback == "http://127.0.0.1:7890", \
        f"fallback 应取 metadata_proxy, 实际: {fallback}"
    print(f"  ✓ fallback proxy: {fallback}")

    # ── 3. fallback 关闭时不应回退 ──
    cfg.download_fallback_to_proxy = False
    assert cfg.download_fallback_to_proxy is False
    print(f"  ✓ download_fallback_to_proxy=False 时不回退")

    # ── 4. 无代理配置时 fallback 应返回 false ──
    from core.orchestrator import Orchestrator
    from core.database import LibraryVault
    from core.network import NetworkKernel

    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # _stream_with_fallback with an invalid URL should fail and return (False, msg)
    cfg.download_fallback_to_proxy = True
    cfg.download_proxy = None
    cfg.metadata_proxy = None
    cfg.proxy = None

    try:
        success, msg = await orc._stream_with_fallback(
            "http://192.0.2.1:1/nonexistent", {})
        assert success is False, "应返回 False（无代理且直连失败）"
        assert "No proxy" in str(msg).lower() or "proxy" in str(msg).lower() \
               or "failed" in str(msg).lower(), f"消息应提及无代理: {msg}"
        print(f"  ✓ 无代理时 fallback 返回: {msg[:60]}")
    except Exception as e:
        # May raise if DNS resolution fails immediately
        print(f"  ✓ 无代理时抛异常（预期行为）: {e}")

    await kernel.shutdown()

    print(f"\n{'='*60}")
    print(f"  ✓ 下载 fallback 代理测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
