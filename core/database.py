import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Dict

from core.models import WorkMetadata

DB_FILE = Path("history.db")

# Cache expiry: 7 days
CACHE_TTL_HOURS = 168


class LibraryVault:
    """Manages download history, metadata cache, and download state.

    All writes are protected by a global threading.RLock to prevent
    concurrent-transaction errors from multiple threads/coroutines.
    Reads use the shared connection (check_same_thread=False) for speed.
    """

    def __init__(self):
        self.db_path = str(DB_FILE)
        self._lock = threading.RLock()
        # Shared read-only connection
        with self._lock:
            self.conn = sqlite3.connect(self.db_path,
                                        check_same_thread=False,
                                        isolation_level=None)  # RC7.1: autocommit reads
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _write_conn(self):
        """Return a new connection for a write, with lock held by caller."""
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
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
                    status TEXT DEFAULT 'completed'
                )
            """)

        # Migration for works
        for col_name, col_type in [
            ("size_bytes", "INTEGER DEFAULT 0"),
            ("local_path", "TEXT"),
            ("cover_url", "TEXT"),
            ("status", "TEXT DEFAULT 'completed'"),
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
                    updated_at TIMESTAMP
                )
            """)
        conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_downloads_rj
                ON downloads(rj_id)
            """)

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
    def get_metadata_cache(self, rj_id: str) -> Optional[Dict]:
        """Return cached metadata dict or None if missing/expired."""
        try:
            row = self.conn.execute(
                "SELECT * FROM metadata_cache WHERE rj_id = ?", (rj_id,)
            ).fetchone()
            if not row:
                return None
            # Check expiry
            fetched = datetime.fromisoformat(row["fetched_at"])
            if datetime.now() - fetched > timedelta(hours=CACHE_TTL_HOURS):
                return None
            return {
                "rj_id": row["rj_id"],
                "title": row["title"],
                "circle": row["circle"],
                "cover_url": row["cover_url"],
                "metadata_json": row["metadata_json"],
                "tracks_json": row["tracks_json"],
                "fetched_at": row["fetched_at"],
            }
        except Exception as e:
            logging.warning(f"Metadata cache read error: {e}")
            return None

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

    def invalidate_cache(self, rj_id: str) -> None:
        """Force next lookup to fetch fresh data. Raises on failure."""
        self._execute_write(
            "DELETE FROM metadata_cache WHERE rj_id = ?", (rj_id,))

    # ──────────────────────────────────────────────
    #  Download state (P1-2)
    # ──────────────────────────────────────────────
    def upsert_download(self, download_id: str, rj_id: str,
                        track_title: str, local_path: str,
                        status: str, downloaded_bytes: int = 0,
                        total_bytes: int = 0, error: str = "") -> None:
        """Write download state. Raises on failure (RC7.1)."""
        self._execute_write(
            """INSERT OR REPLACE INTO downloads
               (id, rj_id, track_title, local_path, status,
                downloaded_bytes, total_bytes, error, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (download_id, rj_id, track_title, local_path,
             status, downloaded_bytes, total_bytes, error, datetime.now()))

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
        """Get all downloads not in terminal state, for resume."""
        try:
            return self.conn.execute(
                """SELECT * FROM downloads
                   WHERE status NOT IN ('completed', 'registered', 'failed')
                   ORDER BY rj_id, id"""
            ).fetchall()
        except Exception as e:
            logging.error(f"Pending downloads read error: {e}")
            return []

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

    def get_pending_rj_ids(self) -> set:
        """Return set of rj_ids that have non-terminal downloads.

        Includes: queued, paused, downloading, failed.
        Excludes: completed, registered.
        """
        try:
            rows = self.conn.execute(
                """SELECT DISTINCT rj_id FROM downloads
                   WHERE status IN ('queued','paused','downloading','failed')"""
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
                 status: str = 'completed') -> None:
        """Register a work. Raises on failure (RC7.1)."""
        self._execute_write(
            """INSERT OR REPLACE INTO works
               (rj_id, title, circle, downloaded_at, size_bytes,
                local_path, cover_url, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (meta.rj_id, meta.title, meta.circle,
             datetime.now(), size, str(path), meta.cover_url, status))

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
        """Check if an RJ exists in any library path."""
        try:
            return self.conn.execute(
                "SELECT * FROM library_index WHERE rj_id = ? AND status != 'missing'",
                (rj_id,)
            ).fetchall()
        except Exception as e:
            logging.error(f"Library lookup error: {e}")
            return []

    @staticmethod
    def normalize_rj_id(raw: str) -> str:
        """Normalize a directory name to 'RJxxxxxxxx' format (8 digits)."""
        import re as _re
        m = _re.search(r'(?:RJ)?(\d{6,8})', raw, _re.IGNORECASE)
        if m:
            return f"RJ{int(m.group(1)):08d}"
        return ""

    def scan_library_paths(self, paths: List[str]) -> int:
        """Scan library paths for RJ folders. Returns count found."""
        import re as _re
        rj_re = _re.compile(r'(?:RJ)?(\d{6,8})', _re.IGNORECASE)
        found = 0

        def _scan_dir(d: Path, lib_path: str):
            nonlocal found
            if not d.is_dir():
                return
            m = rj_re.search(d.name)
            if m:
                rj_id = f"RJ{int(m.group(1)):08d}"
                files = list(d.rglob("*"))
                file_count = sum(1 for f in files if f.is_file())
                size_bytes = sum(f.stat().st_size for f in files if f.is_file())
                self.upsert_library_entry(
                    rj_id, lib_path, str(d),
                    size_bytes, file_count, 'found')
                found += 1
                return True
            return False

        for lib_path in paths:
            p = Path(lib_path)
            if not p.exists():
                continue
            for d in p.iterdir():
                if not _scan_dir(d, lib_path):
                    for sub in d.iterdir():
                        _scan_dir(sub, lib_path)
        return found

    def rebuild_library(self, paths: List[str]) -> dict:
        """Scan library paths and sync to works table. Returns stats."""
        result = {"found": 0, "indexed": 0, "errors": 0}
        _n = self.scan_library_paths(paths)
        result["found"] = _n

        def _sync(conn):
            rows = conn.execute(
                "SELECT DISTINCT rj_id, work_dir, library_path, size_bytes FROM library_index"
            ).fetchall()
            for row in rows:
                try:
                    existing = conn.execute(
                        "SELECT rj_id FROM works WHERE rj_id=?", (row["rj_id"],)
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            """INSERT OR IGNORE INTO works
                               (rj_id, title, circle, size_bytes, local_path, status, downloaded_at)
                               VALUES (?, ?, ?, ?, ?, 'external', ?)""",
                            (row["rj_id"], row["rj_id"], "",
                             row["size_bytes"], row["work_dir"], datetime.now()))
                        result["indexed"] += 1
                except Exception as e:
                    logging.error(f"Rebuild sync error {row['rj_id']}: {e}")
                    result["errors"] += 1
        self._write(_sync)
        return result

    def enrich_external_metadata(self, rj_id: str, meta_raw: dict,
                                  cover_url: str, title: str, circle: str):
        """Update works table. Raises on failure (RC7.1)."""
        self._execute_write(
            """UPDATE works SET title=?, circle=?, cover_url=?, status='external'
               WHERE rj_id=? AND status IN ('external','indexed','prepared')""",
            (title, circle, cover_url, rj_id))

    def verify_library_item(self, rj_id: str, work_dir: str,
                            metadata_tracks: list) -> str:
        """Compare metadata tracks with local files. Returns status."""
        import os as _os
        d = Path(work_dir)
        result_status = "missing"

        def _verify(conn):
            nonlocal result_status
            if not d.exists():
                conn.execute(
                    "UPDATE works SET status='missing' WHERE rj_id=? AND local_path=?",
                    (rj_id, work_dir))
                result_status = "missing"
                return

            has_part = any(f.suffix == ".part" for f in d.rglob("*.part"))
            if has_part:
                conn.execute(
                    "UPDATE works SET status='partial' WHERE rj_id=? AND local_path=?",
                    (rj_id, work_dir))
                result_status = "partial"
                return

            missing_count = 0
            for track in metadata_tracks:
                if track.get("type") == "folder":
                    continue
                tname = track.get("title", "")
                found = any(
                    f.name.startswith(Path(tname).stem)
                    for f in d.rglob("*") if f.is_file())
                if not found:
                    missing_count += 1

            s = "partial" if missing_count > 0 else "verified"
            conn.execute(
                "UPDATE works SET status=? WHERE rj_id=? AND local_path=?",
                (s, rj_id, work_dir))
            result_status = s

        self._write(_verify)
        return result_status

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
