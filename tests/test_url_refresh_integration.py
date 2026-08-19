"""P0-C end-to-end: download_file must fail over to a fresh signed URL.

The media endpoint returns 403 (expired signed URL) on the stale URL; the
refresh fetcher supplies a fresh TrackItem pointing at a healthy endpoint.
The stale endpoint must be hit exactly once — never mechanically retried —
and the file must land from the fresh URL.
"""

from __future__ import annotations

import asyncio
import logging
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


def _fresh_track(rj_id: str, fresh_url: str, index: int) -> TrackItem:
    return TrackItem(
        id=f"t{index}", title=f"f{index}.bin", type="file", url=fresh_url,
        size=len(PAYLOAD), save_path=Path(f"{rj_id}-{index}.bin"),
    )


async def _site(app: web.Application):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}/media"


async def _orchestrator(tmp_path: Path, retry_count: int = 2):
    config = ConfigManager()
    config.retry_count = retry_count
    config.chunk_size = 4
    config.tag_audio = False
    config.download_fallback_to_proxy = False
    db = LibraryVault(tmp_path / "history.db")
    kernel = NetworkKernel(config)
    orchestrator = Orchestrator(kernel, config, db)
    return orchestrator, kernel, db


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

    orchestrator, kernel, db = await _orchestrator(tmp_path)

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


def test_retry_count_one_still_tries_the_fresh_url(tmp_path: Path) -> None:
    """Review #2: with retry_count=1 the fresh URL must still be attempted."""

    async def _case():
        expired_hits = []

        async def expired(_request):
            expired_hits.append(1)
            return web.Response(status=403, text="expired")

        app_a = web.Application()
        app_a.router.add_get("/media", expired)
        runner_a, stale_url = await _site(app_a)

        async def fresh(_request):
            return web.Response(body=PAYLOAD)

        app_b = web.Application()
        app_b.router.add_get("/media", fresh)
        runner_b, fresh_url = await _site(app_b)

        orchestrator, kernel, db = await _orchestrator(tmp_path, retry_count=1)
        final = tmp_path / "track.bin"
        track = TrackItem(id="t1", title="track.bin", type="file", url=stale_url,
                          size=len(PAYLOAD), save_path=final)

        async def _fetch(_rj_id):
            return [TrackItem(id="t1", title="track.bin", type="file",
                              url=fresh_url, size=len(PAYLOAD), save_path=final)]

        refresher = SignedUrlRefresher(_fetch)
        try:
            result = await orchestrator.download_file(
                track, meta(), None, asyncio.Semaphore(1), refresher)
            return result, final, expired_hits, refresher
        finally:
            await kernel.shutdown()
            db.close()
            await runner_a.cleanup()
            await runner_b.cleanup()

    result, final, expired_hits, refresher = asyncio.run(_case())
    assert result is True
    assert final.read_bytes() == PAYLOAD
    assert len(expired_hits) == 1  # stale URL once, then the fresh URL succeeded
    assert refresher.refresh_count_for(meta().rj_id) == 1


def test_second_signed_error_fails_closed_without_second_refresh(tmp_path: Path) -> None:
    """Review #2: a freshly-refreshed URL that is ALSO signed-invalid must fail
    closed immediately — no second refresh, no mechanical retry of it."""

    async def _case():
        stale_hits = []
        fresh_hits = []

        async def stale(_request):
            stale_hits.append(1)
            return web.Response(status=403, text="expired")

        async def fresh_403(_request):
            fresh_hits.append(1)
            return web.Response(status=403, text="still expired")

        app_a = web.Application()
        app_a.router.add_get("/media", stale)
        runner_a, stale_url = await _site(app_a)
        app_b = web.Application()
        app_b.router.add_get("/media", fresh_403)
        runner_b, fresh_url = await _site(app_b)

        orchestrator, kernel, db = await _orchestrator(tmp_path, retry_count=3)
        final = tmp_path / "track.bin"
        track = TrackItem(id="t1", title="track.bin", type="file", url=stale_url,
                          size=len(PAYLOAD), save_path=final)

        async def _fetch(_rj_id):
            return [TrackItem(id="t1", title="track.bin", type="file",
                              url=fresh_url, size=len(PAYLOAD), save_path=final)]

        refresher = SignedUrlRefresher(_fetch)
        try:
            result = await orchestrator.download_file(
                track, meta(), None, asyncio.Semaphore(1), refresher)
            return result, stale_hits, fresh_hits, refresher
        finally:
            await kernel.shutdown()
            db.close()
            await runner_a.cleanup()
            await runner_b.cleanup()

    result, stale_hits, fresh_hits, refresher = asyncio.run(_case())
    assert result is False
    assert stale_hits == [1]  # stale URL once
    assert fresh_hits == [1]  # fresh URL attempted once, then fail-closed
    assert refresher.refresh_count_for(meta().rj_id) == 1  # never a 2nd refresh


def test_url_refresh_log_never_leaks_signed_query(tmp_path: Path, caplog) -> None:
    """Review #2: signed query params must never reach the logs."""
    signed_fresh = "http://127.0.0.1:9/media?X-Amz-Signature=LEAKME123"
    records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Handler()
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        async def _case():
            async def _fetcher(_rj_id):
                return [TrackItem(id="t1", title="track.bin", type="file",
                                  url=signed_fresh, size=100,
                                  save_path=tmp_path / "track.bin")]

            async def _expired(_request):
                return web.Response(status=403, text="expired")

            app = web.Application()
            app.router.add_get("/media", _expired)
            runner, stale_url = await _site(app)
            orchestrator, kernel, db = await _orchestrator(tmp_path)
            track = TrackItem(id="t1", title="track.bin", type="file",
                              url=stale_url, size=100,
                              save_path=tmp_path / "track.bin")
            refresher = SignedUrlRefresher(_fetcher)
            try:
                # Fresh URL is unreachable (port 9) → still exercises the log line
                # on the refresh path before the transport error surfaces.
                await orchestrator.download_file(
                    track, meta(), None, asyncio.Semaphore(1), refresher)
            finally:
                await kernel.shutdown()
                db.close()
                await runner.cleanup()

        asyncio.run(_case())
    finally:
        logger.removeHandler(handler)

    joined = "\n".join(records)
    assert "LEAKME123" not in joined
    assert "X-Amz-Signature=" not in joined
    assert "URL_REFRESH" in joined


async def run_multi_file_refresh(tmp_path: Path) -> tuple:
    """All files of one work 403 on the stale URL; the refresh fetcher is held
    open until every file is waiting, proving they all share ONE refresh."""
    stale_hits = []

    async def expired(_request):
        stale_hits.append(1)
        await asyncio.sleep(0.05)
        return web.Response(status=403, text="expired")

    app_a = web.Application()
    app_a.router.add_get("/media", expired)
    runner_a, stale_url = await _site(app_a)

    async def fresh(_request):
        return web.Response(body=PAYLOAD)

    app_b = web.Application()
    app_b.router.add_get("/media", fresh)
    runner_b, fresh_url = await _site(app_b)

    orchestrator, kernel, db = await _orchestrator(tmp_path)

    release = asyncio.Event()
    refresh_calls: list = []

    async def slow_fetch(rj_id: str):
        refresh_calls.append(rj_id)
        await release.wait()
        return [
            TrackItem(id=f"t{i}", title=f"f{i}.bin", type="file", url=fresh_url,
                      size=len(PAYLOAD), save_path=tmp_path / f"f{i}.bin")
            for i in range(4)
        ]

    refresher = SignedUrlRefresher(slow_fetch)
    tracks = [
        TrackItem(id=f"t{i}", title=f"f{i}.bin", type="file", url=stale_url,
                  size=len(PAYLOAD), save_path=tmp_path / f"f{i}.bin")
        for i in range(4)
    ]
    sem = asyncio.Semaphore(4)
    try:
        tasks = [
            asyncio.create_task(
                orchestrator.download_file(t, meta(), None, sem, refresher))
            for t in tracks
        ]
        # Give every file time to 403 and start waiting on the refresh.
        for _ in range(100):
            if len(refresh_calls) >= 1:
                break
            await asyncio.sleep(0.01)
        assert len(refresh_calls) == 1  # exactly one refresh for the RJ
        release.set()
        results = await asyncio.gather(*tasks)
        return results, stale_hits, refresh_calls, tmp_path
    finally:
        await kernel.shutdown()
        db.close()
        await runner_a.cleanup()
        await runner_b.cleanup()


def test_multi_file_concurrent_403_shares_one_refresh(tmp_path: Path) -> None:
    """Review #1: concurrent signed-URL failures must all await the SAME
    refresh future and all land with the fresh URL."""

    async def _case():
        return await run_multi_file_refresh(tmp_path)

    results, stale_hits, refresh_calls, work_dir = asyncio.run(_case())
    assert all(result is True for result in results)
    assert len(stale_hits) == 4          # each file hit the stale URL once
    assert len(refresh_calls) == 1       # single-flight: one refresh for the RJ
    for i in range(4):
        assert (work_dir / f"f{i}.bin").read_bytes() == PAYLOAD