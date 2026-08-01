from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class DownloadQueueItem:
    """Immutable presentation model for one download work."""

    rj_id: str
    title: str
    circle: str
    cover_url: str
    local_path: str
    work_status: str
    queue_state: str
    ui_status: str
    file_count: int
    completed_files: int
    registered_files: int
    queued_files: int
    downloading_files: int
    resuming_files: int
    paused_files: int
    failed_files: int
    downloaded_bytes: int
    total_bytes: int
    current_file: str
    error_summary: str
    updated_at: str
    can_pause: bool
    can_resume: bool
    can_retry: bool
    is_terminal: bool

    @property
    def progress(self) -> float:
        if self.total_bytes <= 0:
            if self.file_count > 0 and self.completed_files >= self.file_count:
                return 1.0
            return 0.0
        return max(0.0, min(1.0, self.downloaded_bytes / self.total_bytes))


@dataclass(frozen=True)
class DownloadQueueSummary:
    total_tasks: int = 0
    active_tasks: int = 0
    queued_tasks: int = 0
    paused_tasks: int = 0
    failed_tasks: int = 0
    completed_tasks: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0


@dataclass(frozen=True)
class DownloadQueuePage:
    items: tuple[DownloadQueueItem, ...]
    summary: DownloadQueueSummary
    page: int
    page_size: int
    total_items: int

    @property
    def page_count(self) -> int:
        if self.total_items <= 0:
            return 1
        return max(1, (self.total_items + self.page_size - 1) // self.page_size)


@dataclass(frozen=True)
class BatchEnqueuePreview:
    """Side-effect-free classification of pasted RJ input."""

    ready: tuple[str, ...] = ()
    invalid_tokens: tuple[str, ...] = ()
    duplicate_input: tuple[str, ...] = ()
    already_active: tuple[str, ...] = ()
    already_in_queue: tuple[str, ...] = ()
    already_in_library: tuple[str, ...] = ()
    already_completed: tuple[str, ...] = ()
    needs_review: tuple[str, ...] = ()
    reasons: Mapping[str, str] | None = None

    @property
    def submitted_count(self) -> int:
        return sum(
            len(values)
            for values in (
                self.ready,
                self.invalid_tokens,
                self.duplicate_input,
                self.already_active,
                self.already_in_queue,
                self.already_in_library,
                self.already_completed,
                self.needs_review,
            )
        )

    @property
    def requires_confirmation(self) -> bool:
        return bool(
            len(self.ready) > 1
            or self.invalid_tokens
            or self.duplicate_input
            or self.already_active
            or self.already_in_queue
            or self.already_in_library
            or self.already_completed
            or self.needs_review
        )
