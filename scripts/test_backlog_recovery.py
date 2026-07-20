"""Portable compatibility checks for backlog list/re-enable tools.

This script never opens a repository-root or live ``history.db``.  It builds a
small disposable database and report directory for every run.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.database import LibraryVault
from tools.backlog_list import run_backlog_list
from tools.backlog_reenable import dry_run, execute

passed = failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def add_download(vault: LibraryVault, rj_id: str, suffix: str, status: str, path: Path, size: int = 0) -> None:
    vault.execute_write(
        """INSERT INTO downloads
           (id,rj_id,track_title,local_path,status,downloaded_bytes,total_bytes,error,updated_at)
           VALUES (?,?,?,?,?,?,100,NULL,'2026-07-20T00:00:00')""",
        (f"{rj_id}:{suffix}", rj_id, suffix, str(path), status, size),
    )


print("=== Portable Backlog Recovery Compatibility ===\n")
with TemporaryDirectory(prefix="arsm_backlog_test_") as raw:
    root = Path(raw)
    db_path = root / "history.db"
    report_root = root / "reports"
    vault = LibraryVault(db_path)
    try:
        add_download(vault, "RJ01510133", "ignored", "ignored", root / "ignored.mp3")
        add_download(vault, "RJ01000002", "stale", "stale", root / "stale.mp3", 25)
        add_download(vault, "RJ01000002", "done", "completed", root / "done.mp3", 100)
    finally:
        vault.close()

    groups, summary, candidates = run_backlog_list(db_path=db_path, report_root=report_root)
    ids = {item["rj_id"] for item in candidates}
    check("product-specific RJ is not hidden", "RJ01510133" in ids)
    check("stale group exists", "mixed_backlog" in groups)
    check("ignored group exists", "ignored_backlog" in groups)
    check("mixed rows counted", next(item for item in candidates if item["rj_id"] == "RJ01000002")["completed_count"] == 1)
    check("reports are isolated", Path(summary["report_dir"]).is_relative_to(report_root))

    preview = dry_run(["RJ01000002"], db_path=db_path, mode="continue")
    detail = preview["would_update"][0]["details"][0]
    check("dry-run targets only stale/ignored", detail["old_status"] == "stale")
    check("continue preserves partial bytes", detail["new_downloaded_bytes"] == 25)
    check("dry-run is read-only", preview["dry_run"] is True)

    result = execute(
        ["RJ01000002"],
        db_path=db_path,
        mode="continue",
        backup_root=root / "backups",
    )
    check("execute updates one row", result["updated_rows"] == 1)
    check("SQLite backup exists", Path(result["sqlite_backup"]).exists())
    with sqlite3.connect(db_path) as conn:
        stale_status, stale_bytes = conn.execute(
            "SELECT status,downloaded_bytes FROM downloads WHERE id='RJ01000002:stale'"
        ).fetchone()
        completed_status = conn.execute(
            "SELECT status FROM downloads WHERE id='RJ01000002:done'"
        ).fetchone()[0]
    check("stale row queued with bytes preserved", (stale_status, stale_bytes) == ("queued", 25))
    check("completed row untouched", completed_status == "completed")

print(f"\n{'=' * 40}")
print(f"Results: {passed} passed, {failed} failed")
print(f"Overall: {'PASS' if failed == 0 else 'FAIL'}")
raise SystemExit(0 if failed == 0 else 1)
