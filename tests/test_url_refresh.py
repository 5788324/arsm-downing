"""P0-C: signed-URL refresh must be single-flight and fail-closed.

Issue #20: hundreds of files mechanically retried an expired signed URL.
``SignedUrlRefresher`` must (1) run exactly one refresh per RJ under concurrency,
(2) map fresh URLs back to the affected files by stable key, and (3) return
None on refresh failure so callers can fail closed without a refresh loop.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.url_refresh import SignedUrlRefresher


def _track(key: str, url: str, size: int = 100):
    return SimpleNamespace(id=key, title=key, url=url, size=size)


def test_refresh_is_single_flight_under_concurrency() -> None:
    async def _case():
        fetches = 0

        async def fetcher(rj_id):
            nonlocal fetches
            fetches += 1
            await asyncio.sleep(0.05)
            return [_track("a.mp3", f"http://cdn/{rj_id}/fresh"), ]

        refresher = SignedUrlRefresher(fetcher)
        results = await asyncio.gather(
            refresher.refresh("RJ00000001"),
            refresher.refresh("RJ00000001"),
            refresher.refresh("RJ00000001"),
        )
        return fetches, results, refresher

    fetches, results, refresher = asyncio.run(_case())
    assert fetches == 1
    assert all(result is not None for result in results)
    assert refresher.refresh_count_for("RJ00000001") == 1


def test_refresh_returns_latest_url_for_affected_key() -> None:
    async def _case():
        async def fetcher(_rj_id):
            return [_track("a.mp3", "http://cdn/new-a"),
                    _track("b.mp3", "http://cdn/new-b")]

        refresher = SignedUrlRefresher(fetcher)
        mapping = await refresher.refresh("RJ00000001")
        return refresher, mapping

    refresher, mapping = asyncio.run(_case())
    assert mapping["a.mp3"].url == "http://cdn/new-a"
    assert refresher.latest_url("RJ00000001", "b.mp3") == "http://cdn/new-b"
    assert refresher.latest_url("RJ00000001", "missing.mp3") is None


def test_refresh_failure_returns_none_and_counts_failure() -> None:
    async def _case():
        calls = {"n": 0}

        async def fetcher(_rj_id):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("network down")
            return [_track("a.mp3", "http://cdn/ok")]

        refresher = SignedUrlRefresher(fetcher)
        first = await refresher.refresh("RJ00000001")
        # Caller may try again next round; this time it succeeds.
        second = await refresher.refresh("RJ00000001")
        return refresher, first, second

    refresher, first, second = asyncio.run(_case())
    assert first is None
    assert refresher.refresh_failures.get("RJ00000001") == 1
    assert second is not None
    assert refresher.refresh_count_for("RJ00000001") == 2


def test_empty_refresh_is_a_failure_not_a_success() -> None:
    async def _case():
        async def fetcher(_rj_id):
            return []

        refresher = SignedUrlRefresher(fetcher)
        result = await refresher.refresh("RJ00000001")
        return refresher, result

    refresher, result = asyncio.run(_case())
    assert result is None
    assert refresher.refresh_failures.get("RJ00000001") == 1


def test_refresh_across_distinct_rjs_does_not_share_flight() -> None:
    async def _case():
        async def fetcher(rj_id):
            await asyncio.sleep(0.02)
            return [_track("a.mp3", f"http://cdn/{rj_id}")]

        refresher = SignedUrlRefresher(fetcher)
        await asyncio.gather(
            refresher.refresh("RJ00000001"),
            refresher.refresh("RJ00000002"),
        )
        return refresher

    refresher = asyncio.run(_case())
    assert refresher.refresh_count_for("RJ00000001") == 1
    assert refresher.refresh_count_for("RJ00000002") == 1


def test_second_expiry_is_not_auto_refreshed_by_refresher() -> None:
    """The refresher never loops on its own; the caller owns the round budget."""
    async def _case():
        async def fetcher(_rj_id):
            return [_track("a.mp3", "http://cdn/never")]

        refresher = SignedUrlRefresher(fetcher)
        mapping = await refresher.refresh("RJ00000001")
        # A second manual refresh is allowed but recorded — no mechanical retry
        # of the same URL is ever performed inside this class.
        await refresher.refresh("RJ00000001")
        return refresher, mapping

    refresher, mapping = asyncio.run(_case())
    assert mapping is not None
    assert refresher.refresh_count_for("RJ00000001") == 2
