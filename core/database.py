import csv
import json
import logging
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Iterable

from core.intake_db import (
    IntakePathUpdateRequest,
    apply_path_update,
    capture_external_intake_snapshot,
)
from core.library_rebuild import (
    ACTIVE_DOWNLOAD_STATUSES,
    LibraryRebuildResult,
    LibraryScanError,
    choose_canonical_entries,
    flatten_metadata_track_titles,
    scan_library_snapshot,
)
from core.media_assets import find_local_cover
from core.models import WorkMetadata
from core.paths import app_path

# Python 3.12+ deprecates sqlite3's implicit datetime adapter.  Registering an
# explicit ISO-8601 adapter keeps database writes deterministic across versions.
sqlite3.register_adapter(datetime, lambda value: value.isoformat())

DB_FILE: Optional[Path] = None

# Cache expiry: 7 days
CACHE_TTL_HOURS = 168


class LibraryVault:
    """Manages download history, metadata cache, and download state.

    All writes are protected by a global threading.RLock to prevent
    concurrent-transaction errors from multiple threads/coroutines.
    Reads use the shared connection (check_same_thread=False) for speed.
    """

    def __init__(self, db_path: str | Path | None = None, *, read_only: bool = False):
        selected_path = db_path if db_path is not None else (DB_FILE or app_path("history.db"))
        self.db_path = str(Path(selected_path))
        self.read_only = read_only
        self._lock = threading.RLock()
        if not read_only:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if read_only:
                resolved = Path(self.db_path).expanduser().resolve(strict=True)
                self.conn = sqlite3.connect(
                    f"{resolved.as_uri()}?mode=ro",
                    uri=True,
                    check_same_thread=False,
                    isolation_level=None,
                )
            else:
                self.conn = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    isolation_level=None,
                )
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.row_factory = sqlite3.Row
        if not read_only:
            self._init_schema()

    @classmethod
    def open_read_only(cls, db_path: str | Path | None = None) -> "LibraryVault":
        """Open an existing database without creating files or changing schema."""
        return cls(db_path, read_only=True)

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "LibraryVault":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _write_conn(self):
        """Return a new write connection; read-only vaults fail closed."""
        if self.read_only:
            raise RuntimeError("LibraryVault is read-only")
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def _execute_write(self, sql: str, params=()):
        """Execute a write statement under lock with automatic commit."""
        with self._lock:
            conn = self._write_conn()
            try:
                conn.execute(sql, params)
                conn.commit()
            except sqlite3.Error as e:
                logging.error(f"DB write error: {e} sql={sql[:80]}")
                raise
            finally:
                conn.close()

    def _write(self, fn):
        """Execute fn(conn) under lock with new connection + commit."""
        with self._lock:
            conn = self._write_conn()
            try:
                result = fn(conn)
                conn.commit()
                return result
            except sqlite3.Error as e:
                logging.error(f"DB write error: {e}")
                raise
            finally:
                conn.close()

    def commit(self):
        """Thread-safe commit."""
        with self._lock:
            self.conn.commit()

    def execute_write(self, sql: str, params=()):
        """Execute a write under lock with new connection. Raises on error."""
        with self._lock:
            conn = self._write_conn()
            try:
                conn.execute(sql, params)
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                raise
            finally:
                conn.close()
    # ──────────────────────────────────────────────
    def _init_schema(self) -> None:
        conn = self.conn
        conn.execute("BEGIN")
        # ── works table (P0) ──
        conn.execute("""
                CREATE TABLE IF NOT EXISTS works (
                    rj_id TEXT PRIMARY KEY,
                    title TEXT,
                    circle TEXT,
                    downloaded_at TIMESTAMP,
                    size_bytes INTEGER DEFAULT 0,
                    local_path TEXT,
                    cover_url TEXT,
                    status TEXT DEFAULT 'completed',
                    postprocess_status TEXT DEFAULT 'unknown',
                    postprocess_error TEXT DEFAULT '',
                    postprocess_updated_at TIMESTAMP
                )
            """)

        # Migration for works
        for col_name, col_type in [
            ("size_bytes", "INTEGER DEFAULT 0"),
            ("local_path", "TEXT"),
            ("cover_url", "TEXT"),
            ("status", "TEXT DEFAULT 'completed'"),
            ("postprocess_status", "TEXT DEFAULT 'unknown'"),
            ("postprocess_error", "TEXT DEFAULT ''"),
            ("postprocess_updated_at", "TIMESTAMP"),
        ]:
            self._safe_alter(conn, "works", col_name, col_type)

        # ── metadata_cache (P1-1) ──
        conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata_cache (
                    rj_id TEXT PRIMARY KEY,
                    title TEXT,
                    circle TEXT,
                    cover_url TEXT,
                    metadata_json TEXT NOT NULL,
                    tracks_json TEXT NOT NULL,
                    fetched_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP
                )
            """)

        # ── downloads (P1-2) ──
        conn.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    rj_id TEXT NOT NULL,
                    track_title TEXT,
                    local_path TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    downloaded_bytes INTEGER DEFAULT 0,
                    total_bytes INTEGER DEFAULT 0,
                    error TEXT,
                    error_code TEXT DEFAULT '',
                    attempt_count INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 0,
                    next_retry_at TIMESTAMP,
                    last_http_status INTEGER,
                    updated_at TIMESTAMP
                )
            """)
        conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_downloads_rj
                ON downloads(rj_id)
            """)
        for col_name, col_type in [
            ("error_code", "TEXT DEFAULT ''"),
            ("attempt_count", "INTEGER DEFAULT 0"),
            ("max_attempts", "INTEGER DEFAULT 0"),
            ("next_retry_at", "TIMESTAMP"),
            ("last_http_status", "INTEGER"),
        ]:
            self._safe_alter(conn, "downloads", col_name, col_type)

        # ── library_index (P3.3) ──
        conn.execute("""
                CREATE TABLE IF NOT EXISTS library_index (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rj_id TEXT NOT NULL,
                    library_path TEXT NOT NULL,
                    work_dir TEXT NOT NULL,
                    status TEXT DEFAULT 'found',
                    size_bytes INTEGER DEFAULT 0,
                    file_count INTEGER DEFAULT 0,
                    scanned_at TIMESTAMP
                )
            """)
        try:
            conn.execute("DROP INDEX IF EXISTS idx_library_rj_path")
        except sqlite3.OperationalError:
            pass
        conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_library_rj_workdir
                ON library_index(rj_id, work_dir)
            """)

        # ── library_items (P5/P6 current work-level index) ──
        conn.execute("""
                CREATE TABLE IF NOT EXISTS library_items (
                    rj_id TEXT PRIMARY KEY,
                    folder_path TEXT NOT NULL,
                    folder_name TEXT NOT NULL,
                    total_files INTEGER DEFAULT 0,
                    total_size INTEGER DEFAULT 0,
                    audio_count INTEGER DEFAULT 0,
                    image_count INTEGER DEFAULT 0,
                    video_count INTEGER DEFAULT 0,
                    other_count INTEGER DEFAULT 0,
                    has_audio INTEGER DEFAULT 0,
                    has_cover INTEGER DEFAULT 0,
                    warnings_json TEXT DEFAULT '[]',
                    scan_run_id TEXT,
                    scanned_at TIMESTAMP
                )
            """)
        for col_name, col_type in [
            ("folder_path", "TEXT"),
            ("folder_name", "TEXT"),
            ("total_files", "INTEGER DEFAULT 0"),
            ("total_size", "INTEGER DEFAULT 0"),
            ("audio_count", "INTEGER DEFAULT 0"),
            ("image_count", "INTEGER DEFAULT 0"),
            ("video_count", "INTEGER DEFAULT 0"),
            ("other_count", "INTEGER DEFAULT 0"),
            ("has_audio", "INTEGER DEFAULT 0"),
            ("has_cover", "INTEGER DEFAULT 0"),
            ("warnings_json", "TEXT DEFAULT '[]'"),
            ("scan_run_id", "TEXT"),
            ("scanned_at", "TIMESTAMP"),
        ]:
            self._safe_alter(conn, "library_items", col_name, col_type)
        conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_library_items_scan_run
                ON library_items(scan_run_id)
            """)

        # User-confirmed cloud backup ledger. This does not imply that ARSM
        # uploaded or independently verified the remote copy. It survives
        # filesystem rescans so cloud-only works stay visible and protected.
        conn.execute("""
                CREATE TABLE IF NOT EXISTS cloud_archives (
                    rj_id TEXT PRIMARY KEY,
                    provider TEXT DEFAULT '',
                    remote_path TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    circle TEXT DEFAULT '',
                    original_local_path TEXT DEFAULT '',
                    total_files INTEGER DEFAULT 0,
                    total_size INTEGER DEFAULT 0,
                    audio_count INTEGER DEFAULT 0,
                    image_count INTEGER DEFAULT 0,
                    video_count INTEGER DEFAULT 0,
                    other_count INTEGER DEFAULT 0,
                    has_cover INTEGER DEFAULT 0,
                    cover_cache_path TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '{}',
                    confirmation_source TEXT DEFAULT 'user',
                    archived_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)
        self._safe_alter(conn, "cloud_archives", "cover_cache_path", "TEXT DEFAULT ''")
        self._safe_alter(conn, "cloud_archives", "metadata_json", "TEXT DEFAULT '{}'")
        conn.commit()

    def _safe_alter(self, conn, table: str, col_name: str, col_type: str) -> None:
        try:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"
            )
            logging.info(f"DB migration: added {col_name} to {table}")
        except sqlite3.OperationalError:
            pass

    # ──────────────────────────────────────────────
    #  Metadata cache (P1-1)
    # ──────────────────────────────────────────────
    def get_metadata_cache(self, rj_id: str, *,
                           allow_stale: bool = False) -> Optional[Dict]:
        """Return cached metadata.

        Fresh metadata is returned by default. ``allow_stale`` is reserved for
        recovery paths such as resuming an interrupted download: an expired
        cache is still safer than making an otherwise resumable local ``.part``
        file unusable while the metadata service is offline.
        """
        try:
            row = self.conn.execute(
                "SELECT * FROM metadata_cache WHERE rj_id = ?", (rj_id,)
            ).fetchone()
            if not row:
                return None
            fetched = datetime.fromisoformat(row["fetched_at"])
            is_stale = datetime.now() - fetched > timedelta(
                hours=CACHE_TTL_HOURS)
            if is_stale and not allow_stale:
                return None
            return {
                "rj_id": row["rj_id"],
                "title": row["title"],
                "circle": row["circle"],
                "cover_url": row["cover_url"],
                "metadata_json": row["metadata_json"],
                "tracks_json": row["tracks_json"],
                "fetched_at": row["fetched_at"],
                "is_stale": is_stale,
            }
        except Exception as e:
            logging.warning(f"Metadata cache read error: {e}")
            return None

    def get_recovery_metadata_ids(self) -> set[str]:
        """List usable cache keys without loading metadata/track JSON blobs."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT rj_id, fetched_at FROM metadata_cache"
            ).fetchall()
        result = set()
        for row in rows:
            try:
                # Recovery allows expired entries, but malformed dates have
                # always been rejected by get_metadata_cache.
                datetime.now() - datetime.fromisoformat(row["fetched_at"])
            except (TypeError, ValueError):
                continue
            result.add(str(row["rj_id"]))
        return result

    def set_metadata_cache(self, rj_id: str, title: str, circle: str,
                           cover_url: str, metadata_raw: dict,
                           tracks_raw: list) -> None:
        """Store metadata and tracks in cache. Raises on write failure."""
        import json as _json
        now = datetime.now()
        self._execute_write(
            """INSERT OR REPLACE INTO metadata_cache
               (rj_id, title, circle, cover_url, metadata_json,
                tracks_json, fetched_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rj_id, title, circle, cover_url,
             _json.dumps(metadata_raw, ensure_ascii=False),
             _json.dumps(tracks_raw, ensure_ascii=False),
             now, now))

    def upsert_work_metadata(self, rj_id: str, title: str, circle: str,
                             cover_url: str, metadata_raw: dict) -> None:
        """Refresh album metadata without replacing cached track data or state.

        The bulk metadata backfill uses this narrower write path so it cannot
        reset download status, local paths, post-processing state, or an
        existing ``tracks_json`` payload.
        """
        import json as _json
        now = datetime.now()
        metadata_json = _json.dumps(metadata_raw, ensure_ascii=False)

        def write(conn):
            conn.execute(
                """INSERT INTO metadata_cache
                   (rj_id, title, circle, cover_url, metadata_json,
                    tracks_json, fetched_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, '[]', ?, ?)
                   ON CONFLICT(rj_id) DO UPDATE SET
                     title=excluded.title,
                     circle=excluded.circle,
                     cover_url=excluded.cover_url,
                     metadata_json=excluded.metadata_json,
                     fetched_at=excluded.fetched_at,
                     updated_at=excluded.updated_at""",
                (rj_id, title, circle, cover_url, metadata_json, now, now),
            )
            conn.execute(
                """UPDATE works
                   SET title=?, circle=?, cover_url=?
                   WHERE rj_id=?""",
                (title, circle, cover_url, rj_id),
            )
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='cloud_archives'"
            ).fetchone():
                conn.execute(
                    """UPDATE cloud_archives
                       SET title=?, circle=?, metadata_json=?, updated_at=?
                       WHERE rj_id=?""",
                    (title, circle, metadata_json, now, rj_id),
                )

        self._write(write)

    def invalidate_cache(self, rj_id: str) -> None:
        """Force next lookup to fetch fresh data. Raises on failure."""
        self._execute_write(
            "DELETE FROM metadata_cache WHERE rj_id = ?", (rj_id,))

    # ──────────────────────────────────────────────
    #  Download state (P1-2)
    # ──────────────────────────────────────────────
    _DOWNLOAD_UPSERT_SQL = """INSERT INTO downloads
               (id, rj_id, track_title, local_path, status,
                downloaded_bytes, total_bytes, error, error_code,
                attempt_count, max_attempts, next_retry_at, last_http_status,
                updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 rj_id=excluded.rj_id,
                 track_title=excluded.track_title,
                 local_path=excluded.local_path,
                 status=excluded.status,
                 downloaded_bytes=excluded.downloaded_bytes,
                 total_bytes=excluded.total_bytes,
                 error=excluded.error,
                 error_code=excluded.error_code,
                 attempt_count=excluded.attempt_count,
                 max_attempts=excluded.max_attempts,
                 next_retry_at=excluded.next_retry_at,
                 last_http_status=excluded.last_http_status,
                 updated_at=excluded.updated_at"""

    @staticmethod
    def _download_upsert_params(item: dict, updated_at) -> tuple:
        return (
            item["download_id"], item["rj_id"], item["track_title"],
            item["local_path"], item["status"],
            int(item.get("downloaded_bytes", 0) or 0),
            int(item.get("total_bytes", 0) or 0), item.get("error", ""),
            item.get("error_code", ""),
            max(0, int(item.get("attempt_count", 0) or 0)),
            max(0, int(item.get("max_attempts", 0) or 0)),
            item.get("next_retry_at"), item.get("last_http_status"), updated_at,
        )

    def upsert_download_batch(self, items) -> None:
        """Write several file states in one transaction."""
        items = list(items)
        if not items:
            return
        updated_at = datetime.now()
        params = [self._download_upsert_params(item, updated_at) for item in items]

        def write(conn):
            conn.executemany(self._DOWNLOAD_UPSERT_SQL, params)

        self._write(write)

    def upsert_download(self, download_id: str, rj_id: str,
                        track_title: str, local_path: str,
                        status: str, downloaded_bytes: int = 0,
                        total_bytes: int = 0, error: str = "", *,
                        error_code: str = "", attempt_count: int = 0,
                        max_attempts: int = 0, next_retry_at=None,
                        last_http_status: int | None = None) -> None:
        """Write download state. Raises on failure (RC7.1)."""
        self.upsert_download_batch([{
            "download_id": download_id, "rj_id": rj_id,
            "track_title": track_title, "local_path": local_path,
            "status": status, "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes, "error": error,
            "error_code": error_code, "attempt_count": attempt_count,
            "max_attempts": max_attempts, "next_retry_at": next_retry_at,
            "last_http_status": last_http_status,
        }])

    def get_downloads_by_rj(self, rj_id: str) -> List[sqlite3.Row]:
        try:
            return self.conn.execute(
                "SELECT * FROM downloads WHERE rj_id = ? ORDER BY id",
                (rj_id,)
            ).fetchall()
        except Exception as e:
            logging.error(f"Download state read error: {e}")
            return []

    def get_pending_downloads(self) -> List[sqlite3.Row]:
        """Get downloads that are eligible for startup restore.

        Soft-close statuses such as stale/ignored are intentionally excluded.
        Failed downloads are handled by explicit resume/retry flows, not startup restore.
        """
        try:
            return self.conn.execute(
                """SELECT * FROM downloads
                   WHERE status IN ('queued', 'paused', 'downloading', 'resuming')
                   ORDER BY rj_id, id"""
            ).fetchall()
        except Exception as e:
            logging.error(f"Pending downloads read error: {e}")
            return []

    def get_work(self, rj_id: str) -> Optional[sqlite3.Row]:
        """Return the canonical works row for an RJ id, if present."""
        try:
            return self.conn.execute(
                "SELECT * FROM works WHERE rj_id = ?", (rj_id,)
            ).fetchone()
        except Exception as e:
            logging.error(f"get_work error for {rj_id}: {e}")
            return None

    def get_works_status(self, rj_id: str) -> str:
        """Return works.status for a given rj_id, or empty string if missing."""
        try:
            row = self.conn.execute(
                "SELECT status FROM works WHERE rj_id = ?", (rj_id,)
            ).fetchone()
            return row["status"] if row else ""
        except Exception as e:
            logging.error(f"get_works_status error for {rj_id}: {e}")
            return ""

    def get_rj_state_batch(self, rj_ids: Iterable[str]) -> dict[str, dict[str, object]]:
        """Read local/cloud library and queue states for many RJ ids."""
        canonical = tuple(dict.fromkeys(str(value).upper() for value in rj_ids if value))
        result = {
            rj_id: {
                "in_library": False, "cloud_archived": False,
                "statuses": set(), "download_statuses": set(),
            }
            for rj_id in canonical
        }
        if not canonical:
            return result
        placeholders = ",".join("?" for _ in canonical)
        with self._lock:
            for row in self.conn.execute(
                f"SELECT DISTINCT rj_id, 0 AS cloud_archived FROM library_index "
                f"WHERE rj_id IN ({placeholders}) "
                "AND LOWER(COALESCE(status, '')) != 'missing' "
                "UNION ALL SELECT rj_id, 1 AS cloud_archived FROM cloud_archives "
                f"WHERE rj_id IN ({placeholders})",
                (*canonical, *canonical),
            ).fetchall():
                item = result[str(row["rj_id"]).upper()]
                item["in_library"] = True
                item["cloud_archived"] = (
                    bool(item["cloud_archived"]) or bool(row["cloud_archived"])
                )
            for row in self.conn.execute(
                f"SELECT rj_id, status FROM downloads "
                f"WHERE rj_id IN ({placeholders})",
                canonical,
            ).fetchall():
                item = result[str(row["rj_id"]).upper()]
                item["statuses"].add(row["status"])
                item["download_statuses"].add(row["status"])
            for row in self.conn.execute(
                f"SELECT rj_id, status FROM works WHERE rj_id IN ({placeholders})",
                canonical,
            ).fetchall():
                result[str(row["rj_id"]).upper()]["statuses"].add(row["status"])
        return result

    def get_pending_rj_ids(self) -> set:
        """Return RJ ids that should appear in the active download queue.

        Soft-close statuses such as stale/ignored are intentionally excluded.
        """
        try:
            rows = self.conn.execute(
                """SELECT DISTINCT rj_id FROM downloads
                   WHERE status IN ('queued','paused','downloading','failed','resuming')"""
            ).fetchall()
            return {row["rj_id"] for row in rows}
        except Exception as e:
            logging.error(f"get_pending_rj_ids error: {e}")
            return set()

    def get_downloads_summary(self, rj_id: str) -> dict:
        """Return {status: count} for all downloads of this rj_id."""
        try:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) as cnt FROM downloads "
                "WHERE rj_id = ? GROUP BY status", (rj_id,)
            ).fetchall()
            return {row["status"]: row["cnt"] for row in rows}
        except Exception as e:
            logging.error(f"get_downloads_summary error for {rj_id}: {e}")
            return {}

    def clear_terminal_downloads(self, rj_id: str) -> None:
        """Remove completed/failed/registered downloads. Raises on failure."""
        self._execute_write(
            """DELETE FROM downloads
               WHERE rj_id = ? AND status IN ('completed','registered','failed')""",
            (rj_id,))

    # ──────────────────────────────────────────────
    #  Works library (P0, unchanged logic)
    # ──────────────────────────────────────────────
    def register(self, meta: WorkMetadata, size: int, path: Path,
                 status: str = 'completed', *,
                 postprocess_status: str | None = None) -> None:
        """Register a work. Raises on failure (RC7.1)."""
        self._execute_write(
            """INSERT INTO works
               (rj_id, title, circle, downloaded_at, size_bytes,
                local_path, cover_url, status, postprocess_status,
                postprocess_error, postprocess_updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)
               ON CONFLICT(rj_id) DO UPDATE SET
                 title=excluded.title,
                 circle=excluded.circle,
                 downloaded_at=excluded.downloaded_at,
                 size_bytes=excluded.size_bytes,
                 local_path=excluded.local_path,
                 cover_url=excluded.cover_url,
                 status=excluded.status,
                 postprocess_status=excluded.postprocess_status,
                 postprocess_error='',
                 postprocess_updated_at=excluded.postprocess_updated_at""",
            (meta.rj_id, meta.title, meta.circle,
             datetime.now(), size, str(path), meta.cover_url, status,
             postprocess_status or ("pending" if status == "completed" else "unknown"),
             datetime.now()))

    def set_postprocess_status(self, rj_id: str, status: str,
                               error: str = "") -> None:
        """Persist post-download processing independently from download success."""
        self._execute_write(
            """UPDATE works
               SET postprocess_status=?, postprocess_error=?,
                   postprocess_updated_at=?
               WHERE rj_id=?""",
            (status, error, datetime.now(), rj_id),
        )

    def get_pending_postprocess_works(self) -> list[sqlite3.Row]:
        """Return crash-interrupted or newly pending post-processing work."""
        try:
            return self.conn.execute(
                """SELECT w.*, mc.metadata_json
                   FROM works w
                   LEFT JOIN metadata_cache mc ON mc.rj_id=w.rj_id
                   WHERE w.status='completed'
                     AND w.postprocess_status IN ('pending','running')
                   ORDER BY w.postprocess_updated_at, w.rj_id"""
            ).fetchall()
        except sqlite3.Error as exc:
            logging.error("get_pending_postprocess_works error: %s", exc)
            return []

    def get_postprocess_diagnostics(self, limit: int = 200) -> dict:
        """Return a bounded, read-only report for incomplete post-processing."""
        try:
            rows = self.conn.execute(
                """SELECT rj_id, status, postprocess_status, postprocess_error,
                          postprocess_updated_at, local_path
                   FROM works
                   WHERE COALESCE(postprocess_status,'unknown') NOT IN ('completed','not_required')
                   ORDER BY postprocess_updated_at DESC, rj_id
                   LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
            counts = {
                str(row["postprocess_status"] or "unknown"): int(row["count"])
                for row in self.conn.execute(
                    """SELECT COALESCE(postprocess_status,'unknown') AS postprocess_status,
                              COUNT(*) AS count
                       FROM works GROUP BY COALESCE(postprocess_status,'unknown')"""
                ).fetchall()
            }
            return {"counts": counts, "items": [dict(row) for row in rows]}
        except sqlite3.Error as exc:
            logging.error("get_postprocess_diagnostics error: %s", exc)
            return {"counts": {}, "items": [], "error": str(exc)}

    def get_summary(self) -> Tuple[int, int]:
        try:
            cnt = self.conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
            sz = self.conn.execute(
                "SELECT SUM(size_bytes) FROM works"
            ).fetchone()[0] or 0
            return cnt, sz
        except sqlite3.Error as e:
            logging.error(f"Database get_summary error: {e}")
            return 0, 0

    def search(self, query: str = "", offset: int = 0,
               limit: int = 0, status_filter: str = "") -> List[sqlite3.Row]:
        """Search works with optional pagination and status filter.

        - limit=0 means no limit (return all)
        - status_filter='' means all statuses
        """
        try:
            conditions = []
            params = []
            if query:
                q = f"%{query}%"
                conditions.append(
                    "(title LIKE ? OR rj_id LIKE ? OR circle LIKE ?)")
                params.extend([q, q, q])
            if status_filter:
                conditions.append("status = ?")
                params.append(status_filter)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            sql = f"SELECT * FROM works {where} ORDER BY downloaded_at DESC"
            if limit > 0:
                sql += f" LIMIT {limit} OFFSET {offset}"

            return self.conn.execute(sql, params).fetchall()
        except sqlite3.Error as e:
            logging.error(f"Database search error: {e}")
            return []

    def count_library_by_status(self) -> dict:
        """Return counts of works grouped by status.

        Includes all statuses: completed, partial, missing,
        external, verified, indexed, metadata_failed, prepared.
        """
        try:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) as cnt FROM works GROUP BY status"
            ).fetchall()
            counts = {row["status"]: row["cnt"] for row in rows}
            total = sum(counts.values())
            counts["__total__"] = total
            return counts
        except sqlite3.Error as e:
            logging.error(f"count_library_by_status error: {e}")
            return {"__total__": 0}

    # ──────────────────────────────────────────────
    #  Library index (P3.3)
    # ──────────────────────────────────────────────
    def upsert_library_entry(self, rj_id: str, library_path: str,
                             work_dir: str, size_bytes: int = 0,
                             file_count: int = 0, status: str = 'found'):
        """Upsert library index entry. Raises on failure (RC7.1)."""
        self._execute_write(
            """INSERT OR REPLACE INTO library_index
               (rj_id, library_path, work_dir, status,
                size_bytes, file_count, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rj_id, library_path, work_dir, status,
             size_bytes, file_count, datetime.now()))

    def find_in_library(self, rj_id: str) -> List[sqlite3.Row]:
        """Check whether an RJ exists locally or in the cloud archive ledger."""
        try:
            return self.conn.execute(
                """SELECT rj_id, library_path, work_dir, status, size_bytes,
                          file_count, scanned_at
                   FROM library_index
                   WHERE rj_id = ? AND status != 'missing'
                   UNION ALL
                   SELECT ca.rj_id, 'cloud_archive',
                          CASE WHEN ca.remote_path != '' THEN ca.remote_path
                               ELSE '云端归档' END,
                          'archived', ca.total_size, ca.total_files, ca.archived_at
                   FROM cloud_archives ca
                   WHERE ca.rj_id = ?
                     AND NOT EXISTS (
                         SELECT 1 FROM library_index li
                         WHERE li.rj_id=ca.rj_id AND li.status != 'missing'
                     )""",
                (rj_id, rj_id)
            ).fetchall()
        except Exception as e:
            logging.error(f"Library lookup error: {e}")
            return []

    def is_cloud_archived(self, rj_id: str) -> bool:
        """Return whether an RJ has a user-confirmed cloud archive record."""
        try:
            return self.conn.execute(
                "SELECT 1 FROM cloud_archives WHERE rj_id=?", (rj_id,)
            ).fetchone() is not None
        except sqlite3.Error as exc:
            logging.error("is_cloud_archived error for %s: %s", rj_id, exc)
            return False

    def mark_cloud_archives(self, rj_ids: Iterable[str], *, provider: str = "",
                            remote_path: str = "", note: str = "") -> list[dict]:
        """Record user-confirmed cloud backups without deleting local data.

        Only complete, non-active library items are accepted.  The record is a
        durable user assertion, not an independent verification of the remote.
        """
        canonical: list[str] = []
        for raw in rj_ids:
            normalized = self.normalize_rj_id(str(raw or ""))
            if not normalized:
                raise ValueError(f"RJ 号格式不正确: {raw}")
            if normalized not in canonical:
                canonical.append(normalized)
        if not canonical:
            raise ValueError("至少需要一个 RJ 号")
        now = datetime.now()

        def _mark(conn):
            recorded: list[dict] = []
            for rj_id in canonical:
                row = conn.execute(
                    """SELECT li.*, w.title AS work_title, w.circle AS work_circle,
                              w.status AS work_status, w.postprocess_status,
                              w.local_path AS work_local_path,
                              mc.title AS metadata_title, mc.circle AS metadata_circle,
                              mc.metadata_json AS metadata_json
                       FROM library_items li
                       LEFT JOIN works w ON w.rj_id=li.rj_id
                       LEFT JOIN metadata_cache mc ON mc.rj_id=li.rj_id
                       WHERE li.rj_id=?""",
                    (rj_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"{rj_id} 不在当前资源库中，未登记")
                active = conn.execute(
                    """SELECT COUNT(*) FROM downloads
                       WHERE rj_id=? AND status NOT IN
                       ('completed','registered','stale','ignored')""",
                    (rj_id,),
                ).fetchone()[0]
                if active:
                    raise ValueError(f"{rj_id} 仍有未完成或异常文件，未登记")
                work_status = str(row["work_status"] or "")
                if work_status not in {"completed", "verified", "external", "indexed"}:
                    raise ValueError(f"{rj_id} 状态为 {work_status or 'unknown'}，未登记")
                postprocess_status = str(row["postprocess_status"] or "unknown")
                if (work_status == "completed" and
                        postprocess_status not in {"completed", "not_required"}):
                    raise ValueError(f"{rj_id} 后处理尚未完成，未登记")
                title = str(
                    row["metadata_title"] or row["work_title"] or
                    row["folder_name"] or rj_id
                )
                circle = str(row["metadata_circle"] or row["work_circle"] or "")
                original_path = str(row["folder_path"] or row["work_local_path"] or "")
                cover_cache_path = ""
                cover = find_local_cover(original_path) if original_path else None
                if cover is not None:
                    try:
                        cover_dir = Path(self.db_path).parent / "cloud_archive_covers"
                        cover_dir.mkdir(parents=True, exist_ok=True)
                        cached_cover = cover_dir / f"{rj_id}{cover.suffix.casefold()}"
                        shutil.copy2(cover, cached_cover)
                        cover_cache_path = str(cached_cover)
                    except OSError as exc:
                        logging.warning("Cloud archive cover copy failed for %s: %s", rj_id, exc)
                metadata_json = str(row["metadata_json"] or "{}")
                values = (
                    rj_id, str(provider or ""), str(remote_path or ""),
                    str(note or ""), title, circle, original_path,
                    int(row["total_files"] or 0), int(row["total_size"] or 0),
                    int(row["audio_count"] or 0), int(row["image_count"] or 0),
                    int(row["video_count"] or 0), int(row["other_count"] or 0),
                    int(row["has_cover"] or 0), cover_cache_path,
                    metadata_json, "user", now, now,
                )
                conn.execute(
                    """INSERT INTO cloud_archives
                       (rj_id, provider, remote_path, note, title, circle,
                        original_local_path, total_files, total_size, audio_count,
                        image_count, video_count, other_count, has_cover,
                        cover_cache_path, metadata_json, confirmation_source,
                        archived_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(rj_id) DO UPDATE SET
                         provider=excluded.provider,
                         remote_path=excluded.remote_path,
                         note=excluded.note,
                         title=excluded.title,
                         circle=excluded.circle,
                         original_local_path=excluded.original_local_path,
                         total_files=excluded.total_files,
                         total_size=excluded.total_size,
                         audio_count=excluded.audio_count,
                         image_count=excluded.image_count,
                         video_count=excluded.video_count,
                         other_count=excluded.other_count,
                         has_cover=excluded.has_cover,
                         cover_cache_path=CASE
                           WHEN excluded.cover_cache_path != '' THEN excluded.cover_cache_path
                           ELSE cloud_archives.cover_cache_path END,
                         metadata_json=CASE
                           WHEN excluded.metadata_json NOT IN ('', '{}') THEN excluded.metadata_json
                           ELSE cloud_archives.metadata_json END,
                         confirmation_source=excluded.confirmation_source,
                         updated_at=excluded.updated_at""",
                    values,
                )
                recorded.append({"rj_id": rj_id, "title": title,
                                 "original_local_path": original_path})
            return recorded

        return self._write(_mark)

    def list_cloud_archives(self) -> list[dict]:
        """Return a stable snapshot of user-confirmed cloud archive records."""
        try:
            with self._lock:
                rows = self.conn.execute(
                    "SELECT * FROM cloud_archives ORDER BY rj_id"
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logging.error("list_cloud_archives error: %s", exc)
            return []

    def export_cloud_archives_csv(self, destination: str | Path) -> Path:
        """Export the durable cloud ledger as a portable UTF-8 CSV backup."""
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self.list_cloud_archives()
        fieldnames = [
            "rj_id", "title", "circle", "provider", "remote_path", "note",
            "original_local_path", "total_files", "total_size", "audio_count",
            "image_count", "video_count", "other_count", "has_cover",
            "cover_cache_path", "metadata_json", "confirmation_source",
            "archived_at", "updated_at",
        ]
        with target.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})
        return target

    @staticmethod
    def normalize_rj_id(raw: str) -> str:
        """Normalize a directory name to 'RJxxxxxxxx' format (8 digits)."""
        import re as _re
        m = _re.search(r'(?:RJ)?(\d{6,8})', raw, _re.IGNORECASE)
        if m:
            return f"RJ{int(m.group(1)):08d}"
        return ""

    def scan_library_paths(self, paths: List[str]) -> int:
        """Refresh only ``library_index`` from one complete filesystem snapshot."""
        snapshot = scan_library_snapshot(paths)

        def _replace_index(conn):
            conn.execute("DELETE FROM library_index")
            conn.executemany(
                """INSERT INTO library_index
                   (rj_id, library_path, work_dir, status, size_bytes,
                    file_count, scanned_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [entry.to_library_index_row(snapshot.scanned_at)
                 for entry in snapshot.entries],
            )

        self._write(_replace_index)
        return snapshot.unique_rj_count

    @staticmethod
    def _path_is_under(path_value: str, roots: Iterable[str]) -> bool:
        if not path_value:
            return False
        try:
            path = Path(path_value).expanduser().resolve(strict=False)
            return any(path == Path(root).resolve(strict=False) or
                       Path(root).resolve(strict=False) in path.parents
                       for root in roots)
        except (OSError, RuntimeError):
            return False

    def rebuild_library(self, paths: List[str]) -> dict:
        """Atomically replace library indexes from a complete scan snapshot.

        Filesystem scanning happens before the SQLite transaction.  Any scan or
        write failure therefore leaves the previous indexes untouched.  Existing
        works with active/resumable downloads are never rewritten.
        """
        try:
            snapshot = scan_library_snapshot(paths)
        except LibraryScanError as exc:
            logging.error("Library snapshot failed: %s", exc)
            return LibraryRebuildResult(
                success=False, errors=1, error=str(exc)
            ).as_dict()

        disappeared = [
            entry.work_dir for entry in snapshot.entries
            if not Path(entry.work_dir).is_dir()
        ]
        if disappeared:
            return LibraryRebuildResult(
                success=False,
                run_id=snapshot.run_id,
                found=snapshot.unique_rj_count,
                entries=len(snapshot.entries),
                errors=1,
                error=f"scan_changed:{disappeared[0]}",
            ).as_dict()

        with self._lock:
            preferred: dict[str, list[str]] = {}
            for row in self.conn.execute(
                "SELECT rj_id, local_path FROM works WHERE local_path IS NOT NULL"
            ).fetchall():
                preferred.setdefault(row["rj_id"], []).append(row["local_path"])
            for row in self.conn.execute(
                "SELECT rj_id, folder_path FROM library_items"
            ).fetchall():
                if row["folder_path"]:
                    preferred.setdefault(row["rj_id"], []).append(row["folder_path"])
        canonical = choose_canonical_entries(snapshot, preferred)
        result = LibraryRebuildResult(
            success=True,
            run_id=snapshot.run_id,
            found=snapshot.unique_rj_count,
            entries=len(snapshot.entries),
            warnings=len(snapshot.warnings) + sum(
                len(entry.warnings) for entry in snapshot.entries
            ),
            snapshot=snapshot,
        )

        def _replace(conn):
            old_keys = {
                (row["rj_id"], str(row["work_dir"]))
                for row in conn.execute(
                    "SELECT rj_id, work_dir FROM library_index"
                ).fetchall()
            }
            new_keys = {(entry.rj_id, entry.work_dir) for entry in snapshot.entries}
            result.removed_index = len(old_keys - new_keys)

            active_rj = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT rj_id FROM downloads WHERE status IN (?,?,?,?,?)",
                    tuple(sorted(ACTIVE_DOWNLOAD_STATUSES)),
                ).fetchall()
            }
            existing_works = {
                row["rj_id"]: dict(row)
                for row in conn.execute(
                    "SELECT rj_id, local_path, status FROM works"
                ).fetchall()
            }

            conn.execute("DELETE FROM library_index")
            conn.executemany(
                """INSERT INTO library_index
                   (rj_id, library_path, work_dir, status, size_bytes,
                    file_count, scanned_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [entry.to_library_index_row(snapshot.scanned_at)
                 for entry in snapshot.entries],
            )
            conn.execute("DELETE FROM library_items")
            conn.executemany(
                """INSERT INTO library_items
                   (rj_id, folder_path, folder_name, total_files, total_size,
                    audio_count, image_count, video_count, other_count,
                    has_audio, has_cover, warnings_json, scan_run_id, scanned_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [entry.to_library_item_row(snapshot.run_id, snapshot.scanned_at)
                 for entry in canonical.values()],
            )
            conn.execute(
                """INSERT INTO library_items
                   (rj_id, folder_path, folder_name, total_files, total_size,
                    audio_count, image_count, video_count, other_count,
                    has_audio, has_cover, warnings_json, scan_run_id, scanned_at)
                   SELECT ca.rj_id, '',
                          COALESCE(NULLIF(ca.title, ''), ca.rj_id),
                          ca.total_files, ca.total_size, ca.audio_count,
                          ca.image_count, ca.video_count, ca.other_count,
                          CASE WHEN ca.audio_count > 0 THEN 1 ELSE 0 END,
                          ca.has_cover, '[]', ?, ca.updated_at
                   FROM cloud_archives ca
                   WHERE NOT EXISTS (
                       SELECT 1 FROM library_items li WHERE li.rj_id=ca.rj_id
                   )""",
                (snapshot.run_id,),
            )

            for rj_id, entry in canonical.items():
                existing = existing_works.get(rj_id)
                if existing is None:
                    conn.execute(
                        """INSERT INTO works
                           (rj_id, title, circle, downloaded_at, size_bytes,
                            local_path, status)
                           VALUES (?, ?, '', ?, ?, ?, 'external')""",
                        (rj_id, rj_id, snapshot.scanned_at,
                         entry.total_size, entry.work_dir),
                    )
                    result.indexed += 1
                    continue
                if rj_id in active_rj:
                    continue
                status = str(existing.get("status") or "")
                current_path = str(existing.get("local_path") or "")
                if status in {"external", "indexed", "prepared", "missing"}:
                    conn.execute(
                        """UPDATE works SET local_path=?, size_bytes=?, status='indexed'
                           WHERE rj_id=?""",
                        (entry.work_dir, entry.total_size, rj_id),
                    )
                    result.updated += 1
                elif status == "verified":
                    conn.execute(
                        "UPDATE works SET local_path=?, size_bytes=? WHERE rj_id=?",
                        (entry.work_dir, entry.total_size, rj_id),
                    )
                    result.updated += 1
                elif current_path and Path(current_path) == Path(entry.work_dir):
                    conn.execute(
                        "UPDATE works SET size_bytes=? WHERE rj_id=?",
                        (entry.total_size, rj_id),
                    )

            scanned_rj = set(canonical)
            for rj_id, existing in existing_works.items():
                if rj_id in scanned_rj or rj_id in active_rj:
                    continue
                if str(existing.get("status") or "") not in {
                    "external", "indexed", "prepared", "missing", "verified"
                }:
                    continue
                if self._path_is_under(str(existing.get("local_path") or ""), snapshot.roots):
                    conn.execute(
                        "UPDATE works SET status='missing' WHERE rj_id=?",
                        (rj_id,),
                    )
                    result.missing += 1

        try:
            self._write(_replace)
        except Exception as exc:
            logging.error("Library rebuild transaction failed: %s", exc)
            result.success = False
            result.indexed = 0
            result.updated = 0
            result.missing = 0
            result.removed_index = 0
            result.errors = 1
            result.error = str(exc)
        return result.as_dict()

    def enrich_external_metadata(self, rj_id: str, meta_raw: dict,
                                  cover_url: str, title: str, circle: str):
        """Update works table. Raises on failure (RC7.1)."""
        self._execute_write(
            """UPDATE works SET title=?, circle=?, cover_url=?, status='external'
               WHERE rj_id=? AND status IN ('external','indexed','prepared')""",
            (title, circle, cover_url, rj_id))

    def verify_library_item(self, rj_id: str, work_dir: str,
                            metadata_tracks: list) -> str:
        """Compare recursively nested metadata tracks with local files."""
        directory = Path(work_dir)
        result_status = "missing"

        def _verify(conn):
            nonlocal result_status
            if not directory.exists():
                conn.execute(
                    "UPDATE works SET status='missing' WHERE rj_id=? AND local_path=?",
                    (rj_id, work_dir),
                )
                result_status = "missing"
                return

            local_files = [path for path in directory.rglob("*") if path.is_file()]
            if any(path.name.casefold().endswith(".part") for path in local_files):
                conn.execute(
                    "UPDATE works SET status='partial' WHERE rj_id=? AND local_path=?",
                    (rj_id, work_dir),
                )
                result_status = "partial"
                return

            local_names = {path.name.casefold() for path in local_files}
            local_stems = {path.stem.casefold() for path in local_files}
            missing_count = 0
            for title in flatten_metadata_track_titles(metadata_tracks):
                name = Path(title).name.casefold()
                stem = Path(title).stem.casefold()
                if name not in local_names and stem not in local_stems:
                    missing_count += 1

            result_status = "partial" if missing_count else "verified"
            conn.execute(
                "UPDATE works SET status=? WHERE rj_id=? AND local_path=?",
                (result_status, rj_id, work_dir),
            )

        self._write(_verify)
        return result_status

    def get_safe_migratable_works(self) -> list:
        """Return completed/verified works with no active or resumable DB rows.

        Each item: {rj_id, title, local_path, status, size_bytes}
        """
        try:
            rows = self.conn.execute(
                """SELECT w.rj_id, w.title, w.local_path, w.status,
                          COALESCE(w.size_bytes, 0) as size_bytes
                   FROM works w
                   WHERE w.status IN ('completed', 'verified')
                   AND NOT EXISTS (
                     SELECT 1 FROM downloads d
                     WHERE d.rj_id = w.rj_id
                     AND d.status IN ('queued','paused','downloading','failed','resuming')
                   )
                   ORDER BY w.rj_id"""
            ).fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logging.error(f"get_safe_migratable_works error: {e}")
            return []

    def get_external_intake_snapshot(self, rj_id: str) -> dict:
        """Return one read-only, JSON-serializable intake database snapshot."""
        with self._lock:
            return capture_external_intake_snapshot(self.conn, rj_id)

    def get_external_intake_snapshots(self, rj_ids: Iterable[str]) -> dict[str, dict]:
        """Return deduplicated snapshots without exposing the SQLite connection."""
        snapshots: dict[str, dict] = {}
        with self._lock:
            for raw_rj_id in rj_ids:
                rj_id = str(raw_rj_id or "").strip().upper()
                if rj_id and rj_id not in snapshots:
                    snapshots[rj_id] = capture_external_intake_snapshot(self.conn, rj_id)
        return snapshots

    def update_external_intake_paths(
        self,
        rj_id: str,
        source_path: str,
        target_path: str,
        *,
        expected_preimage_token: str = "",
        ensure_library_index: bool = True,
        file_path_mappings: dict[str, str] | None = None,
    ) -> dict:
        """Atomically update matching DB path references for one work.

        The transaction never changes a row merely by RJ id: the stored path
        must match ``source_path``.  This protects the primary record when a
        duplicate RJ directory is being reviewed or quarantined.
        """
        request = IntakePathUpdateRequest(
            rj_id=str(rj_id or "").strip().upper(),
            source_path=str(source_path or "").strip(),
            target_path=str(target_path or "").strip(),
            expected_preimage_token=expected_preimage_token,
            ensure_library_index=ensure_library_index,
            file_path_mappings=dict(file_path_mappings or {}),
        )
        if self.read_only:
            return {
                "success": False,
                "updated": 0,
                "error_code": "read_only_vault",
                "error": "LibraryVault is read-only",
                "rj_id": request.rj_id,
                "source_path": request.source_path,
                "target_path": request.target_path,
            }

        with self._lock:
            conn = self._write_conn()
            preimage: dict = {}
            try:
                conn.execute("BEGIN IMMEDIATE")
                preimage = capture_external_intake_snapshot(conn, request.rj_id)
                result = apply_path_update(conn, request, preimage)
                if not result.success:
                    conn.rollback()
                    return result.to_dict()
                conn.commit()
                return result.to_dict()
            except sqlite3.Error as exc:
                conn.rollback()
                logging.error(
                    "external intake path transaction failed for %s: %s",
                    request.rj_id,
                    exc,
                )
                return {
                    "success": False,
                    "updated": 0,
                    "updated_rows": {},
                    "error_code": "sqlite_error",
                    "error": str(exc),
                    "rj_id": request.rj_id,
                    "source_path": request.source_path,
                    "target_path": request.target_path,
                    "preimage": preimage,
                    "postimage": {},
                    "preimage_token": str(preimage.get("snapshot_token", "")),
                    "postimage_token": "",
                }
            finally:
                conn.close()

    def move_work_to_path(self, rj_id: str, old_path: str,
                          new_path: str) -> dict:
        """Compatibility wrapper for the unified path-reference transaction."""
        result = self.update_external_intake_paths(rj_id, old_path, new_path)
        return {
            "success": bool(result.get("success")),
            "updated": int(result.get("updated", 0)),
            "error": str(result.get("error", "")),
            "error_code": str(result.get("error_code", "")),
            "preimage": result.get("preimage", {}),
            "postimage": result.get("postimage", {}),
        }

    def get_external_works(self) -> List[sqlite3.Row]:
        """Get works needing metadata enrichment."""
        try:
            return self.conn.execute(
                "SELECT * FROM works WHERE status IN ('external','indexed') "
                "AND (title IS NULL OR title = '' OR title = rj_id)"
            ).fetchall()
        except Exception as e:
            logging.error(f"Get external works error: {e}")
            return []

    def diagnose_failed_downloads(self) -> dict:
        """RC7.10: Categorize failed/paused downloads for diagnostic.

        Returns dict with categories and per-error-prefix counts.
        """
        import os as _os
        result = {
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

        # Analyse failed downloads
        failed_rows = self.conn.execute(
            "SELECT d.*, w.title as work_title FROM downloads d "
            "LEFT JOIN works w ON d.rj_id = w.rj_id "
            "WHERE d.status = 'failed'").fetchall()
        result["failed_total"] = len(failed_rows)

        for row in failed_rows:
            lp = row["local_path"]
            has_file = lp and _os.path.exists(lp)
            part_path = lp + ".part" if lp else ""
            has_part_file = part_path and _os.path.exists(part_path)
            file_size = (_os.path.getsize(lp) if has_file else
                         _os.path.getsize(part_path) if has_part_file else 0)
            has_url = bool(row["error"] is None or "url" not in str(row["error"]).lower())

            if (has_file or has_part_file) and file_size > 0 and file_size < (row["total_bytes"] or 1):
                result["failed_resumable_partial_file"] += 1
            elif not has_file and not has_part_file:
                # Check if metadata exists for retry
                cached = self.get_metadata_cache(row["rj_id"])
                if cached:
                    result["failed_retry_from_zero"] += 1
                else:
                    result["failed_missing_url_or_metadata"] += 1
            elif file_size >= (row["total_bytes"] or 0) and row["total_bytes"] > 0:
                result["failed_complete_but_db_failed"] += 1
            else:
                result["failed_missing_file"] += 1

            # Per-error-prefix
            err = row["error"] or "unknown"
            prefix = err[:30].split(":")[0].strip()
            result["per_error_prefix"][prefix] = \
                result["per_error_prefix"].get(prefix, 0) + 1

            # Per-root-path
            if lp:
                root = str(Path(lp).parent.parent) if "/" in lp else str(Path(lp).parent)
                result["per_root_path"][root] = result["per_root_path"].get(root, 0) + 1

        # Analyse paused
        paused_rows = self.conn.execute(
            "SELECT * FROM downloads WHERE status = 'paused'").fetchall()
        for row in paused_rows:
            lp = row["local_path"]
            has_file = lp and _os.path.exists(lp)
            if has_file:
                result["paused_resumable"] += 1
            else:
                result["paused_missing_file"] += 1

        # Registered / soft-close counts
        result["registered_count"] = self.conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE status = 'registered'"
        ).fetchone()[0]
        result["stale_count"] = self.conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE status = 'stale'"
        ).fetchone()[0]
        result["ignored_count"] = self.conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE status = 'ignored'"
        ).fetchone()[0]

        return result

    # ──────────────────────────────────────────────
    #  Library items (P5/P6)
    # ──────────────────────────────────────────────
    def get_library_items(self, search="", offset=0, limit=0,
                          filter_audio=False, filter_cover=False, filter_warnings=False) -> list:
        try:
            conditions, params = [], []
            if search:
                q = f"%{search}%"
                conditions.append("(rj_id LIKE ? OR folder_name LIKE ?)")
                params.extend([q, q])
            if filter_audio:
                conditions.append("has_audio = 1")
            if filter_cover:
                conditions.append("has_cover = 0")
            if filter_warnings:
                conditions.append("warnings_json IS NOT NULL AND warnings_json != '[]' AND warnings_json != ''")
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            sql = f"SELECT * FROM library_items {where} ORDER BY total_size DESC"
            if limit > 0:
                sql += f" LIMIT {limit} OFFSET {offset}"
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        except Exception as e:
            logging.error(f"get_library_items error: {e}")
            return []

    def count_library_items(self, search="", filter_audio=False, filter_cover=False, filter_warnings=False) -> int:
        try:
            conditions, params = [], []
            if search:
                q = f"%{search}%"
                conditions.append("(rj_id LIKE ? OR folder_name LIKE ?)")
                params.extend([q, q])
            if filter_audio:
                conditions.append("has_audio = 1")
            if filter_cover:
                conditions.append("has_cover = 0")
            if filter_warnings:
                conditions.append("warnings_json IS NOT NULL AND warnings_json != '[]' AND warnings_json != ''")
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            return self.conn.execute(f"SELECT COUNT(*) FROM library_items {where}", params).fetchone()[0]
        except Exception as e:
            logging.error(f"count_library_items error: {e}")
            return 0

    def get_library_summary(self) -> dict:
        try:
            with self._lock:
                total = self.conn.execute(
                    "SELECT COUNT(*), SUM(total_files), SUM(total_size) FROM library_items"
                ).fetchone()
                return {
                    "total_works": total[0] or 0,
                    "total_files": total[1] or 0,
                    "total_size": total[2] or 0,
                    "with_audio": self.conn.execute(
                        "SELECT COUNT(*) FROM library_items WHERE has_audio=1"
                    ).fetchone()[0],
                    "with_cover": self.conn.execute(
                        "SELECT COUNT(*) FROM library_items WHERE has_cover=1"
                    ).fetchone()[0],
                    "with_warnings": self.conn.execute(
                        "SELECT COUNT(*) FROM library_items "
                        "WHERE warnings_json IS NOT NULL "
                        "AND warnings_json != '[]' AND warnings_json != ''"
                    ).fetchone()[0],
                    "cloud_archived": self.conn.execute(
                        "SELECT COUNT(*) FROM cloud_archives"
                    ).fetchone()[0],
                }
        except Exception as e:
            logging.error(f"get_library_summary error: {e}")
            return {}

    def get_library_page(self, *, search: str = "", offset: int = 0,
                         limit: int = 20, category: str = "all",
                         sort: str = "size_desc") -> dict:
        """Return one card page plus summary using a single serialized read."""
        try:
            with self._lock:
                conditions, params = [], []
                if search:
                    query = f"%{search}%"
                    conditions.append(
                        "(li.rj_id LIKE ? OR li.folder_name LIKE ? OR li.folder_path LIKE ?)"
                    )
                    params.extend([query, query, query])
                category_conditions = {
                    "audio": "li.has_audio = 1",
                    "missing_cover": "li.has_cover = 0",
                    "warnings": "li.warnings_json IS NOT NULL AND li.warnings_json != '[]' AND li.warnings_json != ''",
                    "completed": (
                        "w.status = 'completed' AND "
                        "w.postprocess_status IN ('completed','not_required') AND "
                        "NOT EXISTS (SELECT 1 FROM downloads dx "
                        "WHERE dx.rj_id=li.rj_id AND dx.status NOT IN "
                        "('completed','registered','stale','ignored'))"
                    ),
                    "postprocess_pending": (
                        "w.status = 'completed' AND "
                        "COALESCE(w.postprocess_status,'unknown') NOT IN "
                        "('completed','not_required')"
                    ),
                    "cloud_archived": "ca.rj_id IS NOT NULL",
                }
                if category in category_conditions:
                    conditions.append(category_conditions[category])
                order_by = {
                    "size_desc": "li.total_size DESC, li.rj_id",
                    "files_desc": "li.total_files DESC, li.rj_id",
                    "name_asc": "li.folder_name COLLATE NOCASE, li.rj_id",
                    "rj_desc": "li.rj_id DESC",
                }.get(sort, "li.total_size DESC, li.rj_id")
                where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
                total = int(self.conn.execute(
                    f"""SELECT COUNT(*) FROM library_items li
                         LEFT JOIN works w ON w.rj_id=li.rj_id
                         LEFT JOIN cloud_archives ca ON ca.rj_id=li.rj_id
                         {where}""", params
                ).fetchone()[0])
                rows = self.conn.execute(
                    f"""SELECT li.*, mc.cover_url AS metadata_cover_url,
                               w.status AS work_status,
                               w.postprocess_status, w.postprocess_error,
                               ca.provider AS archive_provider,
                               ca.remote_path AS archive_remote_path,
                               ca.note AS archive_note,
                               ca.archived_at, ca.original_local_path,
                               ca.cover_cache_path AS archive_cover_path
                        FROM library_items li
                        LEFT JOIN metadata_cache mc ON mc.rj_id = li.rj_id
                        LEFT JOIN works w ON w.rj_id = li.rj_id
                        LEFT JOIN cloud_archives ca ON ca.rj_id = li.rj_id
                        {where}
                        ORDER BY {order_by}
                        LIMIT ? OFFSET ?""",
                    [*params, int(limit), int(offset)],
                ).fetchall()
                works_count = int(self.conn.execute(
                    "SELECT COUNT(*) FROM works"
                ).fetchone()[0])
                summary = self.get_library_summary()
                return {
                    "items": [dict(row) for row in rows],
                    "total": total,
                    "works_count": works_count,
                    "summary": summary,
                }
        except Exception as exc:
            logging.error("get_library_page error: %s", exc)
            return {"items": [], "total": 0, "works_count": 0, "summary": {}}

    def get_library_detail(self, rj_id: str) -> dict | None:
        """Return one immutable library-detail snapshot without touching disk."""
        normalized = str(rj_id or "").strip().upper()
        if not normalized:
            return None
        try:
            with self._lock:
                row = self.conn.execute(
                    """SELECT li.*, w.title AS work_title, w.circle AS work_circle,
                              w.status AS work_status, w.cover_url AS work_cover_url,
                               w.postprocess_status, w.postprocess_error,
                               w.postprocess_updated_at,
                              mc.title AS metadata_title, mc.circle AS metadata_circle,
                              mc.cover_url AS metadata_cover_url,
                              COALESCE(mc.metadata_json, ca.metadata_json) AS metadata_json,
                              mc.tracks_json, mc.fetched_at,
                              ca.provider AS archive_provider,
                              ca.remote_path AS archive_remote_path,
                              ca.note AS archive_note,
                              ca.archived_at, ca.original_local_path,
                              ca.cover_cache_path AS archive_cover_path
                       FROM library_items li
                       LEFT JOIN works w ON w.rj_id = li.rj_id
                       LEFT JOIN metadata_cache mc ON mc.rj_id = li.rj_id
                       LEFT JOIN cloud_archives ca ON ca.rj_id = li.rj_id
                       WHERE li.rj_id = ?""",
                    (normalized,),
                ).fetchone()
            if not row:
                return None
            result = dict(row)
            for key in ("metadata_json", "tracks_json", "warnings_json"):
                raw = result.get(key) or "[]"
                try:
                    result[key] = json.loads(raw)
                except (TypeError, ValueError):
                    result[key] = [] if key != "metadata_json" else {}
            return result
        except Exception as exc:
            logging.error("get_library_detail error: %s", exc)
            return None

    def get_library_diagnostic_rows(self) -> dict:
        """Return immutable row snapshots for background filesystem diagnosis."""
        try:
            with self._lock:
                works = [dict(row) for row in self.conn.execute(
                    "SELECT rj_id, title, status, local_path FROM works ORDER BY rj_id"
                ).fetchall()]
                items = [dict(row) for row in self.conn.execute(
                    "SELECT * FROM library_items ORDER BY rj_id"
                ).fetchall()]
                return {
                    "works": works,
                    "library_items": items,
                    "works_count": len(works),
                    "summary": self.get_library_summary(),
                }
        except Exception as exc:
            logging.error("get_library_diagnostic_rows error: %s", exc)
            return {"works": [], "library_items": [], "works_count": 0, "summary": {}}



