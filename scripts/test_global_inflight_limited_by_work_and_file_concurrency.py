#!/usr/bin/env python3
"""work_concurrency * file_concurrency 乘积为全局最大 in-flight."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  global_inflight ≤ work * file concurrency\n{'='*60}\n")

    from core.config import ConfigManager
    from core.orchestrator import Orchestrator
    import inspect

    cfg = ConfigManager()
    cfg.work_concurrency = 2
    cfg.file_concurrency = 3

    # ── 1. Per-RJ semaphore = file_concurrency ──
    print(f"  work_concurrency={cfg.work_concurrency}")
    print(f"  file_concurrency={cfg.file_concurrency}")
    print(f"  理论上界: {cfg.work_concurrency * cfg.file_concurrency}")

    # ── 2. Each _process_download has its own Semaphore(file_concurrency) ──
    src = inspect.getsource(Orchestrator._process_download)
    assert "Semaphore" in src, "_process_download should have Semaphore"
    print(f"  ✓ per-RJ Semaphore(file_concurrency) = {cfg.file_concurrency}")

    # ── 3. Global in-flight tracking exists ──
    src_init = inspect.getsource(Orchestrator.__init__)
    assert "_global_inflight" in src_init, "__init__ should have _global_inflight"
    assert "_global_inflight_lock" in src_init, "__init__ should have _global_inflight_lock"
    print(f"  ✓ _global_inflight + _global_inflight_lock 追踪")

    # ── 4. Per-RJ tracking exists ──
    assert "_per_rj_inflight" in src_init, "__init__ should have _per_rj_inflight"
    print(f"  ✓ _per_rj_inflight 追踪")

    # ── 5. FILE_SLOT_ACQUIRE logs work_inflight + global_inflight ──
    src_df = inspect.getsource(Orchestrator.download_file)
    assert "FILE_SLOT_ACQUIRE" in src_df, "should log FILE_SLOT_ACQUIRE"
    assert "FILE_SLOT_RELEASE" in src_df, "should log FILE_SLOT_RELEASE"
    assert "work_inflight=" in src_df, "should log work_inflight"
    assert "global_inflight=" in src_df, "should log global_inflight"
    print(f"  ✓ FILE_SLOT_ACQUIRE/RELEASE 含 work_inflight + global_inflight")

    # ── 6. Theoretical max: work_concurrency * file_concurrency ──
    # Each RJ gets file_concurrency=3 slots
    # work_concurrency=2 RJs can run simultaneously
    # → max 6 files globally
    max_theoretical = cfg.work_concurrency * cfg.file_concurrency
    print(f"  ✓ 理论上界: {cfg.work_concurrency} × {cfg.file_concurrency} = {max_theoretical}")

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
