"""P0-B: the download worker pool must bound live coroutines.

Issue #20: one coroutine per file (hundreds) waiting on a semaphore starved the
event loop and made pause/cancel unmanageable.  These tests pin the pool
contract: fixed workers, bounded peak concurrency, stable per-key results, and
clean termination on cancel.
"""

from __future__ import annotations

import asyncio

import pytest

from core.download_workers import DownloadWorkerPool


def _track(index: int):
    return {"key": f"f{index:04d}", "index": index}


def test_pool_bounds_concurrency_to_worker_count() -> None:
    async def _case():
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def process(job):
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.005)
            async with lock:
                active -= 1
            return {"ok": True, "key": job["key"]}

        jobs = [_track(i) for i in range(686)]
        pool = DownloadWorkerPool(worker_count=5, process=process,
                                  key_of=lambda job: job["key"])
        results = await pool.run(jobs)
        return pool, results

    pool, results = asyncio.run(_case())
    assert pool.peak_active == 5
    assert pool.active_count == 0
    assert len(results) == 686
    assert all(results[f"f{i:04d}"]["ok"] for i in range(686))


def test_pool_single_worker_is_truly_serial() -> None:
    async def _case():
        active = 0
        peak = 0

        async def process(_job):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.001)
            active -= 1
            return True

        pool = DownloadWorkerPool(worker_count=1, process=process,
                                  key_of=lambda job: job["key"])
        await pool.run([_track(i) for i in range(20)])
        return peak

    assert asyncio.run(_case()) == 1


def test_pool_records_worker_exceptions_per_key() -> None:
    async def _case():
        async def process(job):
            if job["index"] % 2 == 0:
                raise RuntimeError("boom")
            return {"ok": True}

        pool = DownloadWorkerPool(worker_count=3, process=process,
                                  key_of=lambda job: job["key"])
        return await pool.run([_track(i) for i in range(10)])

    results = asyncio.run(_case())
    for i in range(10):
        if i % 2 == 0:
            assert results[f"f{i:04d}"]["error"] == "boom"
        else:
            assert results[f"f{i:04d}"]["ok"] is True


def test_pool_cancel_terminates_cleanly() -> None:
    async def _case():
        started = asyncio.Event()
        release = asyncio.Event()

        async def process(_job):
            started.set()
            await release.wait()
            return True

        pool = DownloadWorkerPool(worker_count=4, process=process,
                                  key_of=lambda job: job["key"])
        runner = asyncio.create_task(pool.run([_track(i) for i in range(50)]))
        await asyncio.wait_for(started.wait(), timeout=5)
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
        return pool

    pool = asyncio.run(_case())
    # Workers must be gone — cancellation must not stall or leak tasks.
    assert pool.active_count == 0
    assert all(task.done() for task in pool._workers) or not pool._workers


def test_pool_finishes_without_leaked_worker_tasks() -> None:
    async def _case():
        async def process(job):
            await asyncio.sleep(0.001)
            return True

        pool = DownloadWorkerPool(worker_count=4, process=process,
                                  key_of=lambda job: job["key"])
        await pool.run([_track(i) for i in range(40)])
        return pool

    pool = asyncio.run(_case())
    assert pool._workers == []


def test_pool_large_file_count_is_bounded_and_complete() -> None:
    """686 files with file_concurrency=8: peak active must equal 8."""
    async def _case():
        active = 0
        peak = 0

        async def process(job):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.002)
            active -= 1
            return job["key"]

        jobs = [_track(i) for i in range(686)]
        pool = DownloadWorkerPool(worker_count=8, process=process,
                                  key_of=lambda job: job["key"])
        results = await pool.run(jobs)
        return pool, results

    pool, results = asyncio.run(_case())
    assert pool.peak_active == 8
    assert len(results) == 686