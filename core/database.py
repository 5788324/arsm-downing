import csv
from functools import lru_cache
import json
import logging
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Iterable

from opencc import OpenCC

from core.intake_db import (
    IntakePathUpdateRequest,
    apply_path_update,
    capture_external_intake_snapshot,
)
from core.library_rebuild import (
    ACTIVE_DOWNLOAD_STATUSES,
    LibraryRebuildResult,
    LibraryScanError,
    _scan_work_dir,
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


_search_converter = OpenCC("t2s")


@lru_cache(maxsize=32768)
def _fold_search_segment(segment: str) -> str:
    return segment if segment.isascii() else _search_converter.convert(segment)


@lru_cache(maxsize=16384)
def _library_search_key(text: str) -> str:
    if text.isascii():
        return text.casefold()
    # Reuse the pinned OpenCC converter's separators to keep phrase matching
    # intact while sharing repeated tags and names across different albums.
    parts = _search_converter.split_chars_re.split(text)
    parts[::2] = [_fold_search_segment(part) for part in parts[::2]]
    return "".join(parts).casefold()


def _search_terms(column: str) -> str:
    return (
        f"CASE WHEN json_valid({column}) THEN "
        f"coalesce(json_extract({column},'$.tags'),'') || ' ' || "
        f"coalesce(json_extract({column},'$.vas'),'') || ' ' || "
        f"coalesce(json_extract({column},'$.voice_actors'),'') ELSE '' END"
    )


def _init_metadata_search(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_metadata_search'"
    ).fetchone()
    conn.execute("""CREATE TABLE IF NOT EXISTS library_metadata_search (
        rj_id TEXT PRIMARY KEY, title TEXT, circle TEXT, terms TEXT NOT NULL)""")
    if exists is None:
        conn.execute(f"""INSERT INTO library_metadata_search
            SELECT rj_id, title, circle, {_search_terms('metadata_json')}
            FROM metadata_cache WHERE rj_id IS NOT NULL""")
    for event in ("INSERT", "UPDATE OF rj_id, title, circle, metadata_json"):
        remove = ("DELETE FROM library_metadata_search WHERE rj_id=old.rj_id "
                  "AND old.rj_id IS NOT new.rj_id;" if event.startswith("UPDATE") else "")
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS metadata_search_{event.split()[0].lower()}
            AFTER {event} ON metadata_cache BEGIN
                {remove}
                INSERT INTO library_metadata_search (rj_id, title, circle, terms)
                SELECT new.rj_id, new.title, new.circle, {_search_terms('new.metadata_json')}
                WHERE new.rj_id IS NOT NULL
                ON CONFLICT(rj_id) DO UPDATE SET title=excluded.title, circle=excluded.circle,
                                                terms=excluded.terms;
            END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS metadata_search_delete
        AFTER DELETE ON metadata_cache BEGIN
            DELETE FROM library_metadata_search WHERE rj_id=old.rj_id;
        END""")


def _init_queue_revisions(conn: sqlite3.Connection) -> None:
    # At most one row per changed album, regardless of the number of file writes.
    conn.execute("""CREATE TABLE IF NOT EXISTS queue_revisions (
        rj_id TEXT PRIMARY KEY, revision INTEGER NOT NULL) WITHOUT ROWID""")

    def mark(source: str, condition: str = "1") -> str:
        return f"""INSERT INTO queue_revisions (rj_id, revision)
            SELECT {source}.rj_id, 1 WHERE {source}.rj_id IS NOT NULL AND ({condition})
            ON CONFLICT(rj_id) DO UPDATE SET revision=queue_revisions.revision+1;"""

    for table, columns in (
        ("works", "rj_id, title, circle, cover_url, local_path, status, downloaded_at"),
        ("downloads", "id, rj_id, status, track_title, downloaded_bytes, total_bytes, error, updated_at"),
    ):
        for event, body in (
            ("INSERT", mark("new")),
            (f"UPDATE OF {columns}", mark("new") + mark("old", "old.rj_id IS NOT new.rj_id")),
            ("DELETE", mark("old")),
        ):
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS queue_{table}_{event.split()[0].lower()}
                AFTER {event} ON {table} BEGIN {body} END""")
    # REPLACE can silently delete an existing file row belonging to another RJ.
    conn.execute("""CREATE TRIGGER IF NOT EXISTS queue_downloads_replace
        BEFORE INSERT ON downloads BEGIN
            INSERT INTO queue_revisions (rj_id, revision)
            SELECT rj_id, 1 FROM downloads WHERE id=new.id AND rj_id IS NOT new.rj_id
            ON CONFLICT(rj_id) DO UPDATE SET revision=queue_revisions.revision+1;
        END""")


def _release_date_sql(column: str) -> str:
    """Use the saved DLsite date, including the upstream 'release' spelling."""
    fields = [f"substr(trim(json_extract({column},'$.{key}')),1,10)"
              for key in ("release_date", "release")]
    valid = [f"CASE WHEN date({ymd},'+0 days')={ymd} THEN {ymd} END" for ymd in fields]
    return f"CASE WHEN json_valid({column}) THEN coalesce({', '.join(valid)}) END"


def _admitted_at_sql(item: str) -> str:
    return f"""coalesce(
        CASE WHEN {item}.folder_path<>'' THEN (
            SELECT julianday(w.downloaded_at) FROM works w WHERE w.rj_id={item}.rj_id
            AND w.status IN ('completed','registered','verified','external','indexed')
            AND w.local_path<>''
        ) END,
        CASE WHEN {item}.folder_path<>'' THEN julianday({item}.scanned_at) END,
        (SELECT julianday(ca.archived_at) FROM cloud_archives ca WHERE ca.rj_id={item}.rj_id),
        julianday({item}.scanned_at)
    )"""


def _init_library_dates(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('library_admissions', 'library_release_dates')"
    )}
    conn.execute("""CREATE TABLE IF NOT EXISTS library_admissions (
        rj_id TEXT PRIMARY KEY, admitted_at REAL NOT NULL) WITHOUT ROWID""")
    if "library_admissions" not in tables:
        conn.execute(f"""INSERT INTO library_admissions
            SELECT li.rj_id, {_admitted_at_sql('li')} AS admitted_at FROM library_items li
            WHERE li.rj_id IS NOT NULL AND admitted_at IS NOT NULL""")
    # Keep the first available timestamp even when a rescan replaces the index.
    for event in ("INSERT", "UPDATE OF folder_path, scanned_at"):
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS library_admission_{event.split()[0].lower()}
            AFTER {event} ON library_items
            WHEN new.rj_id IS NOT NULL AND NOT EXISTS
                (SELECT 1 FROM library_admissions WHERE rj_id=new.rj_id)
            BEGIN
                INSERT INTO library_admissions
                SELECT new.rj_id, admitted_at
                FROM (SELECT {_admitted_at_sql('new')} AS admitted_at)
                WHERE admitted_at IS NOT NULL;
            END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS cloud_archive_admission
        AFTER INSERT ON cloud_archives
        WHEN new.rj_id IS NOT NULL AND julianday(new.archived_at) IS NOT NULL
        BEGIN
            INSERT INTO library_admissions VALUES (new.rj_id, julianday(new.archived_at))
            ON CONFLICT(rj_id) DO NOTHING;
        END""")

    conn.execute("""CREATE TABLE IF NOT EXISTS library_release_dates (
        rj_id TEXT NOT NULL, source TEXT NOT NULL, release_date TEXT,
        PRIMARY KEY (rj_id, source)) WITHOUT ROWID""")
    for table in ("metadata_cache", "cloud_archives"):
        if "library_release_dates" not in tables:
            conn.execute(f"""INSERT INTO library_release_dates
                SELECT rj_id, '{table}', {_release_date_sql('metadata_json')}
                FROM {table} WHERE rj_id IS NOT NULL""")
        for event in ("INSERT", "UPDATE OF rj_id, metadata_json", "DELETE"):
            operation = event.split()[0].lower()
            remove = (
                f"DELETE FROM library_release_dates WHERE rj_id=old.rj_id AND source='{table}';"
                if operation != "insert" else ""
            )
            save = f"""INSERT INTO library_release_dates
                SELECT new.rj_id, '{table}', {_release_date_sql('new.metadata_json')}
                WHERE new.rj_id IS NOT NULL
                ON CONFLICT(rj_id, source) DO UPDATE SET release_date=excluded.release_date;"""
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS library_release_{table}_{operation}
                AFTER {event} ON {table} BEGIN {remove} {save if operation != 'delete' else ''} END""")


def _album_tag_rows(column: str) -> str:
    # json_quote preserves arrays/objects and makes scalar strings safe for json_each.
    fields = [f"json_quote(json_extract({column},'$.{key}'))" for key in ("tags", "tag")]
    values = [
        f"CASE WHEN {field} NOT IN ('[]','{{}}','\"\"','null') THEN {field} END"
        for field in fields
    ]
    array = f"CASE WHEN json_valid({column}) THEN coalesce({', '.join(values)},'[]') ELSE '[]' END"
    # json_each expands a bare object as a tag map, and accepts a scalar string.
    return f"""SELECT DISTINCT trim(CASE type
        WHEN 'object' THEN json_extract(value,'$.name')
        WHEN 'text' THEN value END) AS tag
        FROM json_each({array}) WHERE tag<>''"""


def _init_album_tags(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_album_tags'"
    ).fetchone()
    conn.execute("""CREATE TABLE IF NOT EXISTS library_album_tags (
        rj_id TEXT NOT NULL, source TEXT NOT NULL, tag TEXT NOT NULL COLLATE NOCASE,
        PRIMARY KEY (rj_id, source, tag)) WITHOUT ROWID""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_library_album_tag_name
                    ON library_album_tags(tag, rj_id)""")
    for table in ("metadata_cache", "cloud_archives"):
        for event in ("INSERT", "UPDATE OF rj_id, metadata_json", "DELETE"):
            operation = event.split()[0].lower()
            previous = "new" if operation == "insert" else "old"
            remove = f"DELETE FROM library_album_tags WHERE rj_id={previous}.rj_id AND source='{table}';"
            save = f"""INSERT INTO library_album_tags
                SELECT new.rj_id, '{table}', tag FROM ({_album_tag_rows('new.metadata_json')})
                WHERE new.rj_id IS NOT NULL
                ON CONFLICT DO NOTHING;"""
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS library_album_tags_{table}_{operation}
                AFTER {event} ON {table} BEGIN {remove} {save if operation != 'delete' else ''} END""")
        if exists is None:
            # Feed each metadata row through the same extraction used by the triggers.
            for rid, metadata in conn.execute(f"SELECT rj_id, metadata_json FROM {table} WHERE rj_id IS NOT NULL"):
                conn.execute(f"""INSERT INTO library_album_tags
                    SELECT ?1, '{table}', tag FROM ({_album_tag_rows('?2')})
                    WHERE true ON CONFLICT DO NOTHING""", (rid, metadata))


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
        projection_tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('library_metadata_search', 'queue_revisions', 'library_admissions', 'library_release_dates', 'library_album_tags')"
        )}
        self._has_metadata_search = "library_metadata_search" in projection_tables
        self._has_queue_revisions = "queue_revisions" in projection_tables
        self._has_album_tags = 'library_album_tags' in projection_tables
        self._has_library_dates = {"library_admissions", "library_release_dates"} <= projection_tables

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
        conn.execute("""CREATE TABLE IF NOT EXISTS library_user_state (
            rj_id TEXT PRIMARY KEY, favorite INTEGER NOT NULL DEFAULT 0, played_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS library_asset_checks (
            rj_id TEXT PRIMARY KEY, folder_path TEXT NOT NULL,
            missing_tags INTEGER NOT NULL, checked_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS library_collections (
            name TEXT NOT NULL COLLATE NOCASE, rj_id TEXT NOT NULL,
            PRIMARY KEY (name, rj_id))""")

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
        self._safe_alter(conn, "library_items", "missing_lrc", "INTEGER DEFAULT 0")

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
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_library_items_size_sort
                        ON library_items(total_size DESC, rj_id)""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_cloud_archive_sizes
                        ON cloud_archives(total_size)""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_downloads_rj_status
                        ON downloads(rj_id, status)""")
        _init_metadata_search(conn)
        _init_queue_revisions(conn)
        _init_library_dates(conn)
        _init_album_tags(conn)
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
                f"SELECT DISTINCT rj_id, status FROM downloads "
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

    @staticmethod
    def _write_library_entry(conn, entry, scanned: str) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO library_index
               (rj_id, library_path, work_dir, status, size_bytes, file_count, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""", entry.to_library_index_row(scanned))
        conn.execute(
            """INSERT OR REPLACE INTO library_items
               (rj_id, folder_path, folder_name, total_files, total_size, audio_count,
                image_count, video_count, other_count, has_audio, has_cover,
                warnings_json, scan_run_id, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            entry.to_library_item_row("incremental", scanned))
        conn.execute("UPDATE library_items SET missing_lrc=? WHERE rj_id=?",
                     (entry.missing_lrc, entry.rj_id))

    def index_local_album(self, rj_id: str, work_dir: str | Path,
                          roots: Iterable[str | Path]) -> bool:
        """Refresh both index rows for one album without changing download state."""
        folder = Path(work_dir).resolve(strict=True)
        parents = [Path(root).resolve() for root in roots if root]
        root = next((base for base in parents if base in folder.parents), None)
        if root is None:
            raise ValueError("专辑目录不在已配置的仓库中")
        entry = _scan_work_dir(folder, rj_id=rj_id, library_root=root)
        if not entry.total_files:
            raise ValueError("专辑目录没有文件")
        scanned = datetime.now().isoformat()

        def save(conn):
            conn.execute("BEGIN IMMEDIATE")
            work = conn.execute("SELECT local_path FROM works WHERE rj_id=?",
                                (rj_id,)).fetchone()
            if not work or not work["local_path"] or Path(work["local_path"]).resolve() != folder:
                raise ValueError("作品目录已变更，请刷新后重试")
            self._write_library_entry(conn, entry, scanned)
        self._write(save)
        return True

    def backfill_downloaded_library(self, roots: Iterable[str | Path], *, progress=None) -> dict:
        """Backfill stable album folders without replacing or deleting an index."""
        parents = tuple(Path(root).resolve() for root in roots if root)
        allowed = ("completed", "registered", "verified", "indexed", "external", "partial")
        # Partial albums are eligible when they have playable files and no live/resumable tasks.
        query = """SELECT w.rj_id, w.status, w.local_path FROM works w
                   WHERE w.local_path<>'' AND w.status IN (?,?,?,?,?,?)
                     AND NOT EXISTS (SELECT 1 FROM library_items li
                                     WHERE li.rj_id=w.rj_id AND li.folder_path<>'')
                     AND NOT EXISTS (SELECT 1 FROM downloads d WHERE d.rj_id=w.rj_id
                                     AND d.status IN ('queued','downloading','resuming','paused'))"""
        with self._lock:
            candidates = [tuple(row) for row in self.conn.execute(query, allowed)]
        indexed = 0
        skipped: list[str] = []
        staged = []
        def flush():
            scanned = datetime.now().isoformat()
            def save(conn):
                conn.execute("BEGIN IMMEDIATE")
                count = 0
                for entry, status, original_path in staged:
                    eligible = conn.execute(
                        """SELECT 1 FROM works w WHERE w.rj_id=? AND w.status=? AND w.local_path=?
                             AND NOT EXISTS (SELECT 1 FROM library_items li
                                             WHERE li.rj_id=w.rj_id AND li.folder_path<>'')
                             AND NOT EXISTS (SELECT 1 FROM downloads d WHERE d.rj_id=w.rj_id
                                 AND d.status IN ('queued','downloading','resuming','paused'))""",
                        (entry.rj_id, status, original_path)).fetchone()
                    if eligible and Path(entry.work_dir).is_dir():
                        self._write_library_entry(conn, entry, scanned)
                        count += 1
                    else:
                        skipped.append(entry.rj_id)
                return count
            count = self._write(save)
            staged.clear()
            return count

        for number, (rj_id, status, original_path) in enumerate(candidates, 1):
            try:
                folder = Path(original_path).resolve(strict=True)
                root = next((base for base in parents if base in folder.parents), None)
                if root is None or not folder.is_dir():
                    skipped.append(rj_id)
                else:
                    entry = _scan_work_dir(folder, rj_id=rj_id, library_root=root)
                    if entry.has_audio:
                        staged.append((entry, status, original_path))
                    else:
                        skipped.append(rj_id)
            except (OSError, LibraryScanError):
                skipped.append(rj_id)
            if len(staged) >= 30:
                indexed += flush()
            if progress and number % 100 == 0:
                progress(number, len(candidates), indexed)
        if staged:
            indexed += flush()
        return {"candidates": len(candidates), "indexed": indexed, "skipped": skipped}

    def backup_library_catalog(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"library-catalog-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
        # SQLite's backup captures a consistent snapshot including WAL changes.
        with self._lock:
            with sqlite3.connect(target) as destination:
                self.conn.backup(destination)
                if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("资源库备份校验失败")
        return target

    def update_cloud_archive_location(self, rj_id: str, location: str) -> None:
        location = location.strip()
        if len(location) > 2048:
            raise ValueError("云盘归档位置过长")
        self._execute_write(
            "UPDATE cloud_archives SET remote_path=?,updated_at=? WHERE rj_id=?",
            (location, datetime.now().isoformat(), rj_id))

    def set_library_favorite(self, rj_id: str, favorite: bool) -> None:
        self._execute_write(
            """INSERT INTO library_user_state(rj_id,favorite) VALUES(?,?)
               ON CONFLICT(rj_id) DO UPDATE SET favorite=excluded.favorite""",
            (rj_id, int(favorite)))

    def set_library_last_played(self, rj_id: str) -> None:
        self._execute_write(
            """INSERT INTO library_user_state(rj_id,played_at) VALUES(?,?)
               ON CONFLICT(rj_id) DO UPDATE SET played_at=excluded.played_at""",
            (rj_id, datetime.now().isoformat()))

    def set_library_collection(self, rj_id: str, name: str, *, remove: bool = False) -> None:
        name = name.strip()
        if not name or len(name) > 48:
            raise ValueError("合集名称应为 1–48 个字")
        sql = ("DELETE FROM library_collections WHERE name=? AND rj_id=?" if remove else
               "INSERT OR IGNORE INTO library_collections(name,rj_id) VALUES(?,?)")
        self._execute_write(sql, (name, rj_id))

    def library_collection_names(self) -> list[str]:
        with self._lock:
            return [row[0] for row in self.conn.execute(
                "SELECT DISTINCT name FROM library_collections ORDER BY name")]

    def library_asset_roots(self) -> list[tuple[str, str]]:
        with self._lock:
            return [tuple(row) for row in self.conn.execute(
                "SELECT rj_id,folder_path FROM library_items WHERE folder_path<>'' ORDER BY rj_id")]

    def save_library_asset_checks(self, checks: list[tuple[str, str, int]]) -> None:
        timestamp = datetime.now().isoformat()
        def save(conn):
            conn.executemany(
                "INSERT INTO library_asset_checks(rj_id,folder_path,missing_tags,checked_at) "
                "VALUES(?,?,?,?) ON CONFLICT(rj_id) DO UPDATE SET "
                "folder_path=excluded.folder_path, missing_tags=excluded.missing_tags, "
                "checked_at=excluded.checked_at",
                [(*row, timestamp) for row in checks])
        self._write(save)

    def known_library_work_ids(self) -> set[str]:
        with self._lock:
            return {row[0] for row in self.conn.execute(
                "SELECT rj_id FROM works UNION SELECT rj_id FROM library_items "
                "UNION SELECT rj_id FROM library_index WHERE status<>'missing' "
                "UNION SELECT rj_id FROM cloud_archives UNION SELECT DISTINCT rj_id FROM downloads")}

    def preview_library_scan(self, paths: list[str], *, exclude_paths=()) -> dict:
        snapshot = scan_library_snapshot(paths, exclude_paths=exclude_paths)
        with self._lock:
            rows = self.conn.execute(
                "SELECT rj_id, work_dir FROM library_index WHERE status='found'"
            ).fetchall()
        old = {(row["rj_id"], str(Path(row["work_dir"])).casefold()) for row in rows}
        new = {(entry.rj_id, entry.work_dir.casefold()) for entry in snapshot.entries}
        old_ids = {rj_id for rj_id, _ in old}
        new_ids = {rj_id for rj_id, _ in new}
        return {"found": len(new_ids), "new": len(new_ids - old_ids),
                "moved": len({rj_id for rj_id, _ in new - old} & old_ids),
                "removed": len(old_ids - new_ids), "duplicates": len(new) - len(new_ids),
                "warnings": len(snapshot.warnings)}

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

    def rebuild_library(self, paths: List[str], *, exclude_paths=()) -> dict:
        """Atomically replace library indexes from a complete scan snapshot.

        Filesystem scanning happens before the SQLite transaction.  Any scan or
        write failure therefore leaves the previous indexes untouched.  Existing
        works with active/resumable downloads are never rewritten.
        """
        try:
            snapshot = (scan_library_snapshot(paths, exclude_paths=exclude_paths)
                        if exclude_paths else scan_library_snapshot(paths))
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

            conn.executemany("UPDATE library_items SET missing_lrc=? WHERE rj_id=?",
                             [(entry.missing_lrc, rj_id) for rj_id, entry in canonical.items()
                              if entry.missing_lrc])
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
                token = (self.conn.total_changes,
                         self.conn.execute("PRAGMA data_version").fetchone()[0])
                cached = getattr(self, "_library_summary_cache", None)
                if cached is not None and cached[0] == token:
                    return cached[1].copy()
                total = self.conn.execute(
                    """SELECT COUNT(*), SUM(total_files), SUM(total_size),
                              SUM(folder_path<>''),
                              SUM(CASE WHEN folder_path<>'' THEN total_size ELSE 0 END),
                              SUM(has_audio=1), SUM(has_cover=1),
                              SUM(warnings_json IS NOT NULL AND warnings_json NOT IN ('', '[]'))
                       FROM library_items"""
                ).fetchone()
                cloud = self.conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(total_size),0) FROM cloud_archives"
                ).fetchone()
                summary = dict(zip((
                    "total_works", "total_files", "total_size", "local_works", "local_bytes",
                    "with_audio", "with_cover", "with_warnings",
                ), (value or 0 for value in total)))
                summary.update(cloud_archived=cloud[0], cloud_bytes=cloud[1])
                self._library_summary_cache = token, summary
                return summary.copy()
        except Exception as exc:
            logging.error("get_library_summary error: %s", exc)
            return {}

    def get_library_page(self, *, search: str = "", offset: int = 0,
                         limit: int = 20, category: str = "all",
                         sort: str = "size_desc", collection: str = "", tag: str = "") -> dict:
        """Return one card page plus summary using a single serialized read."""
        try:
            with self._lock:
                conditions, params = [], []
                search = search.strip()
                search_table = "metadata_cache"
                exact_rj = re.fullmatch(r"RJ[0-9]{8}", search, re.IGNORECASE)
                if exact_rj:
                    conditions.append("li.rj_id = ?")
                    params.append(search.upper())
                elif search:
                    self.conn.create_function("library_fold", 1, _library_search_key,
                                              deterministic=True)
                    query = _library_search_key(search)
                    terms = _search_terms("mc.metadata_json")
                    if getattr(self, "_has_metadata_search", False):
                        search_table = "library_metadata_search"
                        terms = "coalesce(mc.terms,'')"
                    conditions.append(
                        "(instr(library_fold(li.rj_id || ' ' || li.folder_name || ' ' || "
                        "li.folder_path || ' ' || coalesce(w.title,'') || ' ' || "
                        "coalesce(w.circle,'') || ' ' || coalesce(mc.title,'') || ' ' || "
                        f"coalesce(mc.circle,'') || ' ' || {terms}), ?) > 0)"
                    )
                    params.append(query)
                tag = tag.strip()
                if tag:
                    if self._has_album_tags:
                        conditions.append("li.rj_id IN (SELECT rj_id FROM library_album_tags WHERE tag=?)")
                        params.append(tag)
                    else:
                        conditions.append(
                            "EXISTS (SELECT 1 FROM ("
                            f"{_album_tag_rows('rm.metadata_json')} UNION "
                            f"{_album_tag_rows('ca.metadata_json')}"
                            ") WHERE tag=? COLLATE NOCASE)"
                        )
                        params.append(tag)
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
                        "li.folder_path <> '' AND w.status = 'completed' AND "
                        "COALESCE(w.postprocess_status,'unknown') NOT IN "
                        "('completed','not_required')"
                    ),
                    "favorite": "ls.favorite=1",
                    "recent": "ls.played_at IS NOT NULL",
                    "missing_lrc": "li.folder_path<>'' AND li.missing_lrc>0",
                    "missing_tags": "li.folder_path<>'' AND ac.missing_tags>0",
                    "cloud_archived": "ca.rj_id IS NOT NULL",
                    "cloud_only": "ca.rj_id IS NOT NULL AND li.folder_path=''",
                    "cloud_and_local": "ca.rj_id IS NOT NULL AND li.folder_path<>''",
                    "cloud_path_missing": "ca.rj_id IS NOT NULL AND COALESCE(ca.remote_path,'')=''",
                    "needs_attention": (
                        "li.folder_path<>'' AND (li.has_audio=0 OR li.has_cover=0 OR li.missing_lrc>0 OR ac.missing_tags>0 "
                        "OR coalesce(w.postprocess_status,'unknown') IN ('pending','running','failed') "
                        "OR EXISTS (SELECT 1 FROM downloads dx WHERE dx.rj_id=li.rj_id "
                        "AND dx.status IN ('failed','paused')))"
                    ),
                }
                if category in category_conditions:
                    conditions.append(category_conditions[category])
                if category == "collection":
                    conditions.append("EXISTS (SELECT 1 FROM library_collections lc "
                                      "WHERE lc.rj_id=li.rj_id AND lc.name=?)")
                    params.append(collection)
                date_joins = ()
                has_dates = self._has_library_dates
                admission = "ad.admitted_at" if has_dates else _admitted_at_sql("li")
                release = "coalesce(rd.release_date, cd.release_date)" if has_dates else (
                    f"coalesce({_release_date_sql('rm.metadata_json')}, "
                    f"{_release_date_sql('ca.metadata_json')})"
                )
                if sort == "admitted_desc" and has_dates:
                    date_joins = ("LEFT JOIN library_admissions ad ON ad.rj_id=li.rj_id",)
                elif sort == "release_desc":
                    date_joins = (
                        "LEFT JOIN library_release_dates rd ON rd.rj_id=li.rj_id AND rd.source='metadata_cache'",
                        "LEFT JOIN library_release_dates cd ON cd.rj_id=li.rj_id AND cd.source='cloud_archives'",
                    ) if has_dates else ("LEFT JOIN metadata_cache rm ON rm.rj_id=li.rj_id",)
                sort_column, direction = {
                    "size_desc": ("li.total_size", "DESC"),
                    "files_desc": ("li.total_files", "DESC"),
                    "name_asc": ("li.folder_name COLLATE NOCASE", "ASC"),
                    "rj_desc": ("li.rj_id", "DESC"),
                    "admitted_desc": (admission, "DESC"),
                    "release_desc": (release, "DESC"),
                }.get(sort, ("li.total_size", "DESC"))
                if category == "recent":
                    sort_column, direction = "ls.played_at", "DESC"
                    date_joins = ()
                order_by = f"{sort_column} {direction}, li.rj_id"
                collate = " COLLATE NOCASE" if "COLLATE NOCASE" in sort_column else ""
                needed = " ".join(conditions) + " " + sort_column
                joins = [
                    join for alias, join in (
                        ("w.", "LEFT JOIN works w ON w.rj_id=li.rj_id"),
                        ("mc.", f"LEFT JOIN {search_table} mc ON mc.rj_id=li.rj_id"),
                        ("ca.", "LEFT JOIN cloud_archives ca ON ca.rj_id=li.rj_id"),
                        ("rm.", "LEFT JOIN metadata_cache rm ON rm.rj_id=li.rj_id"),
                        ("ls.", "LEFT JOIN library_user_state ls ON ls.rj_id=li.rj_id"),
                        ("ac.", "LEFT JOIN library_asset_checks ac "
                                "ON ac.rj_id=li.rj_id AND ac.folder_path=li.folder_path"),
                    ) if alias in needed
                ]
                joins.extend(join for join in date_joins if join not in joins)
                where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
                size, start = int(limit), max(0, int(offset))
                summary = self.get_library_summary()
                if not conditions:
                    # Select narrow IDs before any metadata/tag queries on the page.
                    total = int(summary.get("total_works", 0))
                    cte = f"""WITH page_ids AS MATERIALIZED (
                                  SELECT li.rj_id, {sort_column} AS sort_value
                                  FROM library_items li {' '.join(joins)}
                                  ORDER BY {order_by} LIMIT ? OFFSET ?
                              )"""
                    bindings = [size, start]
                    total_select = ""
                    page_from = "FROM page_ids page"
                else:
                    cte = f"""WITH matched AS MATERIALIZED (
                                  SELECT li.rj_id, {sort_column} AS sort_value
                                  FROM library_items li {' '.join(joins)} {where}
                              ), page_ids AS MATERIALIZED (
                                  SELECT rj_id, sort_value FROM matched ORDER BY sort_value{collate} {direction}, rj_id
                                  LIMIT ? OFFSET ?
                              ), amount AS (SELECT COUNT(*) AS page_total FROM matched)"""
                    bindings = [*params, size, start]
                    total_select = "amount.page_total,"
                    page_from = "FROM amount LEFT JOIN page_ids page ON 1"
                card_tags = """(SELECT json_group_array(tag) FROM (
                    SELECT DISTINCT tag FROM library_album_tags
                    WHERE rj_id=li.rj_id ORDER BY tag LIMIT 2
                ))""" if self._has_album_tags else "'[]'"
                rows = self.conn.execute(
                    f"""{cte}
                        SELECT {total_select} li.*, {card_tags} AS card_tags, ac.missing_tags, mc.cover_url AS metadata_cover_url,
                               w.status AS work_status, w.postprocess_status, w.postprocess_error,
                               (SELECT COUNT(*) FROM downloads dx WHERE dx.rj_id=li.rj_id
                                AND dx.status='ignored') AS ignored_files,
                               ca.provider AS archive_provider, ca.remote_path AS archive_remote_path,
                               ca.note AS archive_note, ca.archived_at, ca.original_local_path,
                               ca.cover_cache_path AS archive_cover_path
                        {page_from}
                        LEFT JOIN library_items li ON li.rj_id=page.rj_id
                        LEFT JOIN metadata_cache mc ON mc.rj_id=li.rj_id
                        LEFT JOIN works w ON w.rj_id=li.rj_id
                        LEFT JOIN library_user_state ls ON ls.rj_id=li.rj_id
                        LEFT JOIN library_asset_checks ac ON ac.rj_id=li.rj_id AND ac.folder_path=li.folder_path
                        LEFT JOIN cloud_archives ca ON ca.rj_id=li.rj_id
                        ORDER BY page.sort_value{collate} {direction}, li.rj_id""",
                    bindings,
                ).fetchall()
                if conditions:
                    total = rows[0]["page_total"] if rows else 0
                items = []
                for row in rows:
                    if row["rj_id"] is None:
                        continue
                    item = dict(row)
                    item.pop("page_total", None)
                    item["card_tags"] = json.loads(item["card_tags"])
                    items.append(item)
                works_count = int(self.conn.execute(
                    "SELECT COUNT(*) FROM works"
                ).fetchone()[0])
                return {
                    "items": items,
                    "total": total,
                    "works_count": works_count,
                    "summary": summary,
                }
        except Exception as exc:
            logging.error("get_library_page error: %s", exc)
            return {"items": [], "total": 0, "works_count": 0, "summary": {},
                    "error": "资源库读取失败，请刷新重试"}

    def get_library_detail(self, rj_id: str) -> dict | None:
        """Return one immutable library-detail snapshot without touching disk."""
        normalized = str(rj_id or "").strip().upper()
        if not normalized:
            return None
        try:
            with self._lock:
                row = self.conn.execute(
                    """SELECT li.*, ls.favorite, ls.played_at,
                              w.title AS work_title, w.circle AS work_circle,
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
                       LEFT JOIN library_user_state ls ON ls.rj_id=li.rj_id
                       LEFT JOIN metadata_cache mc ON mc.rj_id = li.rj_id
                       LEFT JOIN cloud_archives ca ON ca.rj_id = li.rj_id
                       WHERE li.rj_id = ?""",
                    (normalized,),
                ).fetchone()
                if row is None:
                    return None
                album_tags = [tag[0] for tag in self.conn.execute(
                    "SELECT DISTINCT tag FROM library_album_tags WHERE rj_id=? ORDER BY tag",
                    (normalized,),
                )] if self._has_album_tags else []
            result = dict(row)
            result["album_tags"] = album_tags
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
            return {"works": [], "library_items": [], "works_count": 0, "summary": {},
                    "error": "异常记录读取失败，请刷新重试"}



