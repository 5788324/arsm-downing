from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest import mock

from core import config as config_module
from core.config import ConfigManager
from core.orchestrator import Orchestrator


class _MetadataKernel:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    async def fetch(self, path: str):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.01)
            if path.startswith("/api/workInfo/"):
                return {
                    "title": path.rsplit("/", 1)[-1],
                    "circle": {"name": "Circle"},
                    "mainCoverUrl": "",
                }
            return [{"id": "1", "title": "a.mp3", "mediaDownloadUrl": "https://example.invalid/a"}]
        finally:
            self.active -= 1

    async def shutdown(self):
        return None


class _Db:
    def __init__(self) -> None:
        self.cached = []

    def set_metadata_cache(self, **kwargs):
        self.cached.append(kwargs["rj_id"])


async def _run_metadata_batch(limit: int):
    config = ConfigManager()
    config.work_concurrency = 1
    config.metadata_concurrency = limit
    kernel = _MetadataKernel()
    db = _Db()
    orchestrator = Orchestrator(kernel, config, db)
    await asyncio.gather(*[
        orchestrator._fetch_metadata_live(f"RJ0000000{index}", str(index))
        for index in range(1, 7)
    ])
    return kernel, db


def test_metadata_requests_use_independent_bounded_pool() -> None:
    kernel, db = asyncio.run(_run_metadata_batch(2))
    assert kernel.peak == 2
    assert len(db.cached) == 6


def test_metadata_concurrency_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    missing_example = tmp_path / "missing-example.json"
    with mock.patch.object(config_module, "CONFIG_FILE", config_path), mock.patch.object(
        config_module,
        "CONFIG_EXAMPLE_FILE",
        missing_example,
    ):
        config = ConfigManager()
        config.metadata_concurrency = 6
        config.save()
        loaded = ConfigManager.load()

    assert loaded.metadata_concurrency == 6
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["metadata_concurrency"] == 6
