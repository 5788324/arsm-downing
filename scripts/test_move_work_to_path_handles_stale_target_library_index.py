#!/usr/bin/env python3
"""Portable regression: conflicting source+target index rows fail closed."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.database import LibraryVault


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "history.db"
        source = "/old/RJ01020001"
        target = "/new/RJ01020001"
        rj_id = "RJ01020001"
        with LibraryVault(db_path) as vault:
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "INSERT INTO works (rj_id, local_path, status) VALUES (?, ?, 'verified')",
                    (rj_id, source),
                )
                for path in (source, target):
                    connection.execute(
                        """INSERT INTO library_index
                           (rj_id, library_path, work_dir, status)
                           VALUES (?, ?, ?, 'found')""",
                        (rj_id, str(Path(path).parent), path),
                    )
                connection.commit()
            finally:
                connection.close()

            result = vault.move_work_to_path(rj_id, source, target)
            assert not result["success"], result
            assert result["error_code"] == "target_reference_conflict", result
            row = vault.conn.execute(
                "SELECT local_path FROM works WHERE rj_id=?", (rj_id,)
            ).fetchone()
            assert row["local_path"] == source

    print("OK conflicting library_index rows are preserved and blocked for review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
