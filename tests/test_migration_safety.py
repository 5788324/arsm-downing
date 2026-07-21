from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from core.database import LibraryVault
from core.migration import MigrationEngine
from core.migration_manifest import (
    MigrationManifestError,
    build_migration_manifest,
    compare_manifest_to_tree,
)
from core.models import WorkMetadata


def _metadata(rj_id: str) -> WorkMetadata:
    return WorkMetadata(
        rj_id=rj_id,
        title="Migration Test",
        circle="",
        cv=[],
        tags=[],
        price=0,
        source_url="",
        dl_count=0,
        rating=0.0,
        release_date="",
        cover_url="",
    )


def _registered_work(tmp_path: Path, rj_id: str = "RJ01000001"):
    source = tmp_path / "source" / rj_id
    target_base = tmp_path / "target"
    target = target_base / rj_id
    (source / "nested").mkdir(parents=True)
    (source / "track.mp3").write_bytes(b"a" * 64)
    (source / "nested" / "meta.json").write_text('{"ok": true}', encoding="utf-8")
    vault = LibraryVault(tmp_path / "history.db")
    vault.register(_metadata(rj_id), 1, source, status="completed")
    vault.upsert_download(
        f"{rj_id}:track", rj_id, "track", str(source / "track.mp3"),
        "registered", 64, 64,
    )
    vault.execute_write(
        """INSERT OR REPLACE INTO library_items
           (rj_id,folder_path,folder_name,total_files,total_size)
           VALUES (?,?,?,?,?)""",
        (rj_id, str(source), source.name, 2, 76),
    )
    vault.execute_write(
        """INSERT INTO library_index
           (rj_id,library_path,work_dir,status,size_bytes,file_count)
           VALUES (?,?,?,'found',?,?)""",
        (rj_id, str(source.parent), str(source), 76, 2),
    )
    return vault, source, target_base, target


def test_manifest_compares_relative_paths_sizes_and_hashes(tmp_path: Path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "a").mkdir(parents=True)
    (source / "a" / "same.bin").write_bytes(b"abc")
    destination.mkdir()
    (destination / "same.bin").write_bytes(b"abc")
    manifest = build_migration_manifest(source)
    ok, issues = compare_manifest_to_tree(manifest, destination)
    assert ok is False
    assert "missing_file:a/same.bin" in issues
    assert "unexpected_file:same.bin" in issues


def test_manifest_rejects_nested_part_file(tmp_path: Path):
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "track.mp3.part").write_bytes(b"partial")
    with pytest.raises(MigrationManifestError, match="partial download"):
        build_migration_manifest(source)


def test_scan_candidates_uses_actual_disk_size(tmp_path: Path):
    vault, source, target_base, _ = _registered_work(tmp_path)
    try:
        vault.execute_write(
            "UPDATE works SET size_bytes=999999 WHERE rj_id='RJ01000001'"
        )
        dry = MigrationEngine(vault).dry_run(str(target_base))
        candidate = dry["candidates"][0]
        assert candidate["size_bytes"] == 76
        assert dry["total_size_bytes"] == 76
        assert candidate["db_size_bytes"] == 999999
    finally:
        vault.close()


def test_migration_updates_all_path_tables_and_deletes_source(tmp_path: Path):
    vault, source, target_base, target = _registered_work(tmp_path)
    try:
        result = MigrationEngine(vault).migrate_one(
            "RJ01000001", str(source), str(target), target_base=str(target_base)
        )
        assert result["success"] is True, result
        assert result["source_removed"] is True
        assert not source.exists()
        assert target.is_dir()
        assert vault.conn.execute(
            "SELECT local_path FROM works WHERE rj_id='RJ01000001'"
        ).fetchone()[0] == str(target)
        assert vault.conn.execute(
            "SELECT local_path FROM downloads WHERE rj_id='RJ01000001'"
        ).fetchone()[0] == str(target / "track.mp3")
        assert vault.conn.execute(
            "SELECT folder_path FROM library_items WHERE rj_id='RJ01000001'"
        ).fetchone()[0] == str(target)
        index = vault.conn.execute(
            "SELECT library_path,work_dir FROM library_index WHERE rj_id='RJ01000001'"
        ).fetchone()
        assert tuple(index) == (str(target_base), str(target))
    finally:
        vault.close()


def test_db_failure_removes_target_and_preserves_source(tmp_path: Path, monkeypatch):
    vault, source, target_base, target = _registered_work(tmp_path)
    monkeypatch.setattr(
        vault,
        "update_external_intake_paths",
        lambda *args, **kwargs: {"success": False, "error": "forced", "error_code": "forced"},
    )
    try:
        result = MigrationEngine(vault).migrate_one(
            "RJ01000001", str(source), str(target), target_base=str(target_base)
        )
        assert result["success"] is False
        assert result["stage"] == "db_update"
        assert result["rollback_performed"] is True
        assert source.is_dir()
        assert not target.exists()
    finally:
        vault.close()


def test_source_delete_failure_rolls_back_when_source_is_intact(tmp_path: Path, monkeypatch):
    vault, source, target_base, target = _registered_work(tmp_path)
    engine = MigrationEngine(vault)

    def fail_delete(path: str) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(engine, "_delete_source_tree", fail_delete)
    try:
        result = engine.migrate_one(
            "RJ01000001", str(source), str(target), target_base=str(target_base)
        )
        assert result["success"] is False
        assert result["error_code"] == "source_delete_failed_rolled_back"
        assert result["rollback_performed"] is True
        assert source.is_dir()
        assert not target.exists()
        assert vault.conn.execute(
            "SELECT local_path FROM works WHERE rj_id='RJ01000001'"
        ).fetchone()[0] == str(source)
    finally:
        vault.close()


def test_source_delete_partial_failure_requires_stop(tmp_path: Path, monkeypatch):
    vault, source, target_base, target = _registered_work(tmp_path)
    engine = MigrationEngine(vault)

    def partial_delete(path: str) -> None:
        (Path(path) / "track.mp3").unlink()
        raise PermissionError("partially deleted")

    monkeypatch.setattr(engine, "_delete_source_tree", partial_delete)
    try:
        result = engine.migrate_one(
            "RJ01000001", str(source), str(target), target_base=str(target_base)
        )
        assert result["success"] is False
        assert result["stop_required"] is True
        assert result["error_code"] == "source_delete_partial_failure"
        assert target.is_dir()
        assert vault.conn.execute(
            "SELECT local_path FROM works WHERE rj_id='RJ01000001'"
        ).fetchone()[0] == str(target)
    finally:
        vault.close()


def test_existing_empty_target_is_not_deleted(tmp_path: Path):
    vault, source, target_base, target = _registered_work(tmp_path)
    target.mkdir(parents=True)
    marker = target / ".owner"
    marker.write_text("keep", encoding="utf-8")
    try:
        result = MigrationEngine(vault).migrate_one(
            "RJ01000001", str(source), str(target), target_base=str(target_base)
        )
        assert result["success"] is False
        assert result["error_code"] == "target_exists"
        assert marker.read_text(encoding="utf-8") == "keep"
    finally:
        vault.close()


def test_cleanup_plan_is_upserted_not_duplicated(tmp_path: Path, monkeypatch):
    vault, source, target_base, target = _registered_work(tmp_path)
    cleanup = tmp_path / "migration_cleanup_plan.jsonl"
    monkeypatch.setattr(MigrationEngine, "CLEANUP_PLAN_FILE", cleanup)
    try:
        result = MigrationEngine(vault).migrate_one(
            "RJ01000001", str(source), str(target), delete_source=False,
            target_base=str(target_base),
        )
        assert result["success"] is True
        # Simulate a second write for the same RJ and verify a single canonical entry.
        MigrationEngine._append_cleanup_plan(
            {
                "rj_id": "RJ01000001",
                "source": str(source),
                "target": str(target),
                "status": "source_preserved",
                "migrated_at": "later",
                "verified": True,
                "delete_allowed_after_full_verification": True,
            }
        )
        entries = [json.loads(line) for line in cleanup.read_text(encoding="utf-8").splitlines()]
        assert len(entries) == 1
        assert entries[0]["migrated_at"] == "later"
    finally:
        vault.close()

def test_plan_token_rejects_source_changed_after_dry_run(tmp_path: Path):
    vault, source, target_base, target = _registered_work(tmp_path)
    try:
        dry = MigrationEngine(vault).dry_run(str(target_base))
        token = dry["candidates"][0]["manifest_token"]
        (source / "late.bin").write_bytes(b"late")
        result = MigrationEngine(vault).migrate_one(
            "RJ01000001",
            str(source),
            str(target),
            target_base=str(target_base),
            expected_manifest_token=token,
        )
        assert result["success"] is False
        assert result["error_code"] == "source_plan_changed"
        assert source.is_dir()
        assert not target.exists()
    finally:
        vault.close()


def test_final_target_verification_failure_removes_uncommitted_target(
    tmp_path: Path, monkeypatch
):
    vault, source, target_base, target = _registered_work(tmp_path)
    engine = MigrationEngine(vault)
    original_compare = __import__("core.migration", fromlist=["compare_manifest_to_tree"]).compare_manifest_to_tree
    calls = {"count": 0}

    def fail_second_compare(manifest, root, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            return False, ["hash_mismatch:track.mp3"]
        return original_compare(manifest, root, **kwargs)

    monkeypatch.setattr("core.migration.compare_manifest_to_tree", fail_second_compare)
    try:
        result = engine.migrate_one(
            "RJ01000001", str(source), str(target), target_base=str(target_base)
        )
        assert result["success"] is False
        assert result["error_code"] == "target_verification_failed"
        assert source.is_dir()
        assert not target.exists()
    finally:
        vault.close()

@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_manifest_rejects_symlink_source_root(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "track.mp3").write_bytes(b"audio")
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(MigrationManifestError, match="source root is a symlink"):
        build_migration_manifest(link)


def test_direct_migration_rejects_resuming_download(tmp_path: Path):
    vault, source, target_base, target = _registered_work(tmp_path)
    try:
        vault.execute_write(
            "UPDATE downloads SET status='resuming' WHERE rj_id='RJ01000001'"
        )
        result = MigrationEngine(vault).migrate_one(
            "RJ01000001", str(source), str(target), target_base=str(target_base)
        )
        assert result["success"] is False
        assert result["error_code"] == "pending_downloads"
        assert source.is_dir()
        assert not target.exists()
    finally:
        vault.close()


def test_keep_source_verify_uses_cleanup_plan_exact_source_path(tmp_path: Path, monkeypatch):
    vault, source, target_base, _ = _registered_work(tmp_path)
    target = target_base / "Renamed Target"
    cleanup = tmp_path / "migration_cleanup_plan.jsonl"
    monkeypatch.setattr(MigrationEngine, "CLEANUP_PLAN_FILE", cleanup)
    try:
        result = MigrationEngine(vault).migrate_one(
            "RJ01000001",
            str(source),
            str(target),
            delete_source=False,
            target_base=str(target_base),
        )
        assert result["success"] is True
        verified = MigrationEngine(vault).verify_migrated_work(
            "RJ01000001", str(target_base), source_roots=[str(source.parent)]
        )
        assert verified["success"] is True, verified
        assert verified["source_preserved"] is True
        assert any(item["path"] == str(source) for item in verified["source_details"])
    finally:
        vault.close()
