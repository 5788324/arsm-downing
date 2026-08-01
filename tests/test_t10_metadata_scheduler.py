from __future__ import annotations

import asyncio

import pytest

from core.metadata_scheduler import MetadataScheduler

pytestmark = pytest.mark.portable


def test_metadata_scheduler_bounds_one_hundred_jobs_to_two() -> None:
    async def scenario():
        scheduler = MetadataScheduler(2)
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def work(value: int):
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.002)
            async with lock:
                active -= 1
            return value

        results = await asyncio.gather(*[
            scheduler.submit(str(index), lambda index=index: work(index))
            for index in range(100)
        ])
        await scheduler.shutdown()
        await scheduler.shutdown()
        return scheduler, peak, results

    scheduler, peak, results = asyncio.run(scenario())
    assert peak == 2
    assert scheduler.peak_active == 2
    assert results == list(range(100))


def test_scheduler_rejects_submit_after_shutdown() -> None:
    async def scenario():
        scheduler = MetadataScheduler(2)
        await scheduler.start()
        await scheduler.shutdown()
        with pytest.raises(RuntimeError, match="closing"):
            await scheduler.submit("late", lambda: asyncio.sleep(0))

    asyncio.run(scenario())


def test_orchestrator_metadata_fetches_share_scheduler_pool() -> None:
    from core.config import ConfigManager
    from core.orchestrator import Orchestrator

    class Kernel:
        def __init__(self):
            self.active = 0
            self.peak = 0

        async def fetch(self, path):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.001)
                if "/workInfo/" in path:
                    return {"title": path, "circle": {"name": "C"}, "mainCoverUrl": ""}
                return [{"id": "1", "title": "a.mp3"}]
            finally:
                self.active -= 1

        async def shutdown(self):
            return None

    class Db:
        def __init__(self):
            self.cached = []

        def set_metadata_cache(self, **kwargs):
            self.cached.append(kwargs["rj_id"])

    async def scenario():
        config = ConfigManager()
        config.metadata_concurrency = 2
        kernel = Kernel()
        db = Db()
        orchestrator = Orchestrator(kernel, config, db)
        results = await asyncio.gather(*[
            orchestrator._fetch_metadata_live(f"RJ{index:08d}", str(index))
            for index in range(100)
        ])
        await orchestrator.metadata_scheduler.shutdown()
        return kernel, db, results

    kernel, db, results = asyncio.run(scenario())
    assert kernel.peak == 2
    assert len(db.cached) == 100
    assert all(meta and tracks for meta, tracks in results)
