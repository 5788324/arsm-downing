from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

_RJ_TOKEN_SPLIT = re.compile(r"[\s,，;；]+")
_RJ_TOKEN = re.compile(r"^(?:RJ)?(\d{6,8})$", re.IGNORECASE)
_TERMINAL_WORK_STATUSES = (
    "completed",
    "registered",
    "verified",
    "external",
    "indexed",
    "stale",
    "ignored",
)


@dataclass(frozen=True)
class BatchRjPreview:
    """Pure, side-effect-free preview for pasted RJ input."""

    ready: tuple[str, ...]
    duplicate_input: tuple[str, ...]
    invalid_tokens: tuple[str, ...]
    already_active: tuple[str, ...]
    already_known: tuple[str, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.ready)

    @property
    def submitted_count(self) -> int:
        return (
            len(self.ready)
            + len(self.duplicate_input)
            + len(self.invalid_tokens)
            + len(self.already_active)
            + len(self.already_known)
        )

    @property
    def requires_confirmation(self) -> bool:
        return bool(
            self.duplicate_input
            or self.invalid_tokens
            or self.already_active
            or self.already_known
            or len(self.ready) > 1
        )


@dataclass(frozen=True)
class DownloadTaskSnapshot:
    rj_id: str
    title: str
    circle: str
    cover_url: str
    work_status: str
    local_path: str
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
    updated_at: str

    @property
    def percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return round(
            min(100.0, self.downloaded_bytes / self.total_bytes * 100.0),
            1,
        )

    @property
    def is_terminal_work(self) -> bool:
        return self.work_status.lower() in _TERMINAL_WORK_STATUSES

    @property
    def queue_state(self) -> str:
        """Return one exclusive presentation state for filtering and sorting."""

        if self.downloading_files or self.resuming_files:
            return "active"
        if self.queued_files:
            return "queued"
        # A terminal work may contain historical paused/failed rows.  Those rows
        # must not make it reappear as an active task.
        if self.is_terminal_work:
            return "completed"
        if self.paused_files:
            return "paused"
        if self.failed_files:
            return "failed"
        if self.file_count and self.completed_files == self.file_count:
            return "completed"
        return self.work_status.lower() or "unknown"

    @property
    def ui_status(self) -> str:
        return {
            "active": "下载中",
            "queued": "队列中",
            "paused": "已暂停",
            "failed": "下载失败",
            "completed": "已完成",
            "prepared": "已就绪",
            "preparing": "准备中...",
            "metadata_failed": "元数据失败",
            "no_pending": "无可恢复文件",
            "partial": "部分完成",
        }.get(self.queue_state, self.queue_state)


@dataclass(frozen=True)
class DownloadQueueSummary:
    total_tasks: int
    active_tasks: int
    queued_tasks: int
    paused_tasks: int
    failed_tasks: int
    completed_tasks: int


@dataclass(frozen=True)
class DownloadQueuePage:
    items: tuple[DownloadTaskSnapshot, ...]
    summary: DownloadQueueSummary
    page: int
    page_size: int
    total_items: int

    @property
    def page_count(self) -> int:
        if self.total_items <= 0:
            return 1
        return max(1, math.ceil(self.total_items / self.page_size))



def normalize_rj_id(raw: str) -> str | None:
    """Normalize one strict RJ token while preserving its significant digits."""

    match = _RJ_TOKEN.fullmatch(raw.strip())
    if not match:
        return None
    return f"RJ{match.group(1)}"



def preview_rj_input(
    text: str,
    *,
    active_rj_ids: Iterable[str] = (),
    known_rj_ids: Iterable[str] = (),
) -> BatchRjPreview:
    """Parse, normalize, de-duplicate and classify pasted RJ input.

    The function does not write SQLite, create folders or enqueue downloads.
    """

    active = {item.strip().upper() for item in active_rj_ids}
    known = {item.strip().upper() for item in known_rj_ids}

    ready: list[str] = []
    duplicate_input: list[str] = []
    invalid_tokens: list[str] = []
    already_active: list[str] = []
    already_known: list[str] = []
    seen: set[str] = set()

    for token in _RJ_TOKEN_SPLIT.split(text.strip()):
        if not token:
            continue
        normalized = normalize_rj_id(token)
        if normalized is None:
            invalid_tokens.append(token)
            continue
        if normalized in seen:
            duplicate_input.append(normalized)
            continue
        seen.add(normalized)
        if normalized in active:
            already_active.append(normalized)
        elif normalized in known:
            already_known.append(normalized)
        else:
            ready.append(normalized)

    return BatchRjPreview(
        ready=tuple(ready),
        duplicate_input=tuple(duplicate_input),
        invalid_tokens=tuple(invalid_tokens),
        already_active=tuple(already_active),
        already_known=tuple(already_known),
    )


class DownloadQueueQueryService:
    """Build paged queue read models with bounded SQLite queries."""

    _STATE_FILTERS: Mapping[str, str] = {
        "all": "1=1",
        "active": "(downloading_files > 0 OR resuming_files > 0)",
        "queued": (
            "downloading_files = 0 AND resuming_files = 0 "
            "AND queued_files > 0"
        ),
        "paused": (
            "is_terminal_work = 0 AND downloading_files = 0 "
            "AND resuming_files = 0 AND queued_files = 0 "
            "AND paused_files > 0"
        ),
        "failed": (
            "is_terminal_work = 0 AND downloading_files = 0 "
            "AND resuming_files = 0 AND queued_files = 0 "
            "AND paused_files = 0 AND failed_files > 0"
        ),
        "completed": (
            "is_terminal_work = 1 OR "
            "(file_count > 0 AND completed_files = file_count)"
        ),
        "working": (
            "is_terminal_work = 0 AND ("
            "downloading_files > 0 OR resuming_files > 0 OR "
            "queued_files > 0 OR paused_files > 0 OR failed_files > 0 OR "
            "work_status IN ('preparing','prepared','partial',"
            "'metadata_failed','no_pending')"
            ")"
        ),
    }

    def __init__(self, vault) -> None:
        self.vault = vault

    @staticmethod
    def _normalize_page(page: int, page_size: int) -> tuple[int, int]:
        return max(1, int(page)), max(1, min(int(page_size), 200))

    @classmethod
    def _filter_sql(cls, status_filter: str) -> str:
        return cls._STATE_FILTERS.get(
            status_filter,
            cls._STATE_FILTERS["working"],
        )

    @staticmethod
    def _aggregate_cte() -> str:
        terminal_sql = ",".join(f"'{value}'" for value in _TERMINAL_WORK_STATUSES)
        return f"""
            WITH queue_keys AS (
                SELECT rj_id FROM works
                UNION
                SELECT rj_id FROM downloads
            ),
            queue_rows AS (
                SELECT
                    k.rj_id AS rj_id,
                    COALESCE(w.title, k.rj_id) AS title,
                    COALESCE(w.circle, '') AS circle,
                    COALESCE(w.cover_url, '') AS cover_url,
                    LOWER(COALESCE(w.status, '')) AS work_status,
                    COALESCE(w.local_path, '') AS local_path,
                    COUNT(d.id) AS file_count,
                    SUM(CASE WHEN d.status IN ('completed','registered') THEN 1 ELSE 0 END) AS completed_files,
                    SUM(CASE WHEN d.status = 'registered' THEN 1 ELSE 0 END) AS registered_files,
                    SUM(CASE WHEN d.status = 'queued' THEN 1 ELSE 0 END) AS queued_files,
                    SUM(CASE WHEN d.status = 'downloading' THEN 1 ELSE 0 END) AS downloading_files,
                    SUM(CASE WHEN d.status = 'resuming' THEN 1 ELSE 0 END) AS resuming_files,
                    SUM(CASE WHEN d.status = 'paused' THEN 1 ELSE 0 END) AS paused_files,
                    SUM(CASE WHEN d.status = 'failed' THEN 1 ELSE 0 END) AS failed_files,
                    COALESCE(SUM(d.downloaded_bytes), 0) AS downloaded_bytes,
                    COALESCE(SUM(d.total_bytes), 0) AS total_bytes,
                    COALESCE(MAX(CAST(d.updated_at AS TEXT)), CAST(w.downloaded_at AS TEXT), '') AS updated_at,
                    CASE WHEN LOWER(COALESCE(w.status, '')) IN ({terminal_sql})
                         THEN 1 ELSE 0 END AS is_terminal_work
                FROM queue_keys AS k
                LEFT JOIN works AS w ON w.rj_id = k.rj_id
                LEFT JOIN downloads AS d ON d.rj_id = k.rj_id
                GROUP BY
                    k.rj_id, w.title, w.circle, w.cover_url, w.status,
                    w.local_path, w.downloaded_at
            )
        """

    def fetch_page(
        self,
        *,
        status_filter: str = "working",
        page: int = 1,
        page_size: int = 24,
    ) -> DownloadQueuePage:
        page, page_size = self._normalize_page(page, page_size)
        where = self._filter_sql(status_filter)
        cte = self._aggregate_cte()
        page_sql = cte + f"""
            SELECT * FROM queue_rows
            WHERE {where}
            ORDER BY
                CASE
                    WHEN downloading_files > 0 OR resuming_files > 0 THEN 0
                    WHEN queued_files > 0 THEN 1
                    WHEN is_terminal_work = 0 AND paused_files > 0 THEN 2
                    WHEN is_terminal_work = 0 AND failed_files > 0 THEN 3
                    ELSE 4
                END,
                updated_at DESC,
                rj_id ASC
            LIMIT ? OFFSET ?
        """
        count_sql = cte + f" SELECT COUNT(*) FROM queue_rows WHERE {where}"
        summary_sql = cte + """
            SELECT
                COUNT(*) AS total_tasks,
                SUM(CASE WHEN downloading_files > 0 OR resuming_files > 0 THEN 1 ELSE 0 END) AS active_tasks,
                SUM(CASE WHEN downloading_files = 0 AND resuming_files = 0 AND queued_files > 0 THEN 1 ELSE 0 END) AS queued_tasks,
                SUM(CASE WHEN is_terminal_work = 0 AND downloading_files = 0 AND resuming_files = 0 AND queued_files = 0 AND paused_files > 0 THEN 1 ELSE 0 END) AS paused_tasks,
                SUM(CASE WHEN is_terminal_work = 0 AND downloading_files = 0 AND resuming_files = 0 AND queued_files = 0 AND paused_files = 0 AND failed_files > 0 THEN 1 ELSE 0 END) AS failed_tasks,
                SUM(CASE WHEN is_terminal_work = 1 OR (file_count > 0 AND completed_files = file_count) THEN 1 ELSE 0 END) AS completed_tasks
            FROM queue_rows
        """
        lock = getattr(self.vault, "_lock", None)
        if lock is None:
            return self._fetch_unlocked(
                page_sql, count_sql, summary_sql, page, page_size
            )
        with lock:
            return self._fetch_unlocked(
                page_sql, count_sql, summary_sql, page, page_size
            )

    def _fetch_unlocked(
        self,
        page_sql: str,
        count_sql: str,
        summary_sql: str,
        page: int,
        page_size: int,
    ) -> DownloadQueuePage:
        connection: sqlite3.Connection = self.vault.conn
        total_items = int(connection.execute(count_sql).fetchone()[0])
        page_count = max(1, math.ceil(total_items / page_size))
        page = min(page, page_count)
        offset = (page - 1) * page_size
        rows = connection.execute(page_sql, (page_size, offset)).fetchall()
        summary_row = connection.execute(summary_sql).fetchone()
        items = tuple(
            DownloadTaskSnapshot(
                rj_id=row["rj_id"],
                title=row["title"],
                circle=row["circle"],
                cover_url=row["cover_url"],
                work_status=row["work_status"],
                local_path=row["local_path"],
                file_count=int(row["file_count"] or 0),
                completed_files=int(row["completed_files"] or 0),
                registered_files=int(row["registered_files"] or 0),
                queued_files=int(row["queued_files"] or 0),
                downloading_files=int(row["downloading_files"] or 0),
                resuming_files=int(row["resuming_files"] or 0),
                paused_files=int(row["paused_files"] or 0),
                failed_files=int(row["failed_files"] or 0),
                downloaded_bytes=int(row["downloaded_bytes"] or 0),
                total_bytes=int(row["total_bytes"] or 0),
                updated_at=str(row["updated_at"] or ""),
            )
            for row in rows
        )
        summary = DownloadQueueSummary(
            total_tasks=int(summary_row["total_tasks"] or 0),
            active_tasks=int(summary_row["active_tasks"] or 0),
            queued_tasks=int(summary_row["queued_tasks"] or 0),
            paused_tasks=int(summary_row["paused_tasks"] or 0),
            failed_tasks=int(summary_row["failed_tasks"] or 0),
            completed_tasks=int(summary_row["completed_tasks"] or 0),
        )
        return DownloadQueuePage(
            items=items,
            summary=summary,
            page=page,
            page_size=page_size,
            total_items=total_items,
        )

    def find_known_rj_ids(self, rj_ids: Sequence[str]) -> set[str]:
        """Return known library/work IDs using bounded, read-only queries."""

        normalized = sorted({item.strip().upper() for item in rj_ids if item})
        if not normalized:
            return set()

        connection: sqlite3.Connection = self.vault.conn
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        found: set[str] = set()
        for start in range(0, len(normalized), 400):
            chunk = normalized[start:start + 400]
            placeholders = ",".join("?" for _ in chunk)
            work_rows = connection.execute(
                f"""SELECT rj_id FROM works
                    WHERE rj_id IN ({placeholders})
                      AND LOWER(COALESCE(status, '')) NOT IN
                          ('prepared','metadata_failed')""",
                chunk,
            ).fetchall()
            found.update(row[0] for row in work_rows)
            if "library_index" in tables:
                library_rows = connection.execute(
                    f"""SELECT DISTINCT rj_id FROM library_index
                        WHERE rj_id IN ({placeholders})
                          AND LOWER(COALESCE(status, '')) != 'missing'""",
                    chunk,
                ).fetchall()
                found.update(row[0] for row in library_rows)
        return found

    def preview_input(
        self,
        text: str,
        *,
        active_rj_ids: Iterable[str] = (),
    ) -> BatchRjPreview:
        """Preview pasted input with one bounded known-work lookup."""

        first_pass = preview_rj_input(
            text,
            active_rj_ids=active_rj_ids,
        )
        known = self.find_known_rj_ids(first_pass.ready)
        return preview_rj_input(
            text,
            active_rj_ids=active_rj_ids,
            known_rj_ids=known,
        )
