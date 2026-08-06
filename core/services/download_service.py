from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.progress import ObservedFile, VerifiedDownloadSummary, verified_download_progress
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

    FILTERS = {"working", "active", "queued", "paused", "failed", "completed", "cancelled", "all"}

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
        cancelled_files = int(row["cancelled_files"] or 0)
        if (work_status == "cancelled" or cancelled_files) and not (
                int(row["paused_files"] or 0) or int(row["failed_files"] or 0)):
            return "cancelled"
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
            "cancelled": "已取消",
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
            if item.queue_state == "unknown":
                return False
            if not item.is_terminal:
                return True
            # Terminal download works (completed/registered) are candidates for
            # disk re-verification: apply_disk_verification downgrades the ones
            # that are incomplete on disk to partial (kept visible) and drops
            # the genuinely-complete ones from the active queue.  Library
            # states (verified/external/indexed) are never re-checked.
            return (item.queue_state == "completed"
                    and str(item.work_status or "").lower()
                    in {"completed", "registered"})
        return item.queue_state == status_filter

    @staticmethod
    def _sort_key(item: DownloadQueueItem) -> tuple[int, str]:
        # Issue #19: order must be stable across refreshes, not re-sorted by a
        # changing updated_at.  Priority, then a deterministic RJ id tiebreak.
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
            "cancelled": 9,
            "completed": 10,
        }.get(item.queue_state, 10)
        return (priority, item.rj_id)

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
                SUM(CASE WHEN d.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_files,
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
        terminal = bool(int(row["terminal_work"] or 0)) or queue_state in {"completed", "cancelled"}
        can_pause = queue_state in {"active", "queued", "resuming"}
        can_resume = queue_state in {"paused", "failed", "partial"}
        can_retry = queue_state in {"failed", "metadata_failed", "no_pending", "prepared", "cancelled"}
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
            cancelled_files=int(row["cancelled_files"] or 0),
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

    def fetch_working_page(self, *, page: int = 1,
                           page_size: int = 24) -> DownloadQueuePage:
        """Fetch + disk-verify + paginate the active queue in one pass.

        Terminal download candidates (completed/registered) are included as
        re-verification candidates, downgraded to ``partial`` when incomplete
        on disk, and dropped when genuinely complete — all BEFORE final
        pagination.  A Working page is therefore never emptied by post-filter
        drops and ``total_items``/``page_count`` reflect the verified state
        (review #2c).
        """
        page_size = max(1, min(int(page_size), 200))
        # Bounded over-fetch: every Working candidate (active + terminal
        # download works) is verified before the requested slice is chosen.
        candidates = self.fetch_queue_page(
            status_filter="working", page=1, page_size=200)
        verified = self.apply_disk_verification(
            candidates, status_filter="working")
        items = [item for item in verified.items if not item.is_terminal]
        total_items = len(items)
        page_count = max(1, (total_items + page_size - 1) // page_size)
        page = max(1, min(int(page), page_count))
        start = (page - 1) * page_size
        return DownloadQueuePage(
            items=tuple(items[start:start + page_size]),
            summary=candidates.summary,
            page=page,
            page_size=page_size,
            total_items=total_items,
        )

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
            cancelled_tasks=sum(item.queue_state == "cancelled" for item in all_items),
            total_bytes=int(totals[1] or 0),
        )
        return DownloadQueuePage(
            items=page_items,
            summary=summary,
            page=page,
            page_size=page_size,
            total_items=total_items,
        )

    @staticmethod
    def _safe_stat(path: Path) -> int | None:
        try:
            if path.is_file():
                return path.stat().st_size
        except OSError:
            pass
        return None

    def apply_disk_verification(
            self, page: DownloadQueuePage, *, status_filter: str | None = None
    ) -> DownloadQueuePage:
        """Return a copy of ``page`` whose items carry P0-D disk-verified
        progress (never >100%) and whose terminal works that are incomplete on
        disk are downgraded to ``partial`` for presentation.

        Kept separate from ``fetch_queue_page`` so the two-SELECT contract of
        the queue snapshot is preserved; callers run it off the UI thread.  One
        additional SELECT fetches the per-file paths for the page's works only,
        bounded by the page size.  ``status_filter == "working"`` additionally
        drops terminal items that ARE complete (they belong to the completed
        view, not the active queue).
        """
        items_by_rj = {item.rj_id: item for item in page.items
                       if item.local_path}
        if not items_by_rj:
            return page
        placeholders = ",".join("?" * len(items_by_rj))
        rows = self.connection.execute(
            f"SELECT rj_id, local_path, total_bytes FROM downloads "
            f"WHERE rj_id IN ({placeholders})",
            tuple(items_by_rj),
        ).fetchall()
        grouped: dict[str, list[tuple[str, int]]] = {}
        for rj, local_path, total in rows:
            grouped.setdefault(str(rj), []).append((str(local_path or ""),
                                                    int(total or 0)))

        summaries: dict[str, VerifiedDownloadSummary] = {}
        for rj_id in items_by_rj:
            by_abs: dict[str, int] = {}
            for local_path, total in grouped.get(rj_id, []):
                try:
                    norm = os.path.normcase(str(Path(local_path).resolve()))
                except OSError:
                    norm = os.path.normcase(local_path)
                by_abs[norm] = max(by_abs.get(norm, 0), total)
            observed = []
            for key, expected in by_abs.items():
                final = Path(key)
                part = final.with_suffix(final.suffix + ".part")
                observed.append(ObservedFile(
                    expected_bytes=expected,
                    final_bytes=self._safe_stat(final),
                    part_bytes=self._safe_stat(part),
                ))
            summaries[rj_id] = verified_download_progress(observed)

        updated = []
        for item in page.items:
            summary = summaries.get(item.rj_id)
            if summary is None:
                updated.append(item)
                continue
            updated.append(self._apply_verified_state(item, summary))
        if status_filter == "working":
            # Terminal items still present are genuinely complete (or library
            # states) — drop them from the active queue; incomplete ones were
            # already downgraded to partial above.
            updated = [item for item in updated if not item.is_terminal]
        return DownloadQueuePage(
            items=tuple(updated),
            summary=page.summary,
            page=page.page,
            page_size=page.page_size,
            total_items=page.total_items,
        )

    @staticmethod
    def _apply_verified_state(item: DownloadQueueItem,
                              summary: VerifiedDownloadSummary) -> DownloadQueueItem:
        """Attach disk-verified metrics and, if a completed/registered work is
        NOT actually complete on disk, downgrade its PRESENTATION state so it
        never shows as a green terminal 100%.  The production DB is untouched.
        """
        replaced = replace(
            item,
            verified_bytes=summary.verified_bytes,
            verified_files=summary.complete_files,
            overage_file_count=summary.overage_files,
            verified_known_bytes=summary.known_verified_bytes,
            verified_expected_bytes=summary.known_expected_bytes,
            verified_progress=summary.progress,
        )
        if item.queue_state != "completed":
            return replaced
        # Library-indexed states are validated elsewhere; never downgrade them.
        if str(item.work_status or "").lower() in {"verified", "external", "indexed"}:
            return replaced
        if DownloadService._disk_confirms_complete(summary, item.file_count):
            return replaced
        return replace(
            replaced,
            queue_state="partial",
            ui_status="部分完成",
            is_terminal=False,
            can_resume=True,
            can_retry=True,
        )

    @staticmethod
    def _disk_confirms_complete(summary: VerifiedDownloadSummary,
                                file_count: int) -> bool:
        """A terminal work is only truly complete when EVERY expected file row
        is confirmed present/complete on disk: all files observed complete, no
        overage, and a 100% known-size ratio."""
        if file_count <= 0:
            return False
        if summary.overage_files > 0:
            return False
        if summary.complete_files < file_count:
            return False
        if summary.known_expected_bytes > 0 and summary.progress < 1.0:
            return False
        return True

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
            elif status == "cancelled" or (states and states <= {"cancelled"}):
                categories["review"].append(rj_id)
                reasons[rj_id] = "已取消任务，可选择继续保留的断点"
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
