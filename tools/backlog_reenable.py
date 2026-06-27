"""Backlog re-enable: restore stale/ignored downloads to active queue.
Target status: 'queued' (matches prepare_work + resume_job).
Dry-run by default. --execute requires backup + preimage + rollback.
"""
import sqlite3
import json
import os
import sys
import argparse
import shutil
from pathlib import Path
from datetime import datetime

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

DB_PATH = Path("history.db")
TARGET_STATUS = "queued"  # matches prepare_work initial + resume_job target


def dry_run(rj_ids, mode="retry-from-zero"):
    """Show what WOULD happen, make no changes."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    results = {"dry_run": True, "rj_ids": rj_ids, "mode": mode, "would_update": [], "totals": {}}
    total_updates = 0
    for rj_id in rj_ids:
        rows = conn.execute(
            "SELECT id, rj_id, track_title, status, downloaded_bytes, total_bytes, error, local_path "
            "FROM downloads WHERE rj_id=? AND status IN ('stale','ignored')",
            (rj_id,)
        ).fetchall()

        rj_result = {"rj_id": rj_id, "count": len(rows), "details": []}
        for row in rows:
            new_bytes = row["downloaded_bytes"]
            new_error = None
            if mode == "retry-from-zero":
                new_bytes = 0
                new_error = None

            rj_result["details"].append({
                "id": row["id"],
                "track_title": row["track_title"],
                "old_status": row["status"],
                "new_status": TARGET_STATUS,
                "old_downloaded_bytes": row["downloaded_bytes"],
                "new_downloaded_bytes": new_bytes,
                "old_error": row["error"],
                "new_error": new_error,
            })
        total_updates += len(rows)
        results["would_update"].append(rj_result)

    results["totals"] = {
        "rjs": len(rj_ids),
        "total_rows": total_updates,
        "target_status": TARGET_STATUS,
        "mode": mode,
        "action": "UPDATE downloads SET status='queued', downloaded_bytes=0, error=NULL WHERE rj_id IN (...) AND status IN ('stale','ignored')",
    }

    conn.close()
    return results


def execute(rj_ids, mode="retry-from-zero"):
    """Execute the re-enable with backup, preimage, rollback, and post-verify."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(".local_backups") / f"backlog_reenable_{ts}"
    os.makedirs(backup_dir, exist_ok=True)

    # 1. Integrity check
    conn = sqlite3.connect(str(DB_PATH))
    integrity_before = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity_before.lower() != "ok":
        conn.close()
        print(f"FATAL: integrity_check = {integrity_before}")
        sys.exit(1)

    # 2. Backup
    shutil.copy2(DB_PATH, backup_dir / "history.before_reenable.db")
    for ext in [".db-shm", ".db-wal"]:
        p = Path(str(DB_PATH) + ext)
        if p.exists():
            shutil.copy2(p, backup_dir / p.name)

    temp_dir = Path(os.environ.get("TEMP", ".local_backups"))
    temp_backup = temp_dir / f"arsm_backlog_reenable_{ts}.db"
    dst = sqlite3.connect(str(temp_backup))
    conn.backup(dst)
    dst.close()
    ib = sqlite3.connect(str(temp_backup))
    backup_integrity = ib.execute("PRAGMA integrity_check").fetchone()[0]
    ib.close()

    # 3. Preimage
    rows = conn.execute(
        "SELECT id, rj_id, track_title, status, downloaded_bytes, total_bytes, error, updated_at, local_path "
        "FROM downloads WHERE rj_id IN ({}) AND status IN ('stale','ignored')".format(
            ",".join("?" * len(rj_ids))),
        rj_ids
    ).fetchall()

    preimage = {"rows": [dict(r) for r in rows], "count": len(rows), "backup_integrity": backup_integrity}
    (backup_dir / "backlog_reenable_preimage.json").write_text(json.dumps(preimage, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # 4. Rollback SQL
    rollback_path = backup_dir / "backlog_reenable_rollback.sql"
    with open(rollback_path, "w", encoding="utf-8") as f:
        f.write("-- Backlog re-enable rollback\nBEGIN;\n")
        for r in rows:
            f.write(f"UPDATE downloads SET status='{r['status']}', downloaded_bytes={r['downloaded_bytes']}, "
                    f"error={repr(r['error'])}, updated_at='{r['updated_at']}' WHERE id='{r['id'].replace(chr(39), chr(39)+chr(39))}';\n")
        f.write("COMMIT;\n")

    # 5. Snapshot counts before
    before_counts = {
        "stale": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='stale'").fetchone()[0],
        "ignored": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='ignored'").fetchone()[0],
        "completed": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='completed'").fetchone()[0],
        "queued": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='queued'").fetchone()[0],
        "works": dict(conn.execute("SELECT status, COUNT(*) FROM works GROUP BY status").fetchall()),
    }

    # 6. Execute UPDATE in single transaction
    try:
        conn.execute("BEGIN")
        now = datetime.now().isoformat(timespec="seconds")
        placeholders = ",".join("?" * len(rj_ids))

        if mode == "retry-from-zero":
            cur = conn.execute(
                f"UPDATE downloads SET status=?, downloaded_bytes=0, error=NULL, updated_at=? "
                f"WHERE rj_id IN ({placeholders}) AND status IN ('stale','ignored')",
                [TARGET_STATUS, now] + list(rj_ids)
            )
        else:
            cur = conn.execute(
                f"UPDATE downloads SET status=?, error=NULL, updated_at=? "
                f"WHERE rj_id IN ({placeholders}) AND status IN ('stale','ignored')",
                [TARGET_STATUS, now] + list(rj_ids)
            )

        updated_count = cur.rowcount
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"FATAL: {e}")
        sys.exit(1)

    # 7. Post-verify
    after_counts = {
        "stale": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='stale'").fetchone()[0],
        "ignored": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='ignored'").fetchone()[0],
        "completed": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='completed'").fetchone()[0],
        "queued": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='queued'").fetchone()[0],
        "works": dict(conn.execute("SELECT status, COUNT(*) FROM works GROUP BY status").fetchall()),
    }

    integrity_after = conn.execute("PRAGMA integrity_check").fetchone()[0]

    # Verify completed unchanged
    completed_ok = before_counts["completed"] == after_counts["completed"]
    works_ok = before_counts["works"] == after_counts["works"]
    stale_reduced = after_counts["stale"] <= before_counts["stale"]
    ignored_reduced = after_counts["ignored"] <= before_counts["ignored"]

    conn.close()

    actual = {
        "timestamp": now,
        "rj_ids": rj_ids,
        "mode": mode,
        "updated_count": updated_count,
        "integrity_before": integrity_before,
        "integrity_after": integrity_after,
        "counts_before": before_counts,
        "counts_after": after_counts,
        "completed_unchanged": completed_ok,
        "works_unchanged": works_ok,
        "stale_reduced": stale_reduced,
        "ignored_reduced": ignored_reduced,
        "backup_dir": str(backup_dir),
        "sqlite_backup": str(temp_backup),
        "rollback_sql": str(rollback_path),
    }

    (backup_dir / "backlog_reenable_actual_summary.json").write_text(
        json.dumps(actual, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    (backup_dir / "backlog_reenable_post_verify.json").write_text(
        json.dumps({"integrity_check": integrity_after, "completed_unchanged": completed_ok,
                    "works_unchanged": works_ok, "stale_reduced": stale_reduced, "ignored_reduced": ignored_reduced,
                    "verdict": "OK" if (integrity_after == "ok" and completed_ok and works_ok) else "FAIL"},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Updated: {updated_count} rows ({len(rj_ids)} RJs)")
    print(f"Integrity: {integrity_before} → {integrity_after}")
    print(f"Completed unchanged: {completed_ok}, Works unchanged: {works_ok}")
    print(f"Backup: {backup_dir}")
    return actual


def main():
    parser = argparse.ArgumentParser(description="Backlog re-enable tool")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default)")
    parser.add_argument("--execute", action="store_true", help="Actually write to DB")
    parser.add_argument("--rj", nargs="+", required=True, help="RJ IDs to re-enable")
    parser.add_argument("--limit", type=int, default=0, help="Max rows per RJ")
    parser.add_argument("--mode", choices=["retry-from-zero", "continue"], default="retry-from-zero",
                        help="retry-from-zero: reset downloaded_bytes to 0; continue: keep bytes for .part resume")
    args = parser.parse_args()

    rj_ids = args.rj

    if args.execute:
        print(f"EXECUTING: re-enable {len(rj_ids)} RJs (mode={args.mode})")
        execute(rj_ids, mode=args.mode)
    else:
        print(f"DRY-RUN: {len(rj_ids)} RJs (mode={args.mode})")
        results = dry_run(rj_ids, mode=args.mode)
        print(f"Would update {results['totals']['total_rows']} rows across {len(rj_ids)} RJs")
        for rj_result in results["would_update"]:
            print(f"  {rj_result['rj_id']}: {rj_result['count']} rows")
            for d in rj_result["details"][:3]:
                print(f"    {d['old_status']} → {d['new_status']} | {d['track_title'][:50] if d['track_title'] else '?'}")
            if rj_result["count"] > 3:
                print(f"    ... and {rj_result['count'] - 3} more")


if __name__ == "__main__":
    main()
