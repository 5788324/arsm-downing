from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.config import ConfigManager
from core.database import LibraryVault
from core.download_failures import (
    DownloadHttpError,
    LowSpeedError,
    classify_download_error,
    retry_delay_seconds,
)
from core.models import TrackItem, WorkMetadata
from core.network import NetworkKernel
from core.orchestrator import Orchestrator

pytestmark = pytest.mark.portable


def _meta(rj_id: str = "RJ00000001") -> WorkMetadata:
    return WorkMetadata(
        rj_id=rj_id, title="Completion state", circle="Test",
        cv=[], tags=[], price=0, dl_count=0, source_url="",
        rating=0.0, release_date="", cover_url="",
    )


def test_completed_library_filter_requires_postprocess_and_terminal_files(tmp_path):
    db = LibraryVault(tmp_path / "history.db")
    root = tmp_path / "RJ00000001"
    root.mkdir()
    db.conn.execute(
        "INSERT INTO library_items(rj_id, folder_path, folder_name, total_files, audio_count) "
        "VALUES (?, ?, ?, 1, 1)",
        ("RJ00000001", str(root), root.name),
    )
    db.conn.commit()
    db.register(_meta(), 10, root, status="completed", postprocess_status="pending")
    db.upsert_download("d1", "RJ00000001", "a.mp3", str(root / "a.mp3"),
                       "completed", 10, 10)

    pending = db.get_library_page(category="completed")
    assert pending["total"] == 0

    db.set_postprocess_status("RJ00000001", "completed")
    complete = db.get_library_page(category="completed")
    assert complete["total"] == 1

    db.upsert_download("d1", "RJ00000001", "a.mp3", str(root / "a.mp3"),
                       "paused", 5, 10)
    incomplete = db.get_library_page(category="completed")
    assert incomplete["total"] == 0
    db.close()


def test_pending_postprocess_is_restored_without_download(tmp_path):
    config = ConfigManager()
    config.output_dir = tmp_path
    config.tag_audio = False
    db = LibraryVault(tmp_path / "history.db")
    root = tmp_path / "RJ00000001"
    root.mkdir()
    metadata = {
        "title": "Completion state", "circle": {"name": "Test"},
        "vas": [], "tags": [], "price": 0, "dl_count": 0,
        "rate_average_2dp": 0, "release_date": "", "mainCoverUrl": "",
    }
    db.set_metadata_cache("RJ00000001", "Completion state", "Test", "",
                          metadata, [])
    db.register(_meta(), 0, root, status="completed", postprocess_status="pending")
    orc = Orchestrator(NetworkKernel(config), config, db)
    called = []

    async def finalize(meta, path, cover_path=None, target_paths=None):
        called.append((meta.rj_id, path))
        db.set_postprocess_status(meta.rj_id, "completed")
        return True

    orc._run_postprocess = finalize
    result = asyncio.run(orc.restore_pending_postprocessing())

    assert result == {"found": 1, "completed": 1, "failed": 0}
    assert called == [("RJ00000001", root)]
    assert dict(db.search("RJ00000001")[0])["postprocess_status"] == "completed"
    db.close()


def test_failure_classification_and_retry_after():
    limited = classify_download_error(DownloadHttpError(429, "busy", "7"))
    assert limited.code == "http_429"
    assert limited.retryable is True
    assert limited.retry_after_seconds == 7
    assert retry_delay_seconds(attempt=3, backoff_base=2, retry_after=7) == 7

    denied = classify_download_error(DownloadHttpError(403, "denied"))
    assert denied.retryable is False
    assert classify_download_error(LowSpeedError("slow")).code == "low_speed"


def test_resume_all_preparation_is_bounded_and_parallel():
    orc = Orchestrator.__new__(Orchestrator)
    orc.global_paused = True
    orc.pause_generation = 1
    orc.config = type("Cfg", (), {"metadata_concurrency": 3})()
    orc.resume_all = lambda: [f"RJ{i:08d}" for i in range(6)]
    orc._log_concurrency_state = lambda _label: None
    active = 0
    peak = 0

    async def resume_one(_rj_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"status": "queued"}

    orc._resume_one = resume_one
    stats = asyncio.run(orc._resume_all_async())
    assert stats["resumed_to_queue"] == 6
    assert peak == 3


def test_mirror_failure_temporarily_demotes_host():
    config = ConfigManager()
    config.mirror = "https://primary.invalid"
    kernel = NetworkKernel(config)
    assert kernel._ordered_mirrors()[0] == "https://primary.invalid"
    kernel._record_mirror_failure("https://primary.invalid")
    assert kernel._ordered_mirrors()[0] != "https://primary.invalid"
    report = {item["mirror"]: item for item in kernel.get_mirror_health()}
    assert report["https://primary.invalid"]["failures"] == 1
    assert report["https://primary.invalid"]["cooldown_seconds"] > 0


def test_file_level_retry_preserves_failed_sibling(tmp_path):
    async def run():
        config = ConfigManager()
        config.output_dir = tmp_path
        config.tag_audio = False
        db = LibraryVault(tmp_path / "history.db")
        orc = Orchestrator(NetworkKernel(config), config, db)
        meta = _meta()
        root = tmp_path / meta.rj_id
        root.mkdir()
        selected = TrackItem(
            id="one", title="one.bin", type="file", url="https://invalid/one",
            size=1, save_path=root / "one.bin",
        )
        sibling = TrackItem(
            id="two", title="two.bin", type="file", url="https://invalid/two",
            size=1, save_path=root / "two.bin",
        )
        selected_id = orc._make_dl_id(meta.rj_id, selected.id, selected.save_path,
                                      selected.title)
        sibling_id = orc._make_dl_id(meta.rj_id, sibling.id, sibling.save_path,
                                     sibling.title)
        db.register(meta, 0, root, status="partial")
        db.upsert_download(selected_id, meta.rj_id, selected.title,
                           str(selected.save_path), "failed", 0, 1)
        db.upsert_download(sibling_id, meta.rj_id, sibling.title,
                           str(sibling.save_path), "failed", 0, 1)

        async def download(target, *_args, **_kwargs):
            target.save_path.write_bytes(b"x")
            return True

        async def no_cover(*_args, **_kwargs):
            return None

        orc.download_file = download
        orc._download_cover = no_cover
        await orc._process_download(
            meta.rj_id, meta, [selected], root, authoritative_plan=False)

        rows = {row["id"]: dict(row) for row in db.get_downloads_by_rj(meta.rj_id)}
        assert set(rows) == {selected_id, sibling_id}
        assert rows[selected_id]["status"] == "completed"
        assert rows[sibling_id]["status"] == "failed"
        assert db.get_works_status(meta.rj_id) == "partial"
        db.close()

    asyncio.run(run())