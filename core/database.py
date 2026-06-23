import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Dict

from core.models import WorkMetadata

DB_FILE = Path("history.db")

# Cache expiry: 7 days
CACHE_TTL_HOURS = 168


class LibraryVault:
    """Manages download history, metadata cache, and download state."""

    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ──────────────────────────────────────────────
    #  Schema & migration
    # ──────────────────────────────────────────────
    def _init_schema(self) -> None:
        with self.conn:
            # ── works table (P0) ──
            self.conn.execute("""
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
            self._safe_alter("works", col_name, col_type)

        # ── metadata_cache (P1-1) ──
        with self.conn:
            self.conn.execute("""
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
        with self.conn:
            self.conn.execute("""
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
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_downloads_rj
                ON downloads(rj_id)
            """)

    def _safe_alter(self, table: str, col_name: str, col_type: str) -> None:
        try:
            self.conn.execute(
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
        """Store metadata and tracks in cache."""
        try:
            import json as _json
            now = datetime.now()
            with self.conn:
                self.conn.execute(
                    """INSERT OR REPLACE INTO metadata_cache
                       (rj_id, title, circle, cover_url, metadata_json,
                        tracks_json, fetched_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rj_id, title, circle, cover_url,
                     _json.dumps(metadata_raw, ensure_ascii=False),
                     _json.dumps(tracks_raw, ensure_ascii=False),
                     now, now)
                )
        except Exception as e:
            logging.error(f"Metadata cache write error: {e}")

    def invalidate_cache(self, rj_id: str) -> None:
        """Force next lookup to fetch fresh data."""
        try:
            self.conn.execute(
                "DELETE FROM metadata_cache WHERE rj_id = ?", (rj_id,)
            )
            self.conn.commit()
        except Exception as e:
            logging.error(f"Cache invalidation error: {e}")

    # ──────────────────────────────────────────────
    #  Download state (P1-2)
    # ──────────────────────────────────────────────
    def upsert_download(self, download_id: str, rj_id: str,
                        track_title: str, local_path: str,
                        status: str, downloaded_bytes: int = 0,
                        total_bytes: int = 0, error: str = "") -> None:
        try:
            now = datetime.now()
            with self.conn:
                self.conn.execute(
                    """INSERT OR REPLACE INTO downloads
                       (id, rj_id, track_title, local_path, status,
                        downloaded_bytes, total_bytes, error, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (download_id, rj_id, track_title, local_path,
                     status, downloaded_bytes, total_bytes, error, now)
                )
        except Exception as e:
            logging.error(f"Download state write error: {e}")

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

    def clear_terminal_downloads(self, rj_id: str) -> None:
        """Remove completed/failed/registered downloads for a work."""
        try:
            self.conn.execute(
                """DELETE FROM downloads
                   WHERE rj_id = ? AND status IN ('completed','registered','failed')""",
                (rj_id,)
            )
            self.conn.commit()
        except Exception as e:
            logging.error(f"Clear terminal downloads error: {e}")

    # ──────────────────────────────────────────────
    #  Works library (P0, unchanged logic)
    # ──────────────────────────────────────────────
    def register(self, meta: WorkMetadata, size: int, path: Path,
                 status: str = 'completed') -> None:
        """Register a work in the library with a given status."""
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT OR REPLACE INTO works
                       (rj_id, title, circle, downloaded_at, size_bytes,
                        local_path, cover_url, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (meta.rj_id, meta.title, meta.circle,
                     datetime.now(), size, str(path), meta.cover_url, status)
                )
        except sqlite3.Error as e:
            logging.error(f"Database register error for {meta.rj_id}: {e}")

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

    def search(self, query: str = "") -> List[sqlite3.Row]:
        try:
            if not query:
                sql = "SELECT * FROM works ORDER BY downloaded_at DESC LIMIT 50"
                return self.conn.execute(sql).fetchall()
            q = f"%{query}%"
            sql = """SELECT * FROM works
                     WHERE title LIKE ? OR rj_id LIKE ? OR circle LIKE ?
                     ORDER BY downloaded_at DESC LIMIT 50"""
            return self.conn.execute(sql, (q, q, q)).fetchall()
        except sqlite3.Error as e:
            logging.error(f"Database search error: {e}")
            return []
