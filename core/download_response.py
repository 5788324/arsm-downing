"""Pure helpers for validating resumable HTTP download responses.

The downloader must never infer completion from an HTTP status alone.  These
helpers keep the range and local-file rules deterministic and independently
testable.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Mapping, Optional


_CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$", re.IGNORECASE)


@dataclass(frozen=True)
class DownloadResponsePlan:
    action: str
    mode: str = ""
    initial_bytes: int = 0
    reason: str = ""

    @property
    def should_write(self) -> bool:
        return self.action == "write"


@dataclass(frozen=True)
class ContentRange:
    start: int
    end: int
    total: Optional[int]

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_content_range(value: str) -> Optional[ContentRange]:
    match = _CONTENT_RANGE_RE.match((value or "").strip())
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    total = None if match.group(3) == "*" else int(match.group(3))
    if end < start:
        return None
    return ContentRange(start=start, end=end, total=total)


def local_partial_size(final_path: Path, part_path: Path, expected_size: int) -> int:
    """Return the actual resumable byte count without trusting database state."""
    for candidate in (part_path, final_path):
        try:
            size = candidate.stat().st_size
        except (FileNotFoundError, OSError):
            continue
        if expected_size > 0 and size >= expected_size:
            if size == expected_size:
                return size
            continue
        if size > 0:
            return size
    return 0


def plan_download_response(
    *,
    status: int,
    headers: Mapping[str, str],
    requested_offset: int,
    expected_size: int,
    local_size: int,
) -> DownloadResponsePlan:
    """Translate an HTTP response into a safe local-file action."""
    if status == 416:
        if expected_size > 0 and local_size == expected_size:
            return DownloadResponsePlan(action="complete_local")
        return DownloadResponsePlan(
            action="retry_from_zero",
            reason=(
                "HTTP 416 but the local partial file is not complete "
                f"({local_size}/{expected_size})"
            ),
        )

    if status == 200:
        return DownloadResponsePlan(action="write", mode="wb", initial_bytes=0)

    if status != 206:
        return DownloadResponsePlan(
            action="http_error",
            reason=f"HTTP {status}",
        )

    content_range = parse_content_range(headers.get("Content-Range", ""))
    if content_range is None:
        return DownloadResponsePlan(
            action="retry_from_zero",
            reason="HTTP 206 without a valid Content-Range",
        )

    if content_range.start != requested_offset:
        return DownloadResponsePlan(
            action="retry_from_zero",
            reason=(
                "Content-Range start does not match the requested offset "
                f"({content_range.start}!={requested_offset})"
            ),
        )

    if expected_size > 0 and content_range.total not in (None, expected_size):
        return DownloadResponsePlan(
            action="retry_from_zero",
            reason=(
                "Content-Range total does not match metadata "
                f"({content_range.total}!={expected_size})"
            ),
        )

    content_length = headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) != content_range.length:
                return DownloadResponsePlan(
                    action="retry_from_zero",
                    reason="Content-Length does not match Content-Range",
                )
        except ValueError:
            return DownloadResponsePlan(
                action="retry_from_zero",
                reason="Invalid Content-Length",
            )

    return DownloadResponsePlan(
        action="write",
        mode="ab" if requested_offset > 0 else "wb",
        initial_bytes=requested_offset,
    )
