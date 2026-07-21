"""Safe, testable maintenance operations used by the Tools view.

All functions open dedicated SQLite connections.  Preview functions are read-only;
mutating functions fail closed when active/resumable downloads exist.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ACTIVE_STATUSES = (
    "queued",
    "paused",
    "downloading",
    "resuming",
    "failed",
    "stale",
    "ignored",
)
TERMINAL_QUEUE_STATUSES = ("completed", "registered", "metadata_failed")


def _connect(db_path: str | Path, *, read_only: bool) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve(strict=True)
    if read_only:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)
    else:
        conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def _connection(db_path: str | Path, *, read_only: bool):
    conn = _connect(db_path, read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def _status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(conn, "downloads"):
        return {}
    rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM downloads GROUP BY status ORDER BY status"
    ).fetchall()
    return {str(row["status"]): int(row["cnt"]) for row in rows}


def _active_count(status_counts: dict[str, int]) -> int:
    return sum(status_counts.get(status, 0) for status in ACTIVE_STATUSES)


def _candidate_token(kind: str, rows: list[dict[str, Any]]) -> str:
    raw = json.dumps(
        {"kind": kind, "rows": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class MetadataCachePreview:
    db_path: str
    cutoff: str
    total_rows: int
    expired_rows: int
    protected_expired_rows: int
    removable_rows: int
    active_download_rows: int
    candidate_rj_ids: tuple[str, ...]
    preview_token: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidate_rj_ids"] = list(self.candidate_rj_ids)
        return payload


def preview_metadata_cache_cleanup(
    db_path: str | Path,
    *,
    ttl_hours: int = 168,
    now: datetime | None = None,
) -> MetadataCachePreview:
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(hours=max(1, int(ttl_hours)))
    cutoff_text = cutoff.replace(tzinfo=None).isoformat(timespec="seconds")
    with _connection(db_path, read_only=True) as conn:
        statuses = _status_counts(conn)
        if not _table_exists(conn, "metadata_cache"):
            rows: list[sqlite3.Row] = []
            total = 0
        else:
            total = int(conn.execute("SELECT COUNT(*) FROM metadata_cache").fetchone()[0])
            rows = conn.execute(
                """
                SELECT mc.rj_id, COALESCE(mc.updated_at, mc.fetched_at) AS cached_at,
                       EXISTS (
                           SELECT 1 FROM downloads d
                           WHERE d.rj_id = mc.rj_id
                             AND d.status IN ('queued','paused','downloading','resuming',
                                              'failed','stale','ignored')
                       ) AS protected
                FROM metadata_cache mc
                WHERE datetime(COALESCE(mc.updated_at, mc.fetched_at)) < datetime(?)
                ORDER BY mc.rj_id
                """,
                (cutoff_text,),
            ).fetchall()

    expired = [dict(row) for row in rows]
    removable = [row for row in expired if not int(row.get("protected") or 0)]
    candidates = tuple(str(row["rj_id"]) for row in removable)
    token_rows = [
        {"rj_id": row["rj_id"], "cached_at": row.get("cached_at")}
        for row in removable
    ]
    return MetadataCachePreview(
        db_path=str(Path(db_path).expanduser().resolve(strict=False)),
        cutoff=cutoff_text,
        total_rows=total,
        expired_rows=len(expired),
        protected_expired_rows=len(expired) - len(removable),
        removable_rows=len(removable),
        active_download_rows=_active_count(statuses),
        candidate_rj_ids=candidates,
        preview_token=_candidate_token("metadata-cache", token_rows),
    )


def cleanup_metadata_cache(
    db_path: str | Path,
    *,
    preview_token: str,
    ttl_hours: int = 168,
    now: datetime | None = None,
) -> dict[str, Any]:
    preview = preview_metadata_cache_cleanup(db_path, ttl_hours=ttl_hours, now=now)
    if preview.preview_token != preview_token:
        return {"success": False, "error_code": "preview_changed", "preview": preview.to_dict()}
    if not preview.candidate_rj_ids:
        return {"success": True, "deleted_rows": 0, "preview": preview.to_dict()}

    placeholders = ",".join("?" for _ in preview.candidate_rj_ids)
    with _connection(db_path, read_only=False) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.execute(
                f"""
                DELETE FROM metadata_cache
                WHERE rj_id IN ({placeholders})
                  AND NOT EXISTS (
                      SELECT 1 FROM downloads d
                      WHERE d.rj_id = metadata_cache.rj_id
                        AND d.status IN ('queued','paused','downloading','resuming',
                                         'failed','stale','ignored')
                  )
                """,
                preview.candidate_rj_ids,
            )
            deleted = max(0, int(cursor.rowcount))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"success": True, "deleted_rows": deleted, "preview": preview.to_dict()}


@dataclass(frozen=True)
class QueueCleanupPreview:
    db_path: str
    queue_path: str
    status_counts: dict[str, int]
    active_download_rows: int
    terminal_db_rows: int
    terminal_queue_items: int
    blocked: bool
    blocked_reason: str
    preview_token: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_queue(queue_path: Path) -> dict[str, Any]:
    if not queue_path.exists():
        return {}
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def preview_queue_cleanup(
    db_path: str | Path,
    queue_path: str | Path,
) -> QueueCleanupPreview:
    with _connection(db_path, read_only=True) as conn:
        counts = _status_counts(conn)
        terminal_db = sum(counts.get(status, 0) for status in TERMINAL_QUEUE_STATUSES)
    path = Path(queue_path)
    try:
        queue = _read_queue(path)
    except (OSError, json.JSONDecodeError):
        queue = {}
    terminal_labels = {
        "已完成",
        "completed",
        "registered",
        "metadata_failed",
        "Metadata failed",
    }
    terminal_queue = sum(
        1
        for item in queue.values()
        if isinstance(item, dict) and str(item.get("status") or "") in terminal_labels
    )
    active = _active_count(counts)
    rows = [{"status": key, "count": value} for key, value in sorted(counts.items())]
    rows.append({"queue_terminal_items": terminal_queue})
    return QueueCleanupPreview(
        db_path=str(Path(db_path).expanduser().resolve(strict=False)),
        queue_path=str(path.expanduser().resolve(strict=False)),
        status_counts=counts,
        active_download_rows=active,
        terminal_db_rows=terminal_db,
        terminal_queue_items=terminal_queue,
        blocked=active > 0,
        blocked_reason=(
            "active_or_resumable_downloads_present" if active > 0 else ""
        ),
        preview_token=_candidate_token("queue-cleanup", rows),
    )


def preview_vacuum(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path).expanduser().resolve(strict=True)
    with _connection(path, read_only=True) as conn:
        counts = _status_counts(conn)
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        freelist = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    active = _active_count(counts)
    return {
        "db_path": str(path),
        "db_size_bytes": path.stat().st_size,
        "page_count": page_count,
        "freelist_count": freelist,
        "reclaimable_bytes_estimate": freelist * page_size,
        "active_download_rows": active,
        "blocked": active > 0,
        "blocked_reason": "active_or_resumable_downloads_present" if active else "",
    }


def vacuum_database(db_path: str | Path) -> dict[str, Any]:
    preview = preview_vacuum(db_path)
    if preview["blocked"]:
        return {"success": False, "error_code": preview["blocked_reason"], "preview": preview}
    before = int(preview["db_size_bytes"])
    with _connection(db_path, read_only=False) as conn:
        conn.execute("VACUUM")
    after = Path(db_path).expanduser().resolve(strict=True).stat().st_size
    return {
        "success": True,
        "size_before": before,
        "size_after": after,
        "reclaimed_bytes": max(0, before - after),
    }


def preview_backlog_candidates(
    db_path: str | Path,
    *,
    source: str = "ignored",
    limit: int = 30,
) -> dict[str, Any]:
    """Return a read-only stale/ignored batch without product-specific exclusions."""
    if source not in {"ignored", "stale", "all"}:
        raise ValueError("source must be ignored, stale, or all")
    bounded_limit = max(1, min(int(limit), 100))
    clauses = ["status IN ('stale','ignored')"]
    params: list[Any] = []
    if source in {"ignored", "stale"}:
        clauses.append("status = ?")
        params.append(source)
    where = " AND ".join(clauses)
    with _connection(db_path, read_only=True) as conn:
        rows = conn.execute(
            f"""SELECT rj_id, COUNT(*) AS cnt
                FROM downloads
                WHERE {where}
                GROUP BY rj_id
                ORDER BY cnt ASC, rj_id ASC
                LIMIT ?""",
            (*params, bounded_limit),
        ).fetchall()
        rj_ids = [str(row["rj_id"]) for row in rows]
        source_total = sum(int(row["cnt"]) for row in rows)
        actual_rows: list[dict[str, Any]] = []
        if rj_ids:
            placeholders = ",".join("?" for _ in rj_ids)
            actual = conn.execute(
                f"""SELECT rj_id, COUNT(*) AS cnt
                    FROM downloads
                    WHERE rj_id IN ({placeholders})
                      AND status IN ('stale','ignored')
                    GROUP BY rj_id ORDER BY rj_id""",
                rj_ids,
            ).fetchall()
            actual_rows = [
                {"rj_id": str(row["rj_id"]), "count": int(row["cnt"])}
                for row in actual
            ]
    return {
        "source": source,
        "limit": bounded_limit,
        "rj_ids": rj_ids,
        "candidate_count": len(rj_ids),
        "source_rows": source_total,
        "actual_rows": actual_rows,
        "actual_total": sum(row["count"] for row in actual_rows),
    }


def build_system_diagnostic(
    db_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    db = Path(db_path).expanduser().resolve(strict=False)
    output = Path(output_dir).expanduser().resolve(strict=False)
    result: dict[str, Any] = {
        "db_path": str(db),
        "db_exists": db.exists() and db.is_file(),
        "output_dir": str(output),
        "output_exists": output.exists() and output.is_dir(),
        "output_writable": output.exists() and output.is_dir() and os.access(output, os.W_OK),
    }
    if result["db_exists"]:
        try:
            with _connection(db, read_only=True) as conn:
                result["integrity"] = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
                result["download_status_counts"] = _status_counts(conn)
        except sqlite3.Error as exc:
            result["integrity"] = f"error: {exc}"
            result["download_status_counts"] = {}
    else:
        result["integrity"] = "missing"
        result["download_status_counts"] = {}
    return result


def get_backlog_summary(db_path: str | Path) -> dict[str, int]:
    """Return lightweight backlog/queue counts from a dedicated read-only connection."""
    query = """
        SELECT
            COUNT(DISTINCT CASE WHEN status='stale' THEN rj_id END) AS stale_rjs,
            SUM(CASE WHEN status='stale' THEN 1 ELSE 0 END) AS stale_rows,
            COUNT(DISTINCT CASE WHEN status='ignored' THEN rj_id END) AS ignored_rjs,
            SUM(CASE WHEN status='ignored' THEN 1 ELSE 0 END) AS ignored_rows,
            SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued_rows,
            SUM(CASE WHEN status='paused' THEN 1 ELSE 0 END) AS paused_rows,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_rows,
            SUM(CASE WHEN status IN ('downloading','resuming') THEN 1 ELSE 0 END) AS running_rows
        FROM downloads
    """
    with _connection(db_path, read_only=True) as conn:
        if not _table_exists(conn, "downloads"):
            return {
                "stale_rjs": 0,
                "stale_rows": 0,
                "ignored_rjs": 0,
                "ignored_rows": 0,
                "queued_rows": 0,
                "paused_rows": 0,
                "failed_rows": 0,
                "running_rows": 0,
            }
        row = conn.execute(query).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def diagnose_download_failures(db_path: str | Path) -> dict[str, Any]:
    """Categorize failed/paused rows without using the application's shared connection."""
    result: dict[str, Any] = {
        "failed_total": 0,
        "failed_resumable_partial_file": 0,
        "failed_retry_from_zero": 0,
        "failed_missing_file": 0,
        "failed_missing_url_or_metadata": 0,
        "failed_complete_but_db_failed": 0,
        "paused_resumable": 0,
        "paused_missing_file": 0,
        "registered_count": 0,
        "stale_count": 0,
        "ignored_count": 0,
        "per_error_prefix": {},
        "per_root_path": {},
    }
    with _connection(db_path, read_only=True) as conn:
        if not _table_exists(conn, "downloads"):
            return result
        failed_rows = conn.execute(
            """SELECT d.*,
                      EXISTS(SELECT 1 FROM metadata_cache mc WHERE mc.rj_id=d.rj_id)
                          AS has_metadata
               FROM downloads d WHERE d.status='failed' ORDER BY d.rj_id,d.id"""
        ).fetchall()
        paused_rows = conn.execute(
            "SELECT local_path FROM downloads WHERE status='paused'"
        ).fetchall()
        counts = _status_counts(conn)

    result["failed_total"] = len(failed_rows)
    for row in failed_rows:
        local_text = str(row["local_path"] or "")
        final_path = Path(local_text) if local_text else None
        part_path = Path(local_text + ".part") if local_text else None
        final_exists = bool(final_path and final_path.is_file())
        part_exists = bool(part_path and part_path.is_file())
        file_size = 0
        try:
            if final_exists and final_path:
                file_size = final_path.stat().st_size
            elif part_exists and part_path:
                file_size = part_path.stat().st_size
        except OSError:
            final_exists = False
            part_exists = False
            file_size = 0

        total_bytes = int(row["total_bytes"] or 0)
        if (final_exists or part_exists) and file_size > 0 and (
            total_bytes <= 0 or file_size < total_bytes
        ):
            result["failed_resumable_partial_file"] += 1
        elif not final_exists and not part_exists:
            if int(row["has_metadata"] or 0):
                result["failed_retry_from_zero"] += 1
            else:
                result["failed_missing_url_or_metadata"] += 1
        elif total_bytes > 0 and file_size >= total_bytes:
            result["failed_complete_but_db_failed"] += 1
        else:
            result["failed_missing_file"] += 1

        error = str(row["error"] or "unknown")
        prefix = error[:30].split(":", 1)[0].strip() or "unknown"
        result["per_error_prefix"][prefix] = result["per_error_prefix"].get(prefix, 0) + 1
        if final_path:
            root = str(final_path.parent)
            result["per_root_path"][root] = result["per_root_path"].get(root, 0) + 1

    for row in paused_rows:
        local_text = str(row["local_path"] or "")
        final_path = Path(local_text) if local_text else None
        part_path = Path(local_text + ".part") if local_text else None
        if (final_path and final_path.is_file()) or (part_path and part_path.is_file()):
            result["paused_resumable"] += 1
        else:
            result["paused_missing_file"] += 1

    result["registered_count"] = counts.get("registered", 0)
    result["stale_count"] = counts.get("stale", 0)
    result["ignored_count"] = counts.get("ignored", 0)
    return result
