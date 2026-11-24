"""Structured download failures and bounded retry decisions."""

from __future__ import annotations

import asyncio
import errno
import random
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

import aiohttp


class DownloadHttpError(OSError):
    def __init__(self, status: int, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.status = int(status)
        self.retry_after = retry_after


class LowSpeedError(TimeoutError):
    """The connection stayed alive but transferred too little data."""


@dataclass(frozen=True)
class DownloadFailure:
    code: str
    retryable: bool
    message: str
    http_status: int | None = None
    retry_after_seconds: float | None = None


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def classify_download_error(exc: BaseException) -> DownloadFailure:
    message = str(exc) or exc.__class__.__name__
    lowered = message.casefold()
    if isinstance(exc, DownloadHttpError):
        status = exc.status
        retryable = status in {408, 425, 429} or 500 <= status <= 599
        return DownloadFailure(
            code=f"http_{status}", retryable=retryable, message=message,
            http_status=status,
            retry_after_seconds=_retry_after_seconds(exc.retry_after),
        )
    if isinstance(exc, LowSpeedError):
        return DownloadFailure("low_speed", True, message)
    if isinstance(exc, (asyncio.TimeoutError, aiohttp.ServerTimeoutError)):
        return DownloadFailure("network_timeout", True, message)
    if isinstance(exc, aiohttp.ClientConnectionError):
        return DownloadFailure("connection_error", True, message)
    if isinstance(exc, PermissionError):
        return DownloadFailure("permission_denied", False, message)
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOSPC:
        return DownloadFailure("disk_full", False, message)
    if "content-range" in lowered or "range response" in lowered:
        return DownloadFailure("range_contract_error", True, message)
    if "size mismatch" in lowered or "response length" in lowered:
        return DownloadFailure("size_mismatch", True, message)
    if "no space" in lowered or "disk full" in lowered:
        return DownloadFailure("disk_full", False, message)
    if "permission" in lowered or "access is denied" in lowered:
        return DownloadFailure("permission_denied", False, message)
    if isinstance(exc, (aiohttp.ClientError, OSError)):
        return DownloadFailure("network_or_io", True, message)
    return DownloadFailure("unexpected", False, message)


def retry_delay_seconds(*, attempt: int, backoff_base: int,
                        retry_after: float | None = None) -> float:
    """Return a bounded exponential delay with small anti-stampede jitter."""
    if retry_after is not None:
        return min(300.0, max(0.0, retry_after))
    base = max(1, int(backoff_base)) ** max(1, int(attempt))
    return min(60.0, float(base)) + random.uniform(0.05, 0.45)
