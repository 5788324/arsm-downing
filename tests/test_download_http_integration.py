import asyncio
from pathlib import Path

from aiohttp import web

from core.config import ConfigManager
from core.database import LibraryVault
from core.models import TrackItem, WorkMetadata
from core.network import NetworkKernel
from core.orchestrator import Orchestrator


PAYLOAD = b"0123456789abcdef"


def meta() -> WorkMetadata:
    return WorkMetadata(
        rj_id="RJ00000002", title="HTTP Test", circle="Test", cv=[], tags=[],
        price=0, dl_count=0, source_url="", rating=0.0,
        release_date="", cover_url="",
    )


async def start_range_server():
    seen_ranges = []

    async def media(request: web.Request):
        range_header = request.headers.get("Range")
        seen_ranges.append(range_header)
        if not range_header:
            return web.Response(body=PAYLOAD, status=200)
        start = int(range_header.removeprefix("bytes=").removesuffix("-"))
        if start >= len(PAYLOAD):
            return web.Response(
                status=416,
                headers={"Content-Range": f"bytes */{len(PAYLOAD)}"},
            )
        body = PAYLOAD[start:]
        return web.Response(
            body=body,
            status=206,
            headers={
                "Content-Range": f"bytes {start}-{len(PAYLOAD)-1}/{len(PAYLOAD)}",
                "Content-Length": str(len(body)),
            },
        )

    app = web.Application()
    app.router.add_get("/track", media)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}/track", seen_ranges


async def run_download(tmp_path: Path, initial_part: bytes | None):
    runner, url, seen_ranges = await start_range_server()
    config = ConfigManager()
    config.retry_count = 1
    config.chunk_size = 4
    config.tag_audio = False
    db = LibraryVault(tmp_path / "history.db")
    kernel = NetworkKernel(config)
    orchestrator = Orchestrator(kernel, config, db)
    final_path = tmp_path / "track.bin"
    part_path = final_path.with_suffix(".bin.part")
    if initial_part is not None:
        part_path.write_bytes(initial_part)
    track = TrackItem(
        id="track", title="track.bin", type="file", url=url,
        size=len(PAYLOAD), save_path=final_path,
    )
    try:
        result = await orchestrator.download_file(
            track, meta(), None, asyncio.Semaphore(1))
        row = dict(db.get_downloads_by_rj(meta().rj_id)[0])
        return result, final_path, part_path, row, seen_ranges
    finally:
        await kernel.shutdown()
        db.close()
        await runner.cleanup()


def test_real_http_full_download(tmp_path: Path) -> None:
    result, final_path, part_path, row, ranges = asyncio.run(
        run_download(tmp_path, None))
    assert result is True
    assert final_path.read_bytes() == PAYLOAD
    assert not part_path.exists()
    assert row["status"] == "completed"
    assert ranges == [None]


def test_real_http_resume_uses_matching_range(tmp_path: Path) -> None:
    prefix = PAYLOAD[:7]
    result, final_path, part_path, row, ranges = asyncio.run(
        run_download(tmp_path, prefix))
    assert result is True
    assert final_path.read_bytes() == PAYLOAD
    assert not part_path.exists()
    assert row["downloaded_bytes"] == len(PAYLOAD)
    assert ranges == ["bytes=7-"]


def test_real_http_416_requires_exact_complete_part(tmp_path: Path) -> None:
    result, final_path, part_path, row, ranges = asyncio.run(
        run_download(tmp_path, PAYLOAD))
    assert result is True
    assert final_path.read_bytes() == PAYLOAD
    assert not part_path.exists()
    assert row["status"] == "completed"
    assert ranges == [f"bytes={len(PAYLOAD)}-"]
