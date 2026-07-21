"""Read-only inspection helpers for verified SQLite snapshots."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from core.database_snapshot import DatabaseSnapshotError
from core.status import WorkStatus

KNOWN_TABLES = (
    "works",
    "downloads",
    "metadata_cache",
    "library_items",
    "library_index",
)


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_snapshot_manifest(snapshot_db: str | Path) -> dict[str, Any]:
    snapshot = Path(snapshot_db).expanduser().resolve(strict=True)
    manifest_path = snapshot.with_suffix(snapshot.suffix + ".manifest.json")
    if not manifest_path.is_file():
        raise DatabaseSnapshotError(f"snapshot manifest is missing: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatabaseSnapshotError(f"invalid snapshot manifest: {exc}") from exc

    expected_size = int(manifest.get("snapshot_size", -1))
    expected_hash = str(manifest.get("snapshot_sha256", ""))
    actual_size = snapshot.stat().st_size
    actual_hash = _sha256(snapshot)
    if expected_size != actual_size:
        raise DatabaseSnapshotError(
            f"snapshot size does not match manifest: {actual_size} != {expected_size}"
        )
    if expected_hash != actual_hash:
        raise DatabaseSnapshotError("snapshot SHA-256 does not match manifest")
    return manifest


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _group_counts(connection: sqlite3.Connection, table: str) -> dict[str, int]:
    if not _table_exists(connection, table):
        return {}
    rows = connection.execute(
        f"SELECT COALESCE(NULLIF(TRIM(status), ''), '<empty>') AS status, "
        f"COUNT(*) FROM {table} GROUP BY status ORDER BY status"
    ).fetchall()
    return {str(status): int(count) for status, count in rows}


def inspect_database_snapshot(
    snapshot_db: str | Path,
    *,
    require_manifest: bool = True,
) -> dict[str, Any]:
    snapshot = Path(snapshot_db).expanduser().resolve(strict=True)
    if not snapshot.is_file():
        raise DatabaseSnapshotError(f"snapshot is not a file: {snapshot}")

    manifest = verify_snapshot_manifest(snapshot) if require_manifest else None
    connection = sqlite3.connect(
        f"{snapshot.as_uri()}?mode=ro",
        uri=True,
        timeout=10,
        isolation_level=None,
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "missing_result"

        table_counts: dict[str, int | None] = {}
        for table in KNOWN_TABLES:
            table_counts[table] = (
                int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                if _table_exists(connection, table)
                else None
            )

        download_counts = _group_counts(connection, "downloads")
        work_counts = _group_counts(connection, "works")
        attention_states = {
            WorkStatus.PREPARING,
            WorkStatus.PREPARED,
            WorkStatus.QUEUED,
            WorkStatus.DOWNLOADING,
            WorkStatus.PAUSED,
            WorkStatus.RESUMING,
            WorkStatus.FAILED,
            WorkStatus.METADATA_FAILED,
            WorkStatus.PARTIAL,
        }
        active_or_attention = sum(
            count
            for status, count in download_counts.items()
            if WorkStatus.normalize(status) in attention_states
        )

        return {
            "snapshot_path": str(snapshot),
            "manifest_verified": manifest is not None,
            "created_at": manifest.get("created_at") if manifest else None,
            "integrity_check": integrity,
            "table_counts": table_counts,
            "download_status_counts": download_counts,
            "work_status_counts": work_counts,
            "active_or_attention_download_rows": active_or_attention,
        }
    finally:
        connection.close()
