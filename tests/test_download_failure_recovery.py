from __future__ import annotations

import asyncio
import io
import wave

from PIL import Image

from core.config import ConfigManager
from core.database import LibraryVault
from core.local_file_validation import validate_completed_local_file
from core.models import TrackItem, WorkMetadata
from core.network import NetworkKernel
from core.orchestrator import Orchestrator


def _meta() -> WorkMetadata:
    return WorkMetadata(
        rj_id="RJ00000999", title="Failure recovery", circle="Test",
        cv=[], tags=[], price=0, dl_count=0, source_url="", rating=0.0,
        release_date="", cover_url="",
    )


def _orchestrator(tmp_path):
    config = ConfigManager()
    config.file_concurrency = 2
    config.tag_audio = False
    db = LibraryVault(tmp_path / "history.db")
    kernel = NetworkKernel(config)
    orchestrator = Orchestrator(kernel, config, db)
    db.register(_meta(), 0, tmp_path, status="queued")
    return orchestrator, db, kernel


def test_structurally_valid_oversized_recovery_formats(tmp_path):
    image_path = tmp_path / "cover.jpg"
    Image.new("RGB", (3, 2), "red").save(image_path, format="JPEG")
    assert validate_completed_local_file(image_path) == (True, "valid_image")

    text_path = tmp_path / "script.txt"
    text_path.write_text("有效的文本内容", encoding="utf-8")
    assert validate_completed_local_file(text_path) == (True, "valid_text")

    wav_path = tmp_path / "track.wav"
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 80)
    assert validate_completed_local_file(wav_path) == (True, "valid_media")



def test_structurally_valid_wav_part_uses_original_suffix(tmp_path):
    wav_path = tmp_path / "track.wav"
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 80)
    part_path = wav_path.with_name(wav_path.name + ".part")
    wav_path.rename(part_path)

    assert validate_completed_local_file(part_path) == (True, "valid_media")

def test_unknown_or_corrupt_oversized_file_stays_unverified(tmp_path):
    bad = tmp_path / "track.mp3"
    bad.write_bytes(b"not an mp3")
    valid, _reason = validate_completed_local_file(bad)
    assert valid is False


def test_worker_exception_is_persisted_and_work_is_failed(tmp_path):
    async def run():
        orchestrator, db, kernel = _orchestrator(tmp_path)
        target = TrackItem(
            id="one", title="one.bin", type="file", url="https://invalid/",
            size=10, save_path=tmp_path / "one.bin",
        )

        async def fail(*_args, **_kwargs):
            raise RuntimeError("injected worker failure")

        async def no_cover(*_args, **_kwargs):
            return None

        orchestrator.download_file = fail
        orchestrator._download_cover = no_cover
        try:
            await orchestrator._process_download(
                _meta().rj_id, _meta(), [target], tmp_path)
            row = dict(db.get_downloads_by_rj(_meta().rj_id)[0])
            assert row["status"] == "failed"
            assert row["error"] == "Worker exception: injected worker failure"
            assert db.get_works_status(_meta().rj_id) == "failed"
        finally:
            await kernel.shutdown()
            db.close()

    asyncio.run(run())


def test_mixed_worker_results_persist_partial_work(tmp_path):
    async def run():
        orchestrator, db, kernel = _orchestrator(tmp_path)
        good = TrackItem(
            id="good", title="good.bin", type="file", url="https://invalid/",
            size=1, save_path=tmp_path / "good.bin",
        )
        bad = TrackItem(
            id="bad", title="bad.bin", type="file", url="https://invalid/",
            size=1, save_path=tmp_path / "bad.bin",
        )

        async def download(target, *_args, **_kwargs):
            if target.id == "bad":
                raise RuntimeError("mixed failure")
            target.save_path.write_bytes(b"x")
            return True

        async def no_cover(*_args, **_kwargs):
            return None

        orchestrator.download_file = download
        orchestrator._download_cover = no_cover
        try:
            await orchestrator._process_download(
                _meta().rj_id, _meta(), [good, bad], tmp_path)
            states = {
                row["track_title"]: row["status"]
                for row in db.get_downloads_by_rj(_meta().rj_id)
            }
            assert states == {"good.bin": "completed", "bad.bin": "failed"}
            assert db.get_works_status(_meta().rj_id) == "partial"
        finally:
            await kernel.shutdown()
            db.close()

    asyncio.run(run())


def test_success_removes_stale_queued_row_from_old_path_plan(tmp_path):
    async def run():
        orchestrator, db, kernel = _orchestrator(tmp_path)
        current = TrackItem(
            id="one", title="one.bin", type="file", url="https://invalid/",
            size=1, save_path=tmp_path / "short" / "one.bin",
        )
        stale_path = tmp_path / "old-long-path" / "one.bin"
        stale_id = orchestrator._make_dl_id(
            _meta().rj_id, current.id, stale_path, current.title)
        db.upsert_download(
            stale_id, _meta().rj_id, current.title,
            str(stale_path), "queued", 0, 1,
        )

        async def download(target, *_args, **_kwargs):
            target.save_path.parent.mkdir(parents=True, exist_ok=True)
            target.save_path.write_bytes(b"x")
            return True

        async def no_cover(*_args, **_kwargs):
            return None

        orchestrator.download_file = download
        orchestrator._download_cover = no_cover
        try:
            await orchestrator._process_download(
                _meta().rj_id, _meta(), [current], tmp_path)
            rows = [dict(row) for row in db.get_downloads_by_rj(_meta().rj_id)]
            assert len(rows) == 1
            assert rows[0]["status"] == "completed"
            assert rows[0]["local_path"] == str(current.save_path)
            assert db.get_works_status(_meta().rj_id) == "completed"
        finally:
            await kernel.shutdown()
            db.close()

    asyncio.run(run())