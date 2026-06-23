import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Tuple
from core.models import WorkMetadata

DB_FILE = Path("history.db")

class LibraryVault:
    """Manages download history and library database."""
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS works (
                    rj_id TEXT PRIMARY KEY,
                    title TEXT,
                    circle TEXT,
                    downloaded_at TIMESTAMP,
                    size_bytes INTEGER DEFAULT 0,
                    local_path TEXT,
                    cover_url TEXT
                )
            """)
            # Add track_files to keep file state
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS track_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rj_id TEXT,
                    title TEXT,
                    path TEXT,
                    size INTEGER,
                    downloaded INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    FOREIGN KEY(rj_id) REFERENCES works(rj_id)
                )
            """)

    def register(self, meta: WorkMetadata, size: int, path: Path) -> None:
        """Register a downloaded work in the database."""
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO works 
                   (rj_id, title, circle, downloaded_at, size_bytes, local_path, cover_url) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (meta.rj_id, meta.title, meta.circle, datetime.now(), size, str(path), meta.cover_url)
            )

    def get_summary(self) -> Tuple[int, int]:
        """Get library summary: count and total size."""
        cnt = self.conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        sz = self.conn.execute("SELECT SUM(size_bytes) FROM works").fetchone()[0] or 0
        return cnt, sz

    def search(self, query: str = "") -> List[sqlite3.Row]:
        """Search for works in the library."""
        if not query:
            sql = "SELECT * FROM works ORDER BY downloaded_at DESC LIMIT 50"
            return self.conn.execute(sql).fetchall()
        
        q = f"%{query}%"
        sql = """SELECT * FROM works 
                 WHERE title LIKE ? OR rj_id LIKE ? OR circle LIKE ? 
                 ORDER BY downloaded_at DESC LIMIT 50"""
        return self.conn.execute(sql, (q, q, q)).fetchall()
