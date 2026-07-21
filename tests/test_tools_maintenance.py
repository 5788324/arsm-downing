from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.database import LibraryVault
from core.tools_maintenance import (
    cleanup_metadata_cache,
    preview_metadata_cache_cleanup,
    preview_queue_cleanup,
    preview_vacuum,
    vacuum_database,
)


def _cache_row(vault: LibraryVault, rj_id: str, fetched_at: str) -> None:
    vault.execute_write(
        """INSERT INTO metadata_cache
           (rj_id,title,circle,cover_url,metadata_json,tracks_json,fetched_at,updated_at)
           VALUES (?,?,'','','{}','[]',?,NULL)""",
        (rj_id, rj_id, fetched_at),
    )


def _download(vault: LibraryVault, rj_id: str, status: str) -> None:
    vault.execute_write(
        """INSERT INTO downloads
           (id,rj_id,track_title,status,downloaded_bytes,total_bytes)
           VALUES (?,?,'track',?,0,10)""",
        (f"{rj_id}:{status}", rj_id, status),
    )


def test_cache_cleanup_preserves_expired_cache_for_paused_or_failed_tasks(tmp_path: Path):
    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    try:
        old = "2025-01-01T00:00:00"
        _cache_row(vault, "RJ01000001", old)
        _cache_row(vault, "RJ01000002", old)
        _cache_row(vault, "RJ01000003", old)
        _download(vault, "RJ01000001", "paused")
        _download(vault, "RJ01000002", "failed")
    finally:
        vault.close()

    preview = preview_metadata_cache_cleanup(
        db_path, now=datetime(2026, 7, 20, tzinfo=timezone.utc)
    )
    assert preview.expired_rows == 3
    assert preview.protected_expired_rows == 2
    assert preview.candidate_rj_ids == ("RJ01000003",)

    result = cleanup_metadata_cache(
        db_path,
        preview_token=preview.preview_token,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    assert result["success"] is True
    assert result["deleted_rows"] == 1
    with closing(sqlite3.connect(db_path)) as conn:
        remaining = {row[0] for row in conn.execute("SELECT rj_id FROM metadata_cache")}
    assert remaining == {"RJ01000001", "RJ01000002"}


def test_cache_cleanup_rejects_stale_preview_token(tmp_path: Path):
    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    try:
        _cache_row(vault, "RJ01000001", "2025-01-01T00:00:00")
    finally:
        vault.close()
    first = preview_metadata_cache_cleanup(
        db_path, now=datetime(2026, 7, 20, tzinfo=timezone.utc)
    )
    vault = LibraryVault(db_path)
    try:
        _cache_row(vault, "RJ01000002", "2025-01-01T00:00:00")
    finally:
        vault.close()
    result = cleanup_metadata_cache(
        db_path,
        preview_token=first.preview_token,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    assert result["success"] is False
    assert result["error_code"] == "preview_changed"


def test_queue_cleanup_preview_is_blocked_by_mixed_active_tasks(tmp_path: Path):
    db_path = tmp_path / "history.db"
    queue_path = tmp_path / "queue.json"
    vault = LibraryVault(db_path)
    try:
        _download(vault, "RJ01000001", "completed")
        _download(vault, "RJ01000002", "paused")
        _download(vault, "RJ01000003", "failed")
    finally:
        vault.close()
    queue_path.write_text(
        json.dumps(
            {
                "01000001": {"status": "已完成"},
                "01000002": {"status": "Paused"},
            }
        ),
        encoding="utf-8",
    )
    preview = preview_queue_cleanup(db_path, queue_path)
    assert preview.blocked is True
    assert preview.active_download_rows == 2
    assert preview.terminal_db_rows == 1
    assert preview.terminal_queue_items == 1


def test_vacuum_refuses_when_resumable_tasks_exist(tmp_path: Path):
    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    try:
        _download(vault, "RJ01000001", "queued")
    finally:
        vault.close()
    preview = preview_vacuum(db_path)
    assert preview["blocked"] is True
    result = vacuum_database(db_path)
    assert result["success"] is False
    assert result["error_code"] == "active_or_resumable_downloads_present"


def test_vacuum_runs_on_idle_database(tmp_path: Path):
    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    vault.close()
    result = vacuum_database(db_path)
    assert result["success"] is True
    assert result["size_after"] > 0


def test_backlog_preview_has_no_product_specific_exclusion(tmp_path: Path):
    from core.tools_maintenance import preview_backlog_candidates

    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    try:
        _download(vault, "RJ01510133", "ignored")
        _download(vault, "RJ01000002", "ignored")
        _download(vault, "RJ01000002", "stale")
    finally:
        vault.close()
    preview = preview_backlog_candidates(db_path, source="ignored", limit=30)
    assert set(preview["rj_ids"]) == {"RJ01510133", "RJ01000002"}
    assert preview["source_rows"] == 2
    assert preview["actual_total"] == 3


def test_backlog_summary_counts_mixed_runtime_states(tmp_path: Path):
    from core.tools_maintenance import get_backlog_summary

    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    try:
        _download(vault, "RJ01000001", "stale")
        _download(vault, "RJ01000001", "ignored")
        _download(vault, "RJ01000002", "paused")
        _download(vault, "RJ01000003", "failed")
        _download(vault, "RJ01000004", "downloading")
    finally:
        vault.close()
    summary = get_backlog_summary(db_path)
    assert summary == {
        "stale_rjs": 1,
        "stale_rows": 1,
        "ignored_rjs": 1,
        "ignored_rows": 1,
        "queued_rows": 0,
        "paused_rows": 1,
        "failed_rows": 1,
        "running_rows": 1,
    }


def test_failed_diagnostic_recognizes_partials_and_metadata_retry(tmp_path: Path):
    from core.tools_maintenance import diagnose_download_failures

    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    try:
        partial_final = tmp_path / "partial.mp3"
        Path(str(partial_final) + ".part").write_bytes(b"12345")
        vault.execute_write(
            """INSERT INTO downloads
               (id,rj_id,track_title,local_path,status,downloaded_bytes,total_bytes,error)
               VALUES ('partial','RJ01000001','track',?,'failed',5,10,'network: timeout')""",
            (str(partial_final),),
        )
        _cache_row(vault, "RJ01000002", "2026-07-20T00:00:00")
        vault.execute_write(
            """INSERT INTO downloads
               (id,rj_id,track_title,local_path,status,downloaded_bytes,total_bytes,error)
               VALUES ('retry','RJ01000002','track',?,'failed',0,10,'missing')""",
            (str(tmp_path / "missing.mp3"),),
        )
        paused_final = tmp_path / "paused.mp3"
        Path(str(paused_final) + ".part").write_bytes(b"part")
        vault.execute_write(
            """INSERT INTO downloads
               (id,rj_id,track_title,local_path,status,downloaded_bytes,total_bytes)
               VALUES ('paused','RJ01000003','track',?,'paused',4,10)""",
            (str(paused_final),),
        )
    finally:
        vault.close()

    result = diagnose_download_failures(db_path)
    assert result["failed_total"] == 2
    assert result["failed_resumable_partial_file"] == 1
    assert result["failed_retry_from_zero"] == 1
    assert result["paused_resumable"] == 1
    assert result["per_error_prefix"]["network"] == 1
