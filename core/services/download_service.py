from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from core.read_models import (
    BatchEnqueuePreview,
    DownloadQueueItem,
    DownloadQueuePage,
    DownloadQueueSummary,
)
from core.state_policy import WorkStatePolicy

_RJ_TOKEN_SPLIT = re.compile(r"[\s,，;；]+")
_RJ_EXACT = re.compile(r"^(?:RJ)?(\d{6,8})$", re.IGNORECASE)
_RJ_URL = re.compile(
    r"^https?://(?:www\.)?(?:asmr\.one|asmr-\d+\.com)/(?:work/)?(?:RJ)?(\d{6,8})(?:[/?#].*)?$",
    re.IGNORECASE,
)
_TERMINAL_WORK = {"completed", "registered", "verified", "external", "indexed"}
_ACTIVE_DOWNLOAD = {"queued", "downloading", "resuming", "paused", "failed"}


def normalize_rj_id(raw: str) -> str | None:
    token = (raw or "").strip()
    match = _RJ_EXACT.fullmatch(token) or _RJ_URL.fullmatch(token)
    if match is None:
        return None
    return f"RJ{match.group(1)}"


class DownloadService:
    """Read-only download presentation facade over the existing LibraryVault.

    This class never opens its own SQLite connection and never changes download
    state.  Mutating operations remain owned by AppController/Orchestrator.
    """

    FILTERS = {"working", "active", "queued", "paused", "failed", "completed", "all"}

    def __init__(self, vault: Any, *, output_dir: Path | None = None,
                 library_paths: Iterable[str | Path] = ()) -> None:
        self.vault = vault
        self.output_dir = Path(output_dir) if output_dir else None
        self.library_paths = tuple(Path(value) for value in library_paths if str(value).strip())

    @property
    def connection(self) -> sqlite3.Connection:
        return self.vault.conn

    @staticmethod
    def _normalize_page(page: int, page_size: int) -> tuple[int, int]:
        return max(1, int(page)), max(1, min(int(page_size), 200))

    @staticmethod
    def _queue_state(row: sqlite3.Row) -> str:
        work_status = str(row["work_status"] or "").lower()
        if int(row["downloading_files"] or 0) or int(row["resuming_files"] or 0):
            return "active"
        if int(row["queued_files"] or 0):
            return "queued"
        if work_status in _TERMINAL_WORK:
            return "completed"
        if int(row["paused_files"] or 0):
            return "paused"
        if int(row["failed_files"] or 0):
            return "failed"
        file_count = int(row["file_count"] or 0)
        completed = int(row["completed_files"] or 0)
        if file_count and completed >= file_count:
            return "completed"
        if work_status in {"preparing", "prepared", "metadata_failed", "partial", "no_pending"}:
            return work_status
        return work_status or "unknown"

    @staticmethod
    def _ui_status(queue_state: str) -> str:
        return {
            "active": "下载中",
            "queued": "队列中",
            "paused": "已暂停",
            "failed": "下载失败",
            "completed": "已完成",
            "preparing": "准备中...",
            "prepared": "已就绪",
            "metadata_failed": "元数据失败",
            "partial": "部分完成",
            "no_pending": "无可恢复文件",
        }.get(queue_state, queue_state)

    @staticmethod
    def _matches_filter(item: DownloadQueueItem, status_filter: str) -> bool:
        if status_filter == "all":
            return True
        if status_filter == "working":
            return not item.is_terminal and item.queue_state != "unknown"
        return item.queue_state == status_filter

    @staticmethod
    def _sort_key(item: DownloadQueueItem) -> tuple[int, str, str]:
        priority = {
            "active": 0,
            "queued": 1,
            "paused": 2,
            "failed": 3,
            "preparing": 4,
            "prepared": 5,
            "metadata_failed": 6,
            "partial": 7,
            "no_pending": 8,
            "completed": 9,
        }.get(item.queue_state, 10)
        return (priority, item.updated_at or "", item.rj_id)

    @staticmethod
    def _aggregate_sql() -> str:
        terminal = ",".join(f"'{value}'" for value in sorted(_TERMINAL_WORK))
        return f"""
            WITH queue_keys AS (
                SELECT rj_id FROM works
                UNION
                SELECT rj_id FROM downloads
            )
            SELECT
                k.rj_id,
                COALESCE(w.title, k.rj_id) AS title,
                COALESCE(w.circle, '') AS circle,
                COALESCE(w.cover_url, '') AS cover_url,
                COALESCE(w.local_path, '') AS local_path,
                LOWER(COALESCE(w.status, '')) AS work_status,
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
                COALESCE(MAX(CASE WHEN d.status IN ('downloading','resuming')
                                  THEN d.track_title END), '') AS current_file,
                COALESCE(MAX(CASE WHEN d.error IS NOT NULL AND d.error != ''
                                  THEN d.error END), '') AS error_summary,
                COALESCE(MAX(CAST(d.updated_at AS TEXT)),
                         CAST(w.downloaded_at AS TEXT), '') AS updated_at,
                CASE WHEN LOWER(COALESCE(w.status, '')) IN ({terminal})
                     THEN 1 ELSE 0 END AS terminal_work
            FROM queue_keys AS k
            LEFT JOIN works AS w ON w.rj_id = k.rj_id
            LEFT JOIN downloads AS d ON d.rj_id = k.rj_id
            GROUP BY k.rj_id, w.title, w.circle, w.cover_url, w.local_path,
                     w.status, w.downloaded_at
        """

    def _row_to_item(self, row: sqlite3.Row) -> DownloadQueueItem:
        queue_state = self._queue_state(row)
        terminal = bool(int(row["terminal_work"] or 0)) or queue_state == "completed"
        can_pause = queue_state in {"active", "queued", "resuming"}
        can_resume = queue_state in {"paused", "failed", "partial"}
        can_retry = queue_state in {"failed", "metadata_failed", "no_pending", "prepared"}
        # Keep capability rules tied to the explicit policy without changing legacy rows.
        if queue_state == "paused":
            can_resume = WorkStatePolicy.decide("paused", "queued").allowed
        return DownloadQueueItem(
            rj_id=str(row["rj_id"]),
            title=str(row["title"] or row["rj_id"]),
            circle=str(row["circle"] or ""),
            cover_url=str(row["cover_url"] or ""),
            local_path=str(row["local_path"] or ""),
            work_status=str(row["work_status"] or ""),
            queue_state=queue_state,
            ui_status=self._ui_status(queue_state),
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
            current_file=str(row["current_file"] or ""),
            error_summary=str(row["error_summary"] or ""),
            updated_at=str(row["updated_at"] or ""),
            can_pause=can_pause,
            can_resume=can_resume,
            can_retry=can_retry,
            is_terminal=terminal,
        )

    def fetch_queue_page(self, *, status_filter: str = "working", page: int = 1,
                         page_size: int = 24) -> DownloadQueuePage:
        """Return a paged queue snapshot with exactly two bounded SELECTs."""
        status_filter = status_filter if status_filter in self.FILTERS else "working"
        page, page_size = self._normalize_page(page, page_size)
        lock = getattr(self.vault, "_lock", None)
        if lock is None:
            return self._fetch_queue_page_unlocked(status_filter, page, page_size)
        with lock:
            return self._fetch_queue_page_unlocked(status_filter, page, page_size)

    def _fetch_queue_page_unlocked(self, status_filter: str, page: int,
                                   page_size: int) -> DownloadQueuePage:
        rows = self.connection.execute(self._aggregate_sql()).fetchall()
        all_items = [self._row_to_item(row) for row in rows]
        all_items.sort(key=self._sort_key)
        filtered = [item for item in all_items if self._matches_filter(item, status_filter)]
        total_items = len(filtered)
        page_count = max(1, (total_items + page_size - 1) // page_size)
        page = min(page, page_count)
        start = (page - 1) * page_size
        page_items = tuple(filtered[start:start + page_size])

        # The second SELECT is intentionally tiny and provides durable byte totals.
        totals = self.connection.execute(
            """SELECT COALESCE(SUM(downloaded_bytes), 0),
                      COALESCE(SUM(total_bytes), 0)
               FROM downloads"""
        ).fetchone()
        summary = DownloadQueueSummary(
            total_tasks=len(all_items),
            active_tasks=sum(item.queue_state == "active" for item in all_items),
            queued_tasks=sum(item.queue_state == "queued" for item in all_items),
            paused_tasks=sum(item.queue_state == "paused" for item in all_items),
            failed_tasks=sum(item.queue_state == "failed" for item in all_items),
            completed_tasks=sum(item.queue_state == "completed" for item in all_items),
            downloaded_bytes=int(totals[0] or 0),
            total_bytes=int(totals[1] or 0),
        )
        return DownloadQueuePage(
            items=page_items,
            summary=summary,
            page=page,
            page_size=page_size,
            total_items=total_items,
        )

    def _existing_tables(self) -> set[str]:
        return {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    def _directory_rj_ids(self, requested: set[str]) -> set[str]:
        roots: list[Path] = []
        if self.output_dir:
            roots.append(self.output_dir)
        roots.extend(self.library_paths)
        found: set[str] = set()
        for root in dict.fromkeys(roots):
            try:
                for child in root.iterdir():
                    if not child.is_dir():
                        continue
                    match = re.match(r"^(RJ\d{6,8})(?!\d)", child.name, re.IGNORECASE)
                    if match:
                        value = match.group(1).upper()
                        if value in requested:
                            found.add(value)
            except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
                continue
        return found

    def preview_enqueue(self, text: str, *, active_rj_ids: Iterable[str] = ()) -> BatchEnqueuePreview:
        """Classify pasted input without writing SQLite or touching task state."""
        active = {str(value).strip().upper() for value in active_rj_ids}
        ready_order: list[str] = []
        invalid: list[str] = []
        duplicates: list[str] = []
        seen: set[str] = set()
        for token in _RJ_TOKEN_SPLIT.split((text or "").strip()):
            if not token:
                continue
            normalized = normalize_rj_id(token)
            if normalized is None:
                invalid.append(token)
            elif normalized in seen:
                duplicates.append(normalized)
            else:
                seen.add(normalized)
                ready_order.append(normalized)

        requested = set(ready_order)
        if not requested:
            return BatchEnqueuePreview(
                invalid_tokens=tuple(invalid), duplicate_input=tuple(duplicates), reasons={}
            )

        tables = self._existing_tables()
        placeholders = ",".join("?" for _ in requested)
        params = tuple(sorted(requested))
        work_status: dict[str, str] = {}
        if "works" in tables:
            work_status = {
                str(row[0]).upper(): str(row[1] or "").lower()
                for row in self.connection.execute(
                    f"SELECT rj_id, status FROM works WHERE rj_id IN ({placeholders})", params
                ).fetchall()
            }
        download_states: dict[str, set[str]] = {value: set() for value in requested}
        if "downloads" in tables:
            for row in self.connection.execute(
                f"SELECT rj_id, status FROM downloads WHERE rj_id IN ({placeholders})", params
            ).fetchall():
                download_states.setdefault(str(row[0]).upper(), set()).add(str(row[1] or "").lower())
        library_ids: set[str] = set()
        if "library_items" in tables:
            library_ids.update(
                str(row[0]).upper() for row in self.connection.execute(
                    f"SELECT rj_id FROM library_items WHERE rj_id IN ({placeholders})", params
                ).fetchall()
            )
        if "library_index" in tables:
            library_ids.update(
                str(row[0]).upper() for row in self.connection.execute(
                    f"SELECT DISTINCT rj_id FROM library_index "
                    f"WHERE rj_id IN ({placeholders}) AND LOWER(COALESCE(status,'')) != 'missing'",
                    params,
                ).fetchall()
            )
        library_ids.update(self._directory_rj_ids(requested))

        categories: dict[str, list[str]] = {
            "ready": [], "active": [], "queue": [], "library": [], "completed": [], "review": []
        }
        reasons: dict[str, str] = {}
        for rj_id in ready_order:
            states = download_states.get(rj_id, set())
            status = work_status.get(rj_id, "")
            if rj_id in active:
                categories["active"].append(rj_id)
                reasons[rj_id] = "当前进程中已活动"
            elif states & _ACTIVE_DOWNLOAD:
                categories["queue"].append(rj_id)
                reasons[rj_id] = "SQLite 中已有可恢复/活动下载"
            elif status in _TERMINAL_WORK or (states and states <= {"completed", "registered"}):
                categories["completed"].append(rj_id)
                reasons[rj_id] = "下载历史已完成"
            elif rj_id in library_ids:
                categories["library"].append(rj_id)
                reasons[rj_id] = "资源库或同前缀目录已存在"
            elif status and status not in {"prepared", "metadata_failed", "preparing", "partial"}:
                categories["review"].append(rj_id)
                reasons[rj_id] = f"未知/历史状态：{status}"
            else:
                categories["ready"].append(rj_id)

        return BatchEnqueuePreview(
            ready=tuple(categories["ready"]),
            invalid_tokens=tuple(invalid),
            duplicate_input=tuple(duplicates),
            already_active=tuple(categories["active"]),
            already_in_queue=tuple(categories["queue"]),
            already_in_library=tuple(categories["library"]),
            already_completed=tuple(categories["completed"]),
            needs_review=tuple(categories["review"]),
            reasons=reasons,
        )
