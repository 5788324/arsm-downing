import asyncio
from pathlib import Path

from core.config import ConfigManager
from core.database import LibraryVault
from core.models import TrackItem, WorkMetadata
from core.orchestrator import Orchestrator


class FakeContent:
    def __init__(self, chunks, pause_after_first: bool = False):
        self.chunks = list(chunks)
        self.pause_after_first = pause_after_first
        self.first_written = asyncio.Event()

    async def iter_chunked(self, _size):
        for index, chunk in enumerate(self.chunks):
            yield chunk
            if index == 0:
                self.first_written.set()
                if self.pause_after_first:
                    await asyncio.sleep(60)


class FakeResponse:
    def __init__(self, status, chunks=(), headers=None, pause_after_first=False):
        self.status = status
        self.headers = headers or {}
        self.content = FakeContent(chunks, pause_after_first=pause_after_first)
        self.closed = False

    def close(self):
        self.closed = True


class FakeKernel:
    def __init__(self, responses):
        self.responses = list(responses)

    async def stream(self, _url, _headers=None, purpose="download"):
        assert purpose == "download"
        return self.responses.pop(0)

    async def shutdown(self):
        return None


def make_orchestrator(tmp_path: Path, responses, retry_count=1):
    cfg = ConfigManager()
    cfg.output_dir = tmp_path / "downloads"
    cfg.retry_count = retry_count
    cfg.retry_backoff = 1
    cfg.chunk_size = 2
    cfg.tag_audio = False
    db = LibraryVault(tmp_path / "history.db")
    orc = Orchestrator(FakeKernel(responses), cfg, db)
    return orc, db


def make_meta() -> WorkMetadata:
    return WorkMetadata(
        rj_id="RJ00000001", title="Test", circle="Test", cv=[], tags=[],
        price=0, dl_count=0, source_url="", rating=0.0,
        release_date="", cover_url="",
    )


def make_track(path: Path, size: int) -> TrackItem:
    return TrackItem(
        id="1", title=path.name, type="audio",
        url="https://example.invalid/track", size=size, save_path=path,
    )


def test_complete_part_plus_416_is_verified_and_renamed(tmp_path: Path) -> None:
    response = FakeResponse(416)
    orc, db = make_orchestrator(tmp_path, [response])
    final = tmp_path / "track.mp3"
    final.with_suffix(".mp3.part").write_bytes(b"abcd")

    result = asyncio.run(orc.download_file(
        make_track(final, 4), make_meta(), None, asyncio.Semaphore(1)))

    assert result is True
    assert final.read_bytes() == b"abcd"
    assert not final.with_suffix(".mp3.part").exists()
    row = db.get_downloads_by_rj("RJ00000001")[0]
    assert row["status"] == "completed"
    db.close()


def test_incomplete_part_plus_416_never_marks_completed(tmp_path: Path) -> None:
    response = FakeResponse(416)
    orc, db = make_orchestrator(tmp_path, [response])
    final = tmp_path / "track.mp3"
    final.with_suffix(".mp3.part").write_bytes(b"ab")

    result = asyncio.run(orc.download_file(
        make_track(final, 4), make_meta(), None, asyncio.Semaphore(1)))

    assert result is False
    assert not final.exists()
    row = db.get_downloads_by_rj("RJ00000001")[0]
    assert row["status"] == "failed"
    db.close()


def test_partial_final_is_moved_to_part_before_range_append(tmp_path: Path) -> None:
    response = FakeResponse(
        206, chunks=[b"de", b"f"],
        headers={"Content-Range": "bytes 3-5/6", "Content-Length": "3"},
    )
    orc, db = make_orchestrator(tmp_path, [response])
    final = tmp_path / "track.mp3"
    final.write_bytes(b"abc")

    result = asyncio.run(orc.download_file(
        make_track(final, 6), make_meta(), None, asyncio.Semaphore(1)))

    assert result is True
    assert final.read_bytes() == b"abcdef"
    db.close()


def test_range_mismatch_resets_instead_of_writing_corrupt_body(tmp_path: Path) -> None:
    response = FakeResponse(
        206, chunks=[b"bad"],
        headers={"Content-Range": "bytes 1-3/6", "Content-Length": "3"},
    )
    orc, db = make_orchestrator(tmp_path, [response])
    final = tmp_path / "track.mp3"
    final.with_suffix(".mp3.part").write_bytes(b"abc")

    result = asyncio.run(orc.download_file(
        make_track(final, 6), make_meta(), None, asyncio.Semaphore(1)))

    assert result is False
    assert not final.exists()
    assert not final.with_suffix(".mp3.part").exists()
    db.close()


def test_cancel_records_actual_part_size(tmp_path: Path) -> None:
    response = FakeResponse(200, chunks=[b"abc", b"def"], pause_after_first=True)
    orc, db = make_orchestrator(tmp_path, [response])
    final = tmp_path / "track.mp3"

    async def scenario():
        task = asyncio.create_task(orc.download_file(
            make_track(final, 6), make_meta(), None, asyncio.Semaphore(1)))
        await response.content.first_written.wait()
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    part = final.with_suffix(".mp3.part")
    assert part.read_bytes() == b"abc"
    row = db.get_downloads_by_rj("RJ00000001")[0]
    assert row["status"] == "paused"
    assert row["downloaded_bytes"] == 3
    db.close()


def test_chunk_progress_does_not_write_sqlite_per_chunk(tmp_path: Path) -> None:
    response = FakeResponse(200, chunks=[b"a", b"b", b"c", b"d"])
    orc, db = make_orchestrator(tmp_path, [response])
    final = tmp_path / "track.mp3"
    original = db.upsert_download
    statuses = []

    def recording_upsert(*args, **kwargs):
        if len(args) >= 5:
            statuses.append(args[4])
        else:
            statuses.append(kwargs.get("status"))
        return original(*args, **kwargs)

    db.upsert_download = recording_upsert
    result = asyncio.run(orc.download_file(
        make_track(final, 4), make_meta(), None, asyncio.Semaphore(1)))

    assert result is True
    assert statuses.count("downloading") == 1
    assert statuses.count("completed") == 1
    assert len(statuses) == 2
    db.close()
