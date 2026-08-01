from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class _MetadataJob:
    label: str
    factory: Callable[[], Awaitable[Any]]
    future: asyncio.Future


class MetadataScheduler:
    """Bounded FIFO scheduler for metadata work, separate from audio workers."""

    def __init__(self, concurrency: int = 2) -> None:
        self.concurrency = max(1, min(int(concurrency), 8))
        self._queue: asyncio.Queue[_MetadataJob] | None = None
        self._workers: list[asyncio.Task] = []
        self._started = False
        self._closing = False
        self._active = 0
        self.peak_active = 0

    @property
    def queued_count(self) -> int:
        return self._queue.qsize() if self._queue is not None else 0

    @property
    def active_count(self) -> int:
        return self._active

    async def start(self) -> None:
        if self._started:
            return
        if self._closing:
            raise RuntimeError("metadata scheduler is closing")
        self._queue = asyncio.Queue()
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"arsm-metadata-{index + 1}")
            for index in range(self.concurrency)
        ]
        self._started = True

    async def submit(
        self,
        label: str,
        factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        if self._closing:
            raise RuntimeError("metadata scheduler is closing")
        await self.start()
        assert self._queue is not None
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put(_MetadataJob(label=label, factory=factory, future=future))
        return await future

    async def _worker(self, _index: int) -> None:
        assert self._queue is not None
        while True:
            job = await self._queue.get()
            try:
                if job.future.cancelled():
                    continue
                self._active += 1
                self.peak_active = max(self.peak_active, self._active)
                try:
                    result = await job.factory()
                except asyncio.CancelledError:
                    if not job.future.done():
                        job.future.cancel()
                    raise
                except Exception as exc:
                    if not job.future.done():
                        job.future.set_exception(exc)
                else:
                    if not job.future.done():
                        job.future.set_result(result)
                finally:
                    self._active = max(0, self._active - 1)
            finally:
                self._queue.task_done()

    async def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        if not self._started:
            return
        assert self._queue is not None

        while True:
            try:
                job = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                try:
                    if job is not None and not job.future.done():
                        job.future.cancel()
                finally:
                    self._queue.task_done()

        for worker in self._workers:
            if not worker.done():
                worker.cancel()
        for worker in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._workers.clear()
        self._started = False
