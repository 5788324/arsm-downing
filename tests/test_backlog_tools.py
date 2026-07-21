from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from pathlib import Path

import pytest

from core.database import LibraryVault
from tools.backlog_list import run_backlog_list
from tools.backlog_reenable import dry_run, execute, load_rj_ids_from_file


def _work(vault: LibraryVault, rj_id: str, path: Path, status: str = "completed") -> None:
    path.mkdir(parents=True, exist_ok=True)
    vault.execute_write(
        """INSERT INTO works (rj_id,title,local_path,status,size_bytes)
           VALUES (?,?,?,?,0)""",
        (rj_id, f"Title {rj_id}", str(path), status),
    )


def _download(
    vault: LibraryVault,
    rj_id: str,
    suffix: str,
    status: str,
    local_path: Path,
    *,
    downloaded_bytes: int = 0,
    error: str | None = None,
) -> None:
    vault.execute_write(
        """INSERT INTO downloads
           (id,rj_id,track_title,local_path,status,downloaded_bytes,total_bytes,error,updated_at)
           VALUES (?,?,?,?,?,?,100,?,?)""",
        (
            f"{rj_id}:{suffix}",
            rj_id,
            suffix,
            str(local_path),
            status,
            downloaded_bytes,
            error,
            "2026-07-20T00:00:00",
        ),
    )


def test_backlog_list_counts_all_mixed_rows_and_has_no_hidden_rj(tmp_path: Path):
    db_path = tmp_path / "history.db"
    report_root = tmp_path / "reports"
    vault = LibraryVault(db_path)
    try:
        work_dir = tmp_path / "library" / "RJ01510133"
        _work(vault, "RJ01510133", work_dir)
        _download(vault, "RJ01510133", "stale", "stale", work_dir / "a.mp3", downloaded_bytes=12)
        _download(vault, "RJ01510133", "done", "completed", work_dir / "b.mp3", downloaded_bytes=100)

        mixed_dir = tmp_path / "library" / "RJ01000002"
        _work(vault, "RJ01000002", mixed_dir)
        _download(vault, "RJ01000002", "ignored", "ignored", mixed_dir / "a.mp3")
        _download(vault, "RJ01000002", "paused", "paused", mixed_dir / "b.mp3", downloaded_bytes=7)
    finally:
        vault.close()

    groups, summary, candidates = run_backlog_list(
        db_path=db_path,
        report_root=report_root,
        source="all",
        sort_by="rj_asc",
    )

    by_rj = {item["rj_id"]: item for item in candidates}
    assert set(by_rj) == {"RJ01510133", "RJ01000002"}
    assert by_rj["RJ01510133"]["downloads_total"] == 2
    assert by_rj["RJ01510133"]["completed_count"] == 1
    assert by_rj["RJ01000002"]["paused_count"] == 1
    assert by_rj["RJ01000002"]["recommended_action"] == "wait_until_runtime_idle"
    assert "runtime_review" in groups
    assert summary["total_download_rows"] == 4

    report_dir = Path(summary["report_dir"])
    assert report_dir.is_relative_to(report_root)
    payload = json.loads((report_dir / "backlog_recovery_candidates.json").read_text(encoding="utf-8"))
    assert payload["summary"]["total_candidate_rjs"] == 2


def test_backlog_list_explicit_exclusion_and_limit(tmp_path: Path):
    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    try:
        for idx in range(3):
            rj_id = f"RJ0100000{idx + 1}"
            work_dir = tmp_path / rj_id
            _work(vault, rj_id, work_dir)
            for row_idx in range(idx + 1):
                _download(vault, rj_id, str(row_idx), "ignored", work_dir / f"{row_idx}.mp3")
    finally:
        vault.close()

    _, summary, candidates = run_backlog_list(
        db_path=db_path,
        report_root=tmp_path / "reports",
        source="ignored",
        limit=1,
        sort_by="downloads_desc",
        exclude_rj_ids=["RJ01000003"],
    )
    assert [item["rj_id"] for item in candidates] == ["RJ01000002"]
    assert summary["excluded_rj_ids"] == ["RJ01000003"]


def test_backlog_dry_run_continue_preserves_bytes_and_closes_database(tmp_path: Path):
    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    try:
        local_path = tmp_path / "track.mp3"
        _download(vault, "RJ01000001", "stale", "stale", local_path, downloaded_bytes=37, error="network")
    finally:
        vault.close()

    result = dry_run(["RJ01000001"], db_path=db_path, mode="continue")
    detail = result["would_update"][0]["details"][0]
    assert detail["old_downloaded_bytes"] == 37
    assert detail["new_downloaded_bytes"] == 37
    assert result["totals"]["total_rows"] == 1

    # A write immediately after the read-only dry-run proves no leaked lock/connection.
    with closing(sqlite3.connect(db_path, timeout=1)) as conn:
        conn.execute("UPDATE downloads SET error='still-safe' WHERE id=?", ("RJ01000001:stale",))
        conn.commit()


def test_backlog_execute_requires_fully_idle_runtime_queue(tmp_path: Path):
    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    try:
        _download(vault, "RJ01000001", "stale", "stale", tmp_path / "a.mp3")
        _download(vault, "RJ01000002", "paused", "paused", tmp_path / "b.mp3", downloaded_bytes=9)
    finally:
        vault.close()

    with pytest.raises(RuntimeError, match="Runtime queue is not idle"):
        execute(
            ["RJ01000001"],
            db_path=db_path,
            backup_root=tmp_path / "backups",
        )
    assert not (tmp_path / "backups").exists()
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT status FROM downloads WHERE id='RJ01000001:stale'").fetchone()[0] == "stale"


def test_backlog_execute_continue_creates_verified_backup_and_preserves_other_rows(tmp_path: Path):
    db_path = tmp_path / "history.db"
    work_dir = tmp_path / "work"
    vault = LibraryVault(db_path)
    try:
        _work(vault, "RJ01000001", work_dir, status="completed")
        _download(
            vault,
            "RJ01000001",
            "stale",
            "stale",
            work_dir / "a.mp3",
            downloaded_bytes=41,
            error="can't resume",
        )
        _download(vault, "RJ01000001", "done", "completed", work_dir / "b.mp3", downloaded_bytes=100)
    finally:
        vault.close()

    result = execute(
        ["RJ01000001"],
        db_path=db_path,
        mode="continue",
        backup_root=tmp_path / "backups",
    )
    assert result["updated_rows"] == 1
    assert result["integrity_after"] == "ok"
    assert result["completed_unchanged"] is True
    assert result["works_unchanged"] is True

    backup_dir = Path(result["backup_dir"])
    assert (backup_dir / "history.before_reenable.db").exists()
    assert (backup_dir / "backlog_reenable_preimage.json").exists()
    rollback_sql = (backup_dir / "backlog_reenable_rollback.sql").read_text(encoding="utf-8")
    assert "can''t resume" in rollback_sql

    with closing(sqlite3.connect(db_path)) as conn:
        stale = conn.execute(
            "SELECT status,downloaded_bytes,error FROM downloads WHERE id='RJ01000001:stale'"
        ).fetchone()
        completed = conn.execute(
            "SELECT status FROM downloads WHERE id='RJ01000001:done'"
        ).fetchone()[0]
        work_status = conn.execute("SELECT status FROM works WHERE rj_id='RJ01000001'").fetchone()[0]
    assert stale == ("queued", 41, None)
    assert completed == "completed"
    assert work_status == "completed"


def test_retry_from_zero_is_blocked_when_part_file_exists(tmp_path: Path):
    db_path = tmp_path / "history.db"
    final_path = tmp_path / "track.mp3"
    part_path = Path(str(final_path) + ".part")
    part_path.write_bytes(b"partial")
    vault = LibraryVault(db_path)
    try:
        _download(vault, "RJ01000001", "stale", "stale", final_path, downloaded_bytes=7)
    finally:
        vault.close()

    with pytest.raises(RuntimeError, match=r"\.part files exist"):
        execute(
            ["RJ01000001"],
            db_path=db_path,
            mode="retry-from-zero",
            backup_root=tmp_path / "backups",
        )
    assert not (tmp_path / "backups").exists()


def test_load_rj_ids_from_file_ignores_comments_and_blank_lines(tmp_path: Path):
    path = tmp_path / "rjs.txt"
    path.write_text("# comment\nRJ01000001\n\nRJ01000002\n", encoding="utf-8")
    assert load_rj_ids_from_file(path) == ["RJ01000001", "RJ01000002"]
