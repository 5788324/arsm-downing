"""Thread-safe coalescing sink for high-frequency UI progress events.

P0-A: every downloaded network chunk currently becomes a ``ProgressEvent`` that
is forwarded to Flet's single event loop.  A large job (hundreds of files, each
streamed in 1 MiB chunks) can therefore starve the UI event loop indefinitely,
which is the freeze seen in Issue #20.

``UiDispatcher`` keeps only the newest value per ``(rj, track)``, guarantees
that protected outcomes (completed / failed / paused / cancelled) are delivered
even under a flood, and hands the UI loop a bounded, drainable snapshot so
processing can run under a time budget and yield back to Flet.

Control messages (snack / tray / close / work status) are intentionally NOT
routed through this class: they keep their own ``queue.Queue`` and are consumed
first so they are never starved by progress traffic.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Tuple

from core.models import ProgressEvent

#: Outcomes that must be delivered even when a flood of later "downloading"
#: ticks for the same key follows.  ``paused`` is included so a pause during a
#: progress burst is never swallowed by a newer in-flight tick.
PROTECTED_STATUSES = frozenset({"completed", "failed", "paused", "cancelled"})

ProgressKey = Tuple[str, str]


class UiDispatcher:
    """Coalescing, thread-safe progress sink used by the UI message poller."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Dict[ProgressKey, ProgressEvent] = {}
        self._protected: Dict[ProgressKey, ProgressEvent] = {}
        self._dirty = False
        # ── observability ──
        self.received = 0
        self.coalesced = 0
        self.protected_events = 0
        self.latest_pending = 0

    @staticmethod
    def _key(event: ProgressEvent) -> ProgressKey:
        return (event.rj_id, event.track_id or event.track_title)

    def submit(self, event: ProgressEvent) -> None:
        """Record one progress event.  Safe to call from any thread."""
        key = self._key(event)
        with self._lock:
            self.received += 1
            if event.status in PROTECTED_STATUSES:
                self._protected[key] = event
                self.protected_events += 1
                self._latest.pop(key, None)
            else:
                if key in self._protected:
                    # A protected outcome for this key is already pending;
                    # a newer non-terminal tick is stale and must not override it.
                    self.coalesced += 1
                    return
                if key in self._latest:
                    self.coalesced += 1
                self._latest[key] = event
            self._dirty = True

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._latest or self._protected or self._dirty)

    def pending_count(self) -> int:
        with self._lock:
            self.latest_pending = len(self._latest) + len(self._protected)
            return self.latest_pending

    def drain(self) -> Tuple[List[ProgressEvent], List[ProgressEvent]]:
        """Atomically take the current snapshot.

        Returns ``(latest_progress, protected_outcomes)``.  ``protected`` events
        are returned first so the view applies the outcome, then any still-valid
        in-flight ticks for other files.
        """
        with self._lock:
            protected = list(self._protected.values())
            latest = list(self._latest.values())
            self._protected.clear()
            self._latest.clear()
            self._dirty = False
            self.latest_pending = 0
        return latest, protected

    def clear(self) -> None:
        with self._lock:
            self._latest.clear()
            self._protected.clear()
            self._dirty = False
            self.latest_pending = 0

    def requeue(self, events: List[ProgressEvent]) -> None:
        """Put undrained events back for the next dispatch cycle (P0-A budget).

        Metrics are not incremented again: these were already counted when they
        were first submitted.
        """
        with self._lock:
            for event in events:
                key = self._key(event)
                if event.status in PROTECTED_STATUSES:
                    self._protected[key] = event
                else:
                    self._latest[key] = event
            self._dirty = True
