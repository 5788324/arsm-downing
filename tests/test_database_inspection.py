from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from core.database_inspection import inspect_database_snapshot, verify_snapshot_manifest
from core.database_snapshot import DatabaseSnapshotError, create_database_snapshot

pytestmark = pytest.mark.portable


def _seed_app_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE works (rj_id TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE downloads (id TEXT PRIMARY KEY, rj_id TEXT, status TEXT);
            CREATE TABLE metadata_cache (rj_id TEXT PRIMARY KEY);
            CREATE TABLE library_items (rj_id TEXT PRIMARY KEY);
            CREATE TABLE library_index (id INTEGER PRIMARY KEY);
            """
        )
        connection.executemany(
            "INSERT INTO works(rj_id, status) VALUES (?, ?)",
            [
                ("RJ1", "completed"),
                ("RJ2", "failed"),
                ("RJ3", "paused"),
            ],
        )
        connection.executemany(
            "INSERT INTO downloads(id, rj_id, status) VALUES (?, ?, ?)",
            [
                ("1", "RJ1", "completed"),
                ("2", "RJ2", "failed"),
                ("3", "RJ3", "paused"),
                ("4", "RJ4", "downloading"),
                ("5", "RJ5", "queued"),
                ("6", "RJ6", "Paused (partial)"),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def test_inspection_reports_mixed_download_states(temp_db_path: Path, tmp_path: Path) -> None:
    _seed_app_database(temp_db_path)
    snapshot = tmp_path / "snapshot.db"
    create_database_snapshot(temp_db_path, snapshot)

    report = inspect_database_snapshot(snapshot)

    assert report["manifest_verified"] is True
    assert report["integrity_check"] == "ok"
    assert report["download_status_counts"] == {
        "completed": 1,
        "downloading": 1,
        "failed": 1,
        "paused": 1,
        "queued": 1,
        "Paused (partial)": 1,
    }
    assert report["active_or_attention_download_rows"] == 5
    assert report["table_counts"]["works"] == 3
    assert report["table_counts"]["downloads"] == 6


def test_manifest_verification_detects_tampering(temp_db_path: Path, tmp_path: Path) -> None:
    _seed_app_database(temp_db_path)
    snapshot = tmp_path / "snapshot.db"
    create_database_snapshot(temp_db_path, snapshot)
    snapshot.write_bytes(snapshot.read_bytes() + b"tamper")

    with pytest.raises(DatabaseSnapshotError, match="size does not match"):
        verify_snapshot_manifest(snapshot)


def test_inspection_requires_manifest_by_default(temp_db_path: Path) -> None:
    _seed_app_database(temp_db_path)
    with pytest.raises(DatabaseSnapshotError, match="manifest is missing"):
        inspect_database_snapshot(temp_db_path)


def test_unmanifested_inspection_is_available_only_by_explicit_api_flag(
    temp_db_path: Path,
) -> None:
    _seed_app_database(temp_db_path)
    report = inspect_database_snapshot(temp_db_path, require_manifest=False)
    assert report["manifest_verified"] is False
    assert report["integrity_check"] == "ok"
