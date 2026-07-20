from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from core.database import LibraryVault
from core.library_rebuild import LibraryScanError, scan_library_snapshot


def make_work(root: Path, name: str, files: dict[str, bytes]) -> Path:
    work = root / name
    for relative, content in files.items():
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return work


def test_snapshot_scans_nested_rj_and_file_categories(tmp_path: Path) -> None:
    root = tmp_path / "library"
    work = make_work(
        root / "group",
        "RJ01234567 Demo",
        {
            "audio/track.mp3": b"a" * 10,
            "cover.jpg": b"b" * 5,
            "clip.mp4": b"c" * 7,
            "note.txt": b"d" * 3,
        },
    )

    snapshot = scan_library_snapshot([root])

    assert snapshot.unique_rj_count == 1
    entry = snapshot.entries[0]
    assert Path(entry.work_dir) == work
    assert entry.total_files == 4
    assert entry.total_size == 25
    assert entry.audio_count == 1
    assert entry.image_count == 1
    assert entry.video_count == 1
    assert entry.other_count == 1
    assert entry.has_audio == 1
    assert entry.has_cover == 1
    assert entry.warnings == ()


def test_rebuild_replaces_stale_indexes_and_syncs_work_tables(tmp_path: Path) -> None:
    root = tmp_path / "library"
    work = make_work(root, "RJ01000001 New", {"track.mp3": b"x" * 9})
    vault = LibraryVault(tmp_path / "history.db")
    try:
        vault.execute_write(
            """INSERT INTO library_index
               (rj_id,library_path,work_dir,status,size_bytes,file_count,scanned_at)
               VALUES ('RJ09999999','old','old/work','found',1,1,'old')"""
        )
        vault.execute_write(
            """INSERT INTO library_items
               (rj_id,folder_path,folder_name,total_files,total_size)
               VALUES ('RJ09999999','old/work','old',1,1)"""
        )
        vault.execute_write(
            """INSERT INTO works(rj_id,title,local_path,status)
               VALUES ('RJ09999999','Old',?,'external')""",
            (str(root / "RJ09999999 Old"),),
        )

        result = vault.rebuild_library([str(root)])

        assert result["success"] is True
        assert result["found"] == 1
        assert result["indexed"] == 1
        assert result["removed_index"] == 1
        index_rows = vault.conn.execute(
            "SELECT rj_id,work_dir FROM library_index"
        ).fetchall()
        assert [(row["rj_id"], Path(row["work_dir"])) for row in index_rows] == [
            ("RJ01000001", work)
        ]
        item = vault.conn.execute(
            "SELECT * FROM library_items WHERE rj_id='RJ01000001'"
        ).fetchone()
        assert item and Path(item["folder_path"]) == work
        assert json.loads(item["warnings_json"]) == ["no_cover"]
        new_work = vault.conn.execute(
            "SELECT local_path,status,size_bytes FROM works WHERE rj_id='RJ01000001'"
        ).fetchone()
        assert Path(new_work["local_path"]) == work
        assert new_work["status"] == "external"
        assert new_work["size_bytes"] == 9
        stale = vault.conn.execute(
            "SELECT status FROM works WHERE rj_id='RJ09999999'"
        ).fetchone()
        assert stale["status"] == "missing"
    finally:
        vault.close()


def test_duplicate_rj_prefers_existing_primary_path(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    duplicate_a = make_work(root_a, "RJ01000002 A", {"a.mp3": b"a"})
    duplicate_b = make_work(root_b, "RJ01000002 B", {"b.mp3": b"b"})
    vault = LibraryVault(tmp_path / "history.db")
    try:
        vault.execute_write(
            "INSERT INTO works(rj_id,title,local_path,status) VALUES (?,?,?,'external')",
            ("RJ01000002", "Duplicate", str(duplicate_b)),
        )
        result = vault.rebuild_library([str(root_a), str(root_b)])
        assert result["success"] is True
        assert result["entries"] == 2
        item = vault.conn.execute(
            "SELECT folder_path,warnings_json FROM library_items WHERE rj_id='RJ01000002'"
        ).fetchone()
        assert Path(item["folder_path"]) == duplicate_b
        assert "duplicate_rj" in json.loads(item["warnings_json"])
        assert vault.conn.execute(
            "SELECT COUNT(*) FROM library_index WHERE rj_id='RJ01000002'"
        ).fetchone()[0] == 2
    finally:
        vault.close()


def test_active_download_preserves_existing_work_path(tmp_path: Path) -> None:
    root = tmp_path / "library"
    discovered = make_work(root, "RJ01000003 New", {"track.mp3": b"x"})
    old_path = tmp_path / "active-download-output"
    vault = LibraryVault(tmp_path / "history.db")
    try:
        vault.execute_write(
            "INSERT INTO works(rj_id,title,local_path,status) VALUES (?,?,?,'external')",
            ("RJ01000003", "Active", str(old_path)),
        )
        vault.execute_write(
            """INSERT INTO downloads(id,rj_id,status,local_path)
               VALUES ('d1','RJ01000003','paused',?)""",
            (str(old_path / "track.mp3"),),
        )
        result = vault.rebuild_library([str(root)])
        assert result["success"] is True
        work = vault.conn.execute(
            "SELECT local_path,status FROM works WHERE rj_id='RJ01000003'"
        ).fetchone()
        assert Path(work["local_path"]) == old_path
        assert work["status"] == "external"
        item = vault.conn.execute(
            "SELECT folder_path FROM library_items WHERE rj_id='RJ01000003'"
        ).fetchone()
        assert Path(item["folder_path"]) == discovered
    finally:
        vault.close()


def test_scan_failure_preserves_previous_indexes(tmp_path: Path, monkeypatch) -> None:
    vault = LibraryVault(tmp_path / "history.db")
    try:
        vault.execute_write(
            """INSERT INTO library_index
               (rj_id,library_path,work_dir,status,size_bytes,file_count,scanned_at)
               VALUES ('RJ01000004','old','old/work','found',1,1,'old')"""
        )
        monkeypatch.setattr(
            "core.database.scan_library_snapshot",
            lambda _paths: (_ for _ in ()).throw(LibraryScanError("interrupted")),
        )
        result = vault.rebuild_library([str(tmp_path)])
        assert result["success"] is False
        assert "interrupted" in result["error"]
        assert vault.conn.execute(
            "SELECT COUNT(*) FROM library_index WHERE rj_id='RJ01000004'"
        ).fetchone()[0] == 1
    finally:
        vault.close()


def test_database_failure_rolls_back_full_rebuild(tmp_path: Path) -> None:
    root = tmp_path / "library"
    make_work(root, "RJ01000005 New", {"track.mp3": b"x"})
    vault = LibraryVault(tmp_path / "history.db")
    try:
        vault.execute_write(
            """INSERT INTO library_index
               (rj_id,library_path,work_dir,status,size_bytes,file_count,scanned_at)
               VALUES ('RJ01000006','old','old/work','found',1,1,'old')"""
        )
        vault.execute_write(
            """CREATE TRIGGER reject_new_library_item
               BEFORE INSERT ON library_items
               BEGIN SELECT RAISE(ABORT, 'injected rebuild failure'); END"""
        )
        result = vault.rebuild_library([str(root)])
        assert result["success"] is False
        assert "injected rebuild failure" in result["error"]
        rows = vault.conn.execute(
            "SELECT rj_id,work_dir FROM library_index"
        ).fetchall()
        assert [(row["rj_id"], row["work_dir"]) for row in rows] == [
            ("RJ01000006", "old/work")
        ]
        assert vault.conn.execute("SELECT COUNT(*) FROM library_items").fetchone()[0] == 0
    finally:
        vault.close()


def test_recursive_metadata_verification(tmp_path: Path) -> None:
    work = make_work(tmp_path, "RJ01000007 Work", {"chapter/inner.mp3": b"x"})
    vault = LibraryVault(tmp_path / "history.db")
    try:
        vault.execute_write(
            "INSERT INTO works(rj_id,title,local_path,status) VALUES (?,?,?,'external')",
            ("RJ01000007", "Nested", str(work)),
        )
        tracks = [{
            "type": "folder",
            "title": "Chapter",
            "children": [{
                "type": "folder",
                "children": [{"type": "audio", "title": "inner.mp3"}],
            }],
        }]
        assert vault.verify_library_item("RJ01000007", str(work), tracks) == "verified"
        (work / "chapter" / "inner.mp3").unlink()
        assert vault.verify_library_item("RJ01000007", str(work), tracks) == "partial"
    finally:
        vault.close()


def test_directory_disappearing_after_scan_preserves_old_indexes(
    tmp_path: Path, monkeypatch
) -> None:
    from core.library_rebuild import LibraryScanEntry, LibraryScanSnapshot

    vault = LibraryVault(tmp_path / "history.db")
    try:
        vault.execute_write(
            """INSERT INTO library_index
               (rj_id,library_path,work_dir,status,size_bytes,file_count,scanned_at)
               VALUES ('RJ01000008','old','old/work','found',1,1,'old')"""
        )
        missing = tmp_path / "vanished" / "RJ01000009"
        snapshot = LibraryScanSnapshot(
            run_id="changed",
            scanned_at="2026-07-20T00:00:00",
            roots=(str(tmp_path),),
            entries=(LibraryScanEntry(
                rj_id="RJ01000009",
                library_path=str(tmp_path),
                work_dir=str(missing),
                folder_name=missing.name,
                total_files=1,
                total_size=1,
                audio_count=1,
                image_count=0,
                video_count=0,
                other_count=0,
                has_audio=1,
                has_cover=0,
            ),),
        )
        monkeypatch.setattr("core.database.scan_library_snapshot", lambda _paths: snapshot)
        result = vault.rebuild_library([str(tmp_path)])
        assert result["success"] is False
        assert result["error"].startswith("scan_changed:")
        assert vault.conn.execute(
            "SELECT COUNT(*) FROM library_index WHERE rj_id='RJ01000008'"
        ).fetchone()[0] == 1
    finally:
        vault.close()
