"""Bounded file worker pool for one download work.

P0-B: ``_process_download`` used to build one coroutine per file and hand them
all to ``asyncio.gather``.  A 686-file work therefore created 686 coroutines
(each waiting on a file semaphore) and coupled pause/cancel to an unmanageable
fan-out.  ``DownloadWorkerPool`` instead runs a fixed number of workers that
pull files from a bounded queue, so the number of live download coroutines is
always ``worker_count`` regardless of file count.

Results are keyed by a stable file key (never by ``gather`` index), which the
caller supplies via ``key_of``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List


class DownloadWorkerPool:
    """A fixed-size pool of workers consuming files from an internal queue."""

    def __init__(self, worker_count: int,
                 process: Callable[[Any], Awaitable[Any]],
                 key_of: Callable[[Any], str]) -> None:
        self.worker_count = max(1, int(worker_count))
        self._process = process
        self._key_of = key_of
        self._queue: asyncio.Queue = asyncio.Queue()
        self._results: Dict[str, Any] = {}
        self._workers: List[asyncio.Task] = []
        self._active = 0
        self.peak_active = 0
        self.jobs_submitted = 0

    @property
    def active_count(self) -> int:
        return self._active

    async def run(self, jobs: List[Any]) -> Dict[str, Any]:
        """Process every job and return ``{stable_key: result}``.

        On any exit (including cancellation and exceptions) all worker tasks are
        cancelled and awaited, so no worker or queue item leaks.
        """
        for job in jobs:
            await self._queue.put(job)
        self.jobs_submitted = len(jobs)
        self._workers = [
            asyncio.create_task(self._worker(index),
                                name=f"arsm-file-worker-{index + 1}")
            for index in range(self.worker_count)
        ]
        try:
            await self._queue.join()
        finally:
            for task in self._workers:
                if not task.done():
                    task.cancel()
            if self._workers:
                await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()
        return self._results

    async def _worker(self, _index: int) -> None:
        while True:
            try:
                job = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            self._active += 1
            self.peak_active = max(self.peak_active, self._active)
            try:
                try:
                    result = await self._process(job)
                except asyncio.CancelledError:
                    self._results[self._key_of(job)] = {"cancelled": True}
                    raise
                except Exception as exc:
                    self._results[self._key_of(job)] = {"error": str(exc)}
                else:
                    self._results[self._key_of(job)] = result
            finally:
                self._active = max(0, self._active - 1)
                self._queue.task_done()