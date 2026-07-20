from __future__ import annotations

import asyncio

import pytest

from ui.app import AppController

pytestmark = pytest.mark.portable


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls = 0

    async def shutdown(self) -> None:
        self.calls += 1


class FakeDb:
    def __init__(self) -> None:
        self.calls = 0

    def close(self) -> None:
        self.calls += 1


def test_shutdown_backend_closes_orchestrator_then_database() -> None:
    controller = AppController.__new__(AppController)
    controller.orc = FakeOrchestrator()
    controller.db = FakeDb()

    asyncio.run(controller._shutdown_backend())

    assert controller.orc.calls == 1
    assert controller.db.calls == 1
