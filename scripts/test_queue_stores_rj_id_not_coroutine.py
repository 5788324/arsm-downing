#!/usr/bin/env python3
"""download_queue 存 rj_id 不存 coroutine — 源码验证."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  queue 存 rj_id 不存 coroutine\n{'='*60}\n")
    from core.orchestrator import Orchestrator
    import inspect
    src = inspect.getsource(Orchestrator)
    # queue_job: put(rj_id)
    src_qj = inspect.getsource(Orchestrator.queue_job)
    assert "put(rj_id)" in src_qj, "queue_job should put(rj_id)"
    assert "_queued_work_data" in src_qj, "queue_job should store _queued_work_data"
    assert "_process_download" not in src_qj.split("put(")[1][:50] if "put(" in src_qj else True, \
        "put() should NOT contain _process_download"
    print(f"  ✓ queue_job: put(rj_id) + _queued_work_data")
    # resume_job: put(rj_id)
    src_rj = inspect.getsource(Orchestrator.resume_job)
    assert "put(rj_id)" in src_rj, "resume_job should put(rj_id)"
    assert "_queued_work_data" in src_rj, "resume_job should store _queued_work_data"
    print(f"  ✓ resume_job: put(rj_id) + _queued_work_data")
    # boot_worker: get() returns str, not tuple
    src_bw = inspect.getsource(Orchestrator.boot_worker)
    assert "job_coro" not in src_bw, "boot_worker should NOT have job_coro"
    assert "_queued_work_data" in src_bw, "boot_worker should use _queued_work_data"
    print(f"  ✓ boot_worker: get() → rj_id (str), no coroutine")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
