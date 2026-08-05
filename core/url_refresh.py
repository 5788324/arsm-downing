"""Single-flight signed-URL refresh for media downloads.

P0-C: when many files of one work share a signed CDN URL that expired, the old
code retried the same URL up to ``retry_count`` times per file.  With hundreds
of files that produced a retry storm of identical failing requests.

``SignedUrlRefresher`` guarantees that only one metadata/tracks refresh runs
per RJ at a time (single-flight); every concurrently-failing file awaits the
same refresh.  Each refresh produces a ``{stable_key: TrackItem}`` mapping so
only the affected files are retried with a fresh URL.  A refresh failure or an
unmappable file is reported back to the caller (fail-closed, ``.part`` kept).
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional


class SignedUrlRefresher:
    """Per-RJ single-flight track refresh with observable counters."""

    def __init__(self,
                 fetcher: Callable[[str], Awaitable[List[Any]]],
                 key_of: Optional[Callable[[Any], str]] = None) -> None:
        self._fetcher = fetcher  # async (rj_id) -> list of fresh TrackItem
        self._key_of = key_of or (
            lambda track: str(getattr(track, "id", None) or
                              getattr(track, "title", ""))
        )
        self._in_flight: Dict[str, asyncio.Task] = {}
        self._latest: Dict[str, Dict[str, Any]] = {}
        # Last completed outcome per RJ (mapping on success, None on failure).
        # ``ensure_refreshed_once`` reuses it instead of guessing completion
        # from counters, which is what caused the "refresh failed" mis-reads.
        self._last_outcome: Dict[str, Optional[Dict[str, Any]]] = {}
        # ── observability ──
        self.refresh_count: Dict[str, int] = {}
        self.refresh_failures: Dict[str, int] = {}

    @staticmethod
    def _key_of_track(track: Any) -> str:
        return str(getattr(track, "id", None) or getattr(track, "title", ""))

    async def refresh(self, rj_id: str) -> Optional[Dict[str, Any]]:
        """Explicitly refresh one RJ now (single-flight under concurrency).

        Every caller that awaits this method shares the same in-flight task.
        ``None`` is returned when the refresh itself fails; it is never retried
        inside this class.
        """
        return await self._ensure_refresh(rj_id, force=True)

    async def ensure_refreshed_once(self, rj_id: str) -> Optional[Dict[str, Any]]:
        """Return this round's refresh result for ``rj_id`` exactly once.

        Unlike ``refresh`` (which always re-fetches), this is safe for the
        orchestrator's "one refresh per RJ per round" contract:

        - an in-flight refresh is awaited by every concurrent caller (same
          future, no counting-based guessing);
        - a completed success is reused directly;
        - a completed failure is returned as-is so every caller fails closed
          consistently instead of racing ahead and mis-reading ``latest_url``.
        """
        return await self._ensure_refresh(rj_id, force=False)

    async def _ensure_refresh(self, rj_id: str,
                              force: bool) -> Optional[Dict[str, Any]]:
        task = self._in_flight.get(rj_id)
        if task is not None and not task.done():
            return await asyncio.shield(task)
        if not force and rj_id in self._last_outcome:
            return self._last_outcome[rj_id]
        task = asyncio.create_task(self._do_refresh(rj_id),
                                   name=f"arsm-url-refresh-{rj_id}")
        self._in_flight[rj_id] = task
        try:
            return await task
        finally:
            self._in_flight.pop(rj_id, None)

    async def _do_refresh(self, rj_id: str) -> Optional[Dict[str, Any]]:
        self.refresh_count[rj_id] = self.refresh_count.get(rj_id, 0) + 1
        try:
            fresh = await self._fetcher(rj_id)
        except Exception:
            self.refresh_failures[rj_id] = self.refresh_failures.get(rj_id, 0) + 1
            self._last_outcome[rj_id] = None
            return None
        if not fresh:
            self.refresh_failures[rj_id] = self.refresh_failures.get(rj_id, 0) + 1
            self._last_outcome[rj_id] = None
            return None
        mapping = {self._key_of(track): track for track in fresh}
        self._latest[rj_id] = mapping
        self._last_outcome[rj_id] = mapping
        return mapping

    def latest_url(self, rj_id: str, key: str) -> Optional[str]:
        """Return the most recent fresh URL for a file key, if known."""
        track = self._latest.get(rj_id, {}).get(key)
        if track is None:
            return None
        return getattr(track, "url", None)

    def refresh_count_for(self, rj_id: str) -> int:
        return self.refresh_count.get(rj_id, 0)