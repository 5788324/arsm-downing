"""Consistent read-only snapshots for a live SQLite application database.

The source database is opened with ``mode=ro`` and copied with SQLite's
online backup API.  The source WAL/SHM files are never copied or modified by
this module.  A snapshot is written to a temporary file, verified, and then
atomically moved to its final path.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


class DatabaseSnapshotError(RuntimeError):
    """Raised when a safe database snapshot cannot be produced."""


@dataclass(frozen=True)
class DatabaseSnapshotResult:
    source_path: str
    snapshot_path: str
    manifest_path: str
    created_at: str
    snapshot_size: int
    snapshot_sha256: str
    integrity_check: str
    source_wal_present: bool
    source_shm_present: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _source_uri(path: Path) -> str:
    # as_uri() handles Windows drive letters and escaping correctly.
    return f"{path.as_uri()}?mode=ro"


def create_database_snapshot(
    source_db: str | Path,
    destination_db: str | Path,
    *,
    retries: int = 3,
    retry_delay: float = 0.25,
    pages_per_step: int = 256,
    progress: Callable[[int, int, int], None] | None = None,
) -> DatabaseSnapshotResult:
    """Create and verify a point-in-time snapshot of an existing SQLite DB.

    This function is designed for a database that may still be receiving
    writes from the running downloader.  It never opens the source in write
    mode and never copies ``-wal``/``-shm`` files manually.
    """

    source = Path(source_db).expanduser().resolve(strict=True)
    destination = Path(destination_db).expanduser().resolve(strict=False)

    if not source.is_file():
        raise DatabaseSnapshotError(f"source is not a file: {source}")
    if source == destination:
        raise DatabaseSnapshotError("source and destination must be different")
    if destination.exists():
        raise DatabaseSnapshotError(f"destination already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
    if manifest_path.exists():
        raise DatabaseSnapshotError(f"manifest already exists: {manifest_path}")

    token = uuid.uuid4().hex
    temp_db = destination.with_name(f".{destination.name}.{token}.tmp")
    temp_manifest = manifest_path.with_name(f".{manifest_path.name}.{token}.tmp")

    source_wal = Path(str(source) + "-wal")
    source_shm = Path(str(source) + "-shm")
    last_error: Exception | None = None

    destination_installed = False
    manifest_installed = False
    try:
        for attempt in range(1, max(1, retries) + 1):
            source_conn: sqlite3.Connection | None = None
            target_conn: sqlite3.Connection | None = None
            try:
                source_conn = sqlite3.connect(
                    _source_uri(source),
                    uri=True,
                    timeout=10,
                    isolation_level=None,
                )
                source_conn.execute("PRAGMA query_only=ON")
                source_conn.execute("PRAGMA busy_timeout=10000")

                target_conn = sqlite3.connect(temp_db)
                target_conn.execute("PRAGMA busy_timeout=10000")
                source_conn.backup(
                    target_conn,
                    pages=max(1, pages_per_step),
                    progress=progress,
                    sleep=0.05,
                )
                target_conn.commit()

                row = target_conn.execute("PRAGMA integrity_check").fetchone()
                integrity = str(row[0]) if row else "missing_result"
                if integrity.lower() != "ok":
                    raise DatabaseSnapshotError(
                        f"snapshot integrity_check failed: {integrity}"
                    )
                break
            except (sqlite3.Error, OSError, DatabaseSnapshotError) as exc:
                last_error = exc
                if target_conn is not None:
                    target_conn.close()
                    target_conn = None
                if source_conn is not None:
                    source_conn.close()
                    source_conn = None
                temp_db.unlink(missing_ok=True)
                if attempt >= max(1, retries):
                    raise DatabaseSnapshotError(
                        f"snapshot failed after {attempt} attempt(s): {exc}"
                    ) from exc
                time.sleep(max(0.0, retry_delay))
            finally:
                if target_conn is not None:
                    target_conn.close()
                if source_conn is not None:
                    source_conn.close()
        else:  # pragma: no cover - loop always breaks or raises
            raise DatabaseSnapshotError(str(last_error or "snapshot failed"))

        snapshot_size = temp_db.stat().st_size
        snapshot_sha256 = _sha256(temp_db)
        created_at = datetime.now(timezone.utc).isoformat()
        result = DatabaseSnapshotResult(
            source_path=str(source),
            snapshot_path=str(destination),
            manifest_path=str(manifest_path),
            created_at=created_at,
            snapshot_size=snapshot_size,
            snapshot_sha256=snapshot_sha256,
            integrity_check="ok",
            source_wal_present=source_wal.exists(),
            source_shm_present=source_shm.exists(),
        )

        temp_manifest.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_db, destination)
        destination_installed = True
        os.replace(temp_manifest, manifest_path)
        manifest_installed = True
        return result
    except Exception:
        temp_db.unlink(missing_ok=True)
        temp_manifest.unlink(missing_ok=True)
        if destination_installed and not manifest_installed:
            destination.unlink(missing_ok=True)
        if manifest_installed and not destination.exists():
            manifest_path.unlink(missing_ok=True)
        raise
