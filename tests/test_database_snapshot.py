from __future__ import annotations

import json
import sqlite3
import threading
from unittest import mock
import time
from pathlib import Path

import pytest

from core.database_snapshot import DatabaseSnapshotError, create_database_snapshot

pytestmark = pytest.mark.portable


def _create_source(path: Path, *, rows: int = 3) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO events(value) VALUES (?)",
            [(f"value-{index}",) for index in range(rows)],
        )
        connection.commit()
    finally:
        connection.close()


def _count_rows(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    finally:
        connection.close()


def test_snapshot_copies_data_and_writes_verified_manifest(temp_db_path: Path, tmp_path: Path) -> None:
    _create_source(temp_db_path, rows=5)
    output = tmp_path / "snapshots" / "history.snapshot.db"

    result = create_database_snapshot(temp_db_path, output)

    assert output.exists()
    assert _count_rows(output) == 5
    assert result.integrity_check == "ok"
    assert len(result.snapshot_sha256) == 64
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["snapshot_sha256"] == result.snapshot_sha256
    assert manifest["snapshot_size"] == output.stat().st_size


def test_snapshot_does_not_modify_quiet_source(temp_db_path: Path, tmp_path: Path) -> None:
    _create_source(temp_db_path)
    before = temp_db_path.stat()

    create_database_snapshot(temp_db_path, tmp_path / "snapshot.db")

    after = temp_db_path.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns


def test_snapshot_refuses_overwrite_and_same_path(temp_db_path: Path, tmp_path: Path) -> None:
    _create_source(temp_db_path)
    output = tmp_path / "snapshot.db"
    output.write_bytes(b"existing")

    with pytest.raises(DatabaseSnapshotError, match="already exists"):
        create_database_snapshot(temp_db_path, output)
    with pytest.raises(DatabaseSnapshotError, match="must be different"):
        create_database_snapshot(temp_db_path, temp_db_path)


def test_snapshot_handles_concurrent_wal_writes(temp_db_path: Path, tmp_path: Path) -> None:
    _create_source(temp_db_path, rows=1)
    stop = threading.Event()
    started = threading.Event()

    def writer() -> None:
        connection = sqlite3.connect(temp_db_path, timeout=10)
        try:
            index = 0
            while not stop.is_set():
                connection.execute("INSERT INTO events(value) VALUES (?)", (f"live-{index}",))
                connection.commit()
                started.set()
                index += 1
                time.sleep(0.005)
        finally:
            connection.close()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    assert started.wait(timeout=5)
    try:
        output = tmp_path / "live.snapshot.db"
        result = create_database_snapshot(temp_db_path, output)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert result.integrity_check == "ok"
    assert _count_rows(output) >= 2
    connection = sqlite3.connect(output)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()



def test_manifest_install_failure_removes_unverified_snapshot(
    temp_db_path: Path, tmp_path: Path
) -> None:
    _create_source(temp_db_path)
    output = tmp_path / "snapshot.db"
    real_replace = __import__("os").replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected manifest install failure")
        return real_replace(source, destination)

    with mock.patch("core.database_snapshot.os.replace", side_effect=fail_second_replace):
        with pytest.raises(OSError, match="injected manifest"):
            create_database_snapshot(temp_db_path, output)

    assert not output.exists()
    assert not output.with_suffix(".db.manifest.json").exists()

def test_missing_source_does_not_create_output(tmp_path: Path) -> None:
    output = tmp_path / "snapshot.db"
    with pytest.raises(FileNotFoundError):
        create_database_snapshot(tmp_path / "missing.db", output)
    assert not output.exists()
