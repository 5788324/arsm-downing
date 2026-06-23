"""SpeedMeter — sliding-window bandwidth estimator.

Tracks download speed over a configurable time window (default 5 seconds),
supporting per-track, per-work, and global aggregation levels.
"""

import time
from dataclasses import dataclass, field
from typing import Deque, Optional


@dataclass
class SpeedSample:
    timestamp: float
    total_bytes: int


@dataclass
class SpeedMeter:
    """Tracks download speed over a sliding time window.

    Usage:
        meter = SpeedMeter(window_seconds=5.0)
        meter.update(downloaded_bytes)
        print(f"{meter.speed_bps / 1024:.0f} KB/s")
        print(f"ETA: {meter.eta_seconds(downloaded_bytes, total_bytes)}s")
    """

    window_seconds: float = 5.0
    _samples: Deque[SpeedSample] = field(default_factory=lambda: __import__(
        'collections').deque())
    _last_bytes: int = 0
    _paused: bool = False

    def update(self, total_bytes: int):
        """Record a new byte count sample."""
        if self._paused:
            return
        now = time.time()
        self._samples.append(SpeedSample(now, total_bytes))
        self._last_bytes = total_bytes
        # Prune samples older than the window
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()

    @property
    def speed_bps(self) -> float:
        """Current speed in bytes per second, based on sliding window."""
        if self._paused or len(self._samples) < 2:
            return 0.0
        first = self._samples[0]
        last = self._samples[-1]
        dt = last.timestamp - first.timestamp
        if dt <= 0:
            return 0.0
        db = last.total_bytes - first.total_bytes
        return max(0.0, db / dt)

    def eta_seconds(self, downloaded: int, total: int) -> Optional[float]:
        """Estimated seconds remaining. None if speed is zero."""
        if total <= 0 or downloaded >= total:
            return 0.0
        bps = self.speed_bps
        if bps <= 0:
            return None
        return (total - downloaded) / bps

    def pause(self):
        """Mark as paused, freezing speed at 0."""
        self._paused = True

    def resume(self):
        """Resume tracking."""
        self._paused = False

    def reset(self):
        """Clear all samples."""
        self._samples.clear()
        self._last_bytes = 0
        self._paused = False


class SpeedTracker:
    """Manages per-track, per-work, and global SpeedMeters."""

    def __init__(self, window_seconds: float = 5.0):
        self.window = window_seconds
        self.global_meter = SpeedMeter(window_seconds)
        self.work_meters: dict = {}   # rj_id → SpeedMeter
        self.track_meters: dict = {}  # (rj_id, track_id) → SpeedMeter
        self._paused_works: set = set()

    def get_track(self, rj_id: str, track_id: str) -> SpeedMeter:
        key = (rj_id, track_id)
        if key not in self.track_meters:
            self.track_meters[key] = SpeedMeter(self.window)
        return self.track_meters[key]

    def get_work(self, rj_id: str) -> SpeedMeter:
        if rj_id not in self.work_meters:
            self.work_meters[rj_id] = SpeedMeter(self.window)
        return self.work_meters[rj_id]

    def update(self, rj_id: str, track_id: str, downloaded: int):
        """Update all three meters from a single byte-count sample."""
        if rj_id in self._paused_works:
            return
        self.global_meter.update(downloaded)
        self.get_work(rj_id).update(downloaded)
        self.get_track(rj_id, track_id).update(downloaded)

    def track_speed(self, rj_id: str, track_id: str) -> float:
        return self.get_track(rj_id, track_id).speed_bps

    def work_speed(self, rj_id: str) -> float:
        return self.get_work(rj_id).speed_bps

    def global_speed(self) -> float:
        return self.global_meter.speed_bps

    def track_eta(self, rj_id: str, track_id: str,
                  downloaded: int, total: int) -> Optional[float]:
        return self.get_track(rj_id, track_id).eta_seconds(downloaded, total)

    def work_eta(self, rj_id: str, downloaded: int, total: int) -> Optional[float]:
        return self.get_work(rj_id).eta_seconds(downloaded, total)

    def pause_track(self, rj_id: str, track_id: str):
        self.get_track(rj_id, track_id).pause()

    def pause_work(self, rj_id: str):
        self._paused_works.add(rj_id)
        self.get_work(rj_id).pause()
        for (r, t), m in self.track_meters.items():
            if r == rj_id:
                m.pause()

    def resume_work(self, rj_id: str):
        self._paused_works.discard(rj_id)
        self.get_work(rj_id).resume()
        for (r, t), m in self.track_meters.items():
            if r == rj_id:
                m.resume()

    def reset_work(self, rj_id: str):
        self._paused_works.discard(rj_id)
        to_drop = [(r, t) for (r, t) in self.track_meters if r == rj_id]
        for key in to_drop:
            self.track_meters.pop(key, None)
