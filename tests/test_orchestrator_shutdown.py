from __future__ import annotations

import asyncio

import pytest

from core.orchestrator import Orchestrator

pytestmark = pytest.mark.portable


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class FakeKernel:
    def __init__(self) -> None:
        self.shutdowns = 0

    async def shutdown(self) -> None:
        self.shutdowns += 1


class FakeConfig:
    work_concurrency = 1
    file_concurrency = 1
    metadata_proxy = None
    download_proxy = None
    download_fallback_to_proxy = False

    def get_proxy_for(self, _purpose):
        return None


async def _never() -> None:
    await asyncio.Event().wait()


def test_shutdown_cancels_active_and_worker_tasks_and_is_idempotent() -> None:
    async def scenario() -> None:
        db = FakeDb()
        kernel = FakeKernel()
        orc = Orchestrator(kernel, FakeConfig(), db)
        orc.pause_all = lambda: []
        active = asyncio.create_task(_never())
        worker = asyncio.create_task(_never())
        orc.active_tasks["RJ1"] = active
        orc.worker_tasks = [worker]

        await orc.shutdown()
        await orc.shutdown()

        assert active.cancelled()
        assert worker.cancelled()
        assert db.commits == 1
        assert kernel.shutdowns == 1
        assert orc.worker_tasks == []

    asyncio.run(scenario())
