from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path


def make_temp_closeout_db() -> tuple[Path, sqlite3.Connection]:
    temp_root = Path(os.environ.get("TEMP", ".")) / f"rc9_1_closeout_test_{uuid.uuid4().hex[:8]}"
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE works (rj_id TEXT PRIMARY KEY, status TEXT, local_path TEXT)")
    conn.execute(
        """
        CREATE TABLE downloads (
            id TEXT PRIMARY KEY,
            rj_id TEXT NOT NULL,
            track_title TEXT,
            local_path TEXT,
            status TEXT NOT NULL,
            downloaded_bytes INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            error TEXT,
            updated_at TEXT
        )
        """
    )
    return db_path, conn
