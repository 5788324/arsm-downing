import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from core.config import ConfigManager
from core.database import CACHE_TTL_HOURS, LibraryVault
from core.orchestrator import Orchestrator


RJ_ID = "RJ00000042"
META = {
    "title": "Cached Work",
    "circle": {"name": "Circle"},
    "vas": [],
    "tags": [],
    "mainCoverUrl": "",
}
TRACKS = [{
    "type": "folder",
    "title": "Chapter",
    "children": [{
        "id": "nested-1",
        "type": "audio",
        "title": "nested.mp3",
        "size": 8,
        "mediaDownloadUrl": "https://example.invalid/nested.mp3",
    }],
}]


class OfflineKernel:
    async def fetch(self, _path):
        raise OSError("offline")


class NoopKernel:
    pass


def make_vault_with_stale_cache(tmp_path: Path) -> LibraryVault:
    vault = LibraryVault(tmp_path / "history.db")
    vault.set_metadata_cache(
        RJ_ID, META["title"], META["circle"]["name"], "", META, TRACKS)
    expired = datetime.now() - timedelta(hours=CACHE_TTL_HOURS + 1)
    vault.execute_write(
        "UPDATE metadata_cache SET fetched_at=? WHERE rj_id=?",
        (expired.isoformat(), RJ_ID),
    )
    return vault


def make_config(tmp_path: Path) -> ConfigManager:
    config = ConfigManager()
    config.output_dir = tmp_path / "downloads"
    config.dir_template = "{rj_id} {title}"
    config.sort_files = False
    return config


def test_stale_metadata_is_opt_in(tmp_path: Path) -> None:
    vault = make_vault_with_stale_cache(tmp_path)
    try:
        assert vault.get_metadata_cache(RJ_ID) is None
        cached = vault.get_metadata_cache(RJ_ID, allow_stale=True)
        assert cached is not None
        assert cached["is_stale"] is True
    finally:
        vault.close()


def test_resume_uses_stale_cache_when_network_is_unavailable(tmp_path: Path) -> None:
    vault = make_vault_with_stale_cache(tmp_path)
    orchestrator = Orchestrator(NoopKernel(), make_config(tmp_path), vault)
    try:
        result = asyncio.run(orchestrator.resume_job(RJ_ID))
        assert result["status"] == "queued"
        assert result["count"] == 1
        assert RJ_ID in orchestrator.queued_rj_ids
    finally:
        vault.close()


def test_prepare_falls_back_to_stale_cache_offline(tmp_path: Path) -> None:
    vault = make_vault_with_stale_cache(tmp_path)
    orchestrator = Orchestrator(OfflineKernel(), make_config(tmp_path), vault)
    try:
        meta, tracks, root, from_cache = asyncio.run(
            orchestrator.prepare_work(RJ_ID))
        assert meta is not None
        assert meta.title == "Cached Work"
        assert len(tracks) == 1
        assert root.is_dir()
        assert from_cache is True
    finally:
        vault.close()


def test_track_detail_recurses_nested_cached_tracks(tmp_path: Path) -> None:
    vault = make_vault_with_stale_cache(tmp_path)
    orchestrator = Orchestrator(NoopKernel(), make_config(tmp_path), vault)
    try:
        detail = orchestrator.get_track_detail_for_ui(RJ_ID)
        assert detail == [{
            "title": "nested.mp3",
            "status": "pending",
            "downloaded": 0,
            "total": 8,
            "local_path": "",
        }]
    finally:
        vault.close()
