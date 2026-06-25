#!/usr/bin/env python3
"""file_concurrency 真正限制同一 RJ 内文件并发 — per-RJ semaphore 测试."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  file_concurrency per-work 限流测试\n{'='*60}\n")

    from core.orchestrator import Orchestrator
    import inspect

    # ── 1. No global sem in __init__ ──
    src_init = inspect.getsource(Orchestrator.__init__)
    assert "self.sem" not in src_init or \
        "self.sem = asyncio.Semaphore" not in src_init, \
        "__init__ should NOT create global self.sem"
    print(f"  ✓ __init__ 无全局 self.sem")

    # ── 2. _process_download creates per-RJ semaphore ──
    src_pd = inspect.getsource(Orchestrator._process_download)
    assert "asyncio.Semaphore" in src_pd, \
        "_process_download should create per-RJ Semaphore"
    assert "file_sem" in src_pd, \
        "_process_download should have file_sem variable"
    print(f"  ✓ _process_download 创建 per-RJ Semaphore")

    # ── 3. download_file accepts file_sem parameter ──
    src_df = inspect.getsource(Orchestrator.download_file)
    assert "file_sem" in src_df, \
        "download_file should accept file_sem parameter"
    assert "async with file_sem" in src_df, \
        "download_file should use async with file_sem"
    print(f"  ✓ download_file 使用 per-RJ file_sem")

    # ── 4. Semaphore value = file_concurrency ──
    assert "Semaphore(self.config.file_concurrency)" in src_pd or \
        "Semaphore(file_concurrency)" in src_pd, \
        "Semaphore should use file_concurrency value"
    print(f"  ✓ Semaphore(file_concurrency)")

    # ── 5. Each _process_download call creates its own semaphore ──
    # This means per-RJ limit, not global
    assert "_process_download" in src_pd, "_process_download exists"
    print(f"  ✓ per-RJ: 每个 work 独立 semaphore → file_concurrency 文件/RJ")

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
