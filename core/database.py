import json
import logging
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
                }
        except Exception as e:
            logging.error(f"get_library_summary error: {e}")
            return {}

    def get_library_page(self, *, search: str = "", offset: int = 0,
                         limit: int = 20) -> dict:
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
                where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
                total = int(self.conn.execute(
                    f"SELECT COUNT(*) FROM library_items li {where}", params
                ).fetchone()[0])
                rows = self.conn.execute(
                    f"""SELECT li.*, mc.cover_url AS metadata_cover_url
                        FROM library_items li
                        LEFT JOIN metadata_cache mc ON mc.rj_id = li.rj_id
                        {where}
                        ORDER BY li.total_size DESC, li.rj_id
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
