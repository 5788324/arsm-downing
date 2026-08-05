"""P0-C end-to-end: download_file must fail over to a fresh signed URL.

The media endpoint returns 403 (expired signed URL) on the stale URL; the
refresh fetcher supplies a fresh TrackItem pointing at a healthy endpoint.
The stale endpoint must be hit exactly once — never mechanically retried —
and the file must land from the fresh URL.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web

from core.config import ConfigManager
from core.database import LibraryVault
from core.models import TrackItem, WorkMetadata
from core.network import NetworkKernel
from core.orchestrator import Orchestrator
from core.url_refresh import SignedUrlRefresher

PAYLOAD = b"0123456789abcdef"


def meta() -> WorkMetadata:
    return WorkMetadata(
        rj_id="RJ00000008", title="Refresh Test", circle="Test", cv=[], tags=[],
        price=0, dl_count=0, source_url="", rating=0.0,
        release_date="", cover_url="",
    )


async def _site(app: web.Application):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}/media"


async def run_refresh_download(tmp_path: Path, refresh_fetcher) -> tuple:
    expired_hits = []

    async def expired(_request):
        expired_hits.append(1)
        return web.Response(status=403, text="signed url expired")

    app_a = web.Application()
    app_a.router.add_get("/media", expired)
    runner_a, stale_url = await _site(app_a)

    async def fresh(request):
        return web.Response(body=PAYLOAD)

    app_b = web.Application()
    app_b.router.add_get("/media", fresh)
    runner_b, fresh_url = await _site(app_b)

    config = ConfigManager()
    config.retry_count = 2
    config.chunk_size = 4
    config.tag_audio = False
    config.download_fallback_to_proxy = False
    db = LibraryVault(tmp_path / "history.db")
    kernel = NetworkKernel(config)
    orchestrator = Orchestrator(kernel, config, db)

    final = tmp_path / "track.bin"
    track = TrackItem(
        id="t1", title="track.bin", type="file", url=stale_url,
        size=len(PAYLOAD), save_path=final,
    )
    default_refresher = None

    async def _default_fetch(_rj_id):
        return [TrackItem(id="t1", title="track.bin", type="file",
                          url=fresh_url, size=len(PAYLOAD), save_path=final)]

    refresher = SignedUrlRefresher(refresh_fetcher or _default_fetch)
    try:
        result = await orchestrator.download_file(
            track, meta(), None, asyncio.Semaphore(1), refresher)
        row = dict(db.get_downloads_by_rj(meta().rj_id)[0])
        return result, final, row, expired_hits, refresher
    finally:
        await kernel.shutdown()
        db.close()
        await runner_a.cleanup()
        await runner_b.cleanup()


def test_stale_signed_url_is_refreshed_not_retried(tmp_path: Path) -> None:
    async def _case():
        return await run_refresh_download(tmp_path, None)

    result, final, row, expired_hits, refresher = asyncio.run(_case())
    assert result is True
    assert final.read_bytes() == PAYLOAD
    assert row["status"] == "completed"
    # The stale URL is hit exactly once — no mechanical same-URL retry.
    assert len(expired_hits) == 1
    assert refresher.refresh_count_for(meta().rj_id) == 1


def test_refresh_failure_fails_closed_without_retry_storm(tmp_path: Path) -> None:
    async def _fetcher(_rj_id):
        raise OSError("refresh network down")

    async def _case():
        return await run_refresh_download(tmp_path, _fetcher)

    result, final, row, expired_hits, refresher = asyncio.run(_case())
    assert result is False
    assert not final.exists()
    assert row["status"] == "failed"
    # Only the initial stale-URL request; refresh failure must not loop.
    assert len(expired_hits) == 1
    assert refresher.refresh_failures.get(meta().rj_id, 0) == 1