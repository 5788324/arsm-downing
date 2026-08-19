"""P0-B end-to-end: _process_download must run through the bounded pool.

The orchestrator must never create one coroutine per file.  With a stubbed
per-file downloader we assert that peak concurrent downloads equal
``file_concurrency`` regardless of file count, and that completion/partial
status propagation still works after the pool replaces the old ``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.config import ConfigManager
from core.database import LibraryVault
from core.models import TrackItem, WorkMetadata
from core.network import NetworkKernel
from core.orchestrator import Orchestrator


def meta() -> WorkMetadata:
    return WorkMetadata(
        rj_id="RJ00000009", title="Pool Test", circle="Test", cv=[], tags=[],
        price=0, dl_count=0, source_url="", rating=0.0,
        release_date="", cover_url="",
    )


async def _work_runner(tmp_path: Path, worker_count: int):
    config = ConfigManager()
    config.file_concurrency = worker_count
    config.tag_audio = False
    db = LibraryVault(tmp_path / "history.db")
    kernel = NetworkKernel(config)
    orch = Orchestrator(kernel, config, db)
    return config, db, kernel, orch


async def _run(tmp_path: Path, worker_count: int, file_count: int,
               fail_ids: set | None = None):
    """Drive _process_download with a stub that records real concurrency."""
    fail_ids = fail_ids or set()
    config, db, kernel, orch = await _work_runner(tmp_path, worker_count)
    statuses = []
    orch.on_work_status = lambda rj, st: statuses.append(st)

    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_download(track, meta_, cover, sem, refresher=None):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.002)
        async with lock:
            active -= 1
        if track.id in fail_ids:
            return False
        track.save_path.write_bytes(b"x")
        return True

    orch.download_file = fake_download
    targets = [
        TrackItem(id=f"f{i:03d}", title=f"f{i:03d}.bin", type="file",
                  url="http://127.0.0.1:1/", size=1,
                  save_path=tmp_path / f"f{i:03d}.bin")
        for i in range(file_count)
    ]
    try:
        await orch._process_download(meta().rj_id, meta(), targets, tmp_path)
        return peak, statuses, db, len(targets)
    finally:
        await kernel.shutdown()
        db.close()


def test_pool_bounds_concurrent_downloads_to_file_concurrency(tmp_path: Path) -> None:
    async def _case():
        return await _run(tmp_path, 3, 30)

    peak, statuses, _db, total = asyncio.run(_case())
    assert peak == 3
    assert "Completed" in statuses
    assert len(statuses) >= 1


def test_pool_with_many_files_stays_bounded(tmp_path: Path) -> None:
    async def _case():
        return await _run(tmp_path, 5, 100)

    peak, statuses, _db, total = asyncio.run(_case())
    assert peak == 5
    assert "Completed" in statuses


def test_pool_reports_partial_completion_on_failures(tmp_path: Path) -> None:
    fail_ids = {f"f{i:03d}" for i in range(0, 20, 2)}
    async def _case():
        return await _run(tmp_path, 4, 20, fail_ids)

    peak, statuses, _db, total = asyncio.run(_case())
    assert peak == 4
    assert any(st.startswith("Partially completed (10/20)") for st in statuses)