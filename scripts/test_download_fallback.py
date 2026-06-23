#!/usr/bin/env python3
"""下载 fallback 测试 — mock 验证直连失败→代理成功。

mock kernel.stream 第 1 次抛错，session.get 第 1 次成功。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  下载 fallback mock 测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    import aiohttp

    cfg = ConfigManager()
    cfg.download_fallback_to_proxy = True
    cfg.metadata_proxy = "http://127.0.0.1:7890"
    fallback_proxy = "http://127.0.0.1:7890"

    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # ── Mock tracking ──
    stream_calls = 0
    session_get_calls = 0
    session_get_proxy = None

    class MockResponse:
        status = 200
        content = None
        closed = False

        def close(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    # Mock kernel.stream: first call raises, second call (if any) returns response
    original_stream = kernel.stream

    async def mock_stream(url, headers, purpose='download'):
        nonlocal stream_calls
        stream_calls += 1
        if stream_calls == 1:
            raise aiohttp.ClientConnectionError("Simulated direct failure")
        return MockResponse()

    kernel.stream = mock_stream

    # Mock kernel.session.get: records proxy arg
    class MockSession:
        async def get(self, url, headers=None, proxy=None, **kwargs):
            nonlocal session_get_calls, session_get_proxy
            session_get_calls += 1
            session_get_proxy = proxy
            return MockResponse()

    kernel.session = MockSession()
    async def mock_boot():
        pass
    kernel.boot = mock_boot

    # ── Run ──
    print("── 调用 _stream_with_fallback ──")
    success, result = await orc._stream_with_fallback(
        "http://example.com/test.mp3", {})
    print(f"  success: {success}")
    print(f"  stream_calls: {stream_calls}")
    print(f"  session_get_calls: {session_get_calls}")
    print(f"  session_get_proxy: {session_get_proxy}")

    # ── Verify ──
    assert success is True, f"应返回 True, 实际 {success}"
    assert stream_calls == 1, \
        f"stream 应只调用 1 次(直连失败), 实际 {stream_calls}"
    assert session_get_calls == 1, \
        f"session.get 应调用 1 次(fallback), 实际 {session_get_calls}"
    assert session_get_proxy == fallback_proxy, \
        f"session.get proxy 应为 {fallback_proxy}, 实际 {session_get_proxy}"

    print(f"\n  ✓ stream 只调 1 次（直连失败，不重复）")
    print(f"  ✓ session.get 调 1 次（走代理）")
    print(f"  ✓ proxy 参数正确")

    # Restore
    kernel.stream = original_stream

    # ── Test: fallback disabled ──
    print(f"\n── fallback 关闭时不应回退 ──")
    cfg.download_fallback_to_proxy = False
    kernel.stream = mock_stream
    stream_calls = 0
    session_get_calls = 0

    success, msg = await orc._stream_with_fallback(
        "http://example.com/test2.mp3", {})
    print(f"  success: {success}, msg: {msg[:60]}")
    assert success is False
    assert "disabled" in str(msg).lower()
    assert session_get_calls == 0, "fallback 关闭时不应调用 session.get"
    print(f"  ✓ fallback 关闭时正确返回失败")

    # ── Test: no proxy configured ──
    print(f"\n── 无代理时不应回退 ──")
    cfg.download_fallback_to_proxy = True
    cfg.metadata_proxy = None
    cfg.download_proxy = None
    cfg.proxy = None
    stream_calls = 0
    session_get_calls = 0

    kernel.stream = mock_stream
    success, msg = await orc._stream_with_fallback(
        "http://example.com/test3.mp3", {})
    print(f"  success: {success}, msg: {msg[:60]}")
    assert success is False
    assert session_get_calls == 0, "无代理时不应调用 session.get"
    print(f"  ✓ 无代理时正确返回失败")

    kernel.stream = original_stream
    try:
        await kernel.shutdown()
    except Exception:
        pass  # MockSession may not support shutdown

    print(f"\n{'='*60}")
    print(f"  ✓ 下载 fallback mock 测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
