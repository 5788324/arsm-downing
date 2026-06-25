#!/usr/bin/env python3
"""pause_all cancel active task — 验证 active task 被取消."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  pause_all waits active cancel\n{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    from core.models import WorkMetadata, TrackItem

    cfg=ConfigManager.load(); db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)

    rj = "RJ99983"
    meta = WorkMetadata(rj_id=rj, title="T", circle="", cv=[], tags=[], price=0, source_url="", dl_count=0, rating=0.0, release_date="", cover_url="")
    target = TrackItem(id="1", title="t1", type="audio", url="http://localhost/t1.mp3", size=100, save_path=Path(f"/tmp/{rj}/t1.mp3"))

    # Create a slow fake task
    async def slow_task():
        await asyncio.sleep(10)
    task = asyncio.create_task(slow_task())
    orc.active_tasks[rj] = task

    # pause_all should cancel it
    orc.pause_all()
    await asyncio.sleep(0.1)  # allow cancellation to propagate
    assert task.cancelled() or task.done(), "task should be cancelled"
    print(f"  ✓ active task cancelled by pause_all")

    orc.active_tasks.pop(rj, None)
    await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
