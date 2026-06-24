#!/usr/bin/env python3
"""resume_all 统计字段完整性 + queued 状态不变为 downloading 测试."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  resume_all stats 字段完整性测试\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    from core.status import WorkStatus

    cfg = ConfigManager.load()
    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # ── 1. Verify _resume_all_async returns dict with all fields ──
    print("── 1. stats dict 所有字段 ──")
    rj_ids = orc.resume_all()
    # With no real data, stats should still have all keys
    stats = await orc._resume_all_async()
    required = ["resumed_to_queue", "already_queued", "already_running",
                "no_pending", "no_cache", "cache_corrupt", "failed"]
    for key in required:
        assert key in stats, f"Missing stat key: {key}"
        print(f"  ✓ stats['{key}'] = {stats[key]}")

    # ── 2. queued state never maps to downloading ──
    print(f"\n── 2. queued ≠ downloading (normalize) ──")
    ws_q = WorkStatus.normalize("Queued")
    ws_dl = WorkStatus.normalize("Downloading")
    assert ws_q == WorkStatus.QUEUED
    assert ws_dl == WorkStatus.DOWNLOADING
    assert ws_q != ws_dl
    print(f"  ✓ Queued → queued, Downloading → downloading (不同)")

    # ── 3. _resume_one does not emit Downloading ──
    print(f"\n── 3. _resume_one 源码检查 ──")
    import inspect
    src = inspect.getsource(Orchestrator._resume_one)
    emit_calls = [l.strip() for l in src.split('\n') if '_emit_work_status' in l]
    has_dl_emit = any('Downloading' in l for l in emit_calls)
    assert not has_dl_emit, \
        f"_resume_one 不应 emit Downloading: {emit_calls}"
    print(f"  ✓ _resume_one 不 emit Downloading")

    # ── 4. resume_job emits Queued not Downloading ──
    print(f"\n── 4. resume_job emit 检查 ──")
    src_rj = inspect.getsource(Orchestrator.resume_job)
    emit_lines = [l.strip() for l in src_rj.split('\n') if '_emit_work_status' in l]
    print(f"  resume_job emits: {emit_lines}")
    assert any('Queued' in l for l in emit_lines), \
        f"resume_job 应 emit Queued, emits: {emit_lines}"
    assert not any('Downloading' in l for l in emit_lines), \
        f"resume_job 不应 emit Downloading, emits: {emit_lines}"
    print(f"  ✓ resume_job emit Queued (not Downloading)")

    await kernel.shutdown()

    print(f"\n{'='*60}\n  ✓ resume_all stats 字段完整性测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
