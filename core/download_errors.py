"""Downloader-specific errors used by the P0 worker-pool refactor."""

from __future__ import annotations


class SignedUrlExpired(Exception):
    """A signed media URL is no longer valid (HTTP 400/401/403).

    Raised instead of being retried mechanically.  The worker pool catches it,
    refreshes the track list once per round (single-flight per RJ) and retries
    only the affected files with a fresh URL.  A second expiry is fail-closed.
    """
