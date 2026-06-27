"""Backlog re-enable: restore stale/ignored downloads to active queue.
Target status: 'queued'. Supports --from-file, safety guards.
"""
import sqlite3, json, os, sys, argparse, shutil
from pathlib import Path
from datetime import datetime

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

DB_PATH = Path("history.db")
TARGET_STATUS = "queued"
MAX_BATCH_RJS = 100
MAX_EXISTING_QUEUED = 3000


def load_rj_ids_from_file(path):
    p = Path(path)
    if not p.exists():
        print(f"ERROR: file not found: {path}")
        sys.exit(1)
    rj_ids = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#")]
    return rj_ids


def safety_checks(conn, rj_ids, force_large, allow_large_queue):
    issues = []
    if len(rj_ids) > MAX_BATCH_RJS and not force_large:
        issues.append(f"Refusing batch of {len(rj_ids)} RJs (max {MAX_BATCH_RJS}). Use --force-large-batch to override.")
    existing_queued = conn.execute("SELECT COUNT(*) FROM downloads WHERE status='queued'").fetchone()[0]
    if existing_queued > MAX_EXISTING_QUEUED and not allow_large_queue:
        issues.append(f"Existing queued rows ({existing_queued}) > {MAX_EXISTING_QUEUED}. Use --allow-large-existing-queue to override.")
    if not rj_ids:
        issues.append("No RJ IDs provided.")
    return issues


def dry_run(rj_ids, mode="retry-from-zero"):
    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row
    results = {"dry_run": True, "rj_ids": rj_ids, "mode": mode, "would_update": [], "totals": {}}
    total = 0
    for rj_id in rj_ids:
        rows = conn.execute("SELECT id,rj_id,track_title,status,downloaded_bytes,total_bytes,error,local_path FROM downloads WHERE rj_id=? AND status IN ('stale','ignored')", (rj_id,)).fetchall()
        rj_result = {"rj_id": rj_id, "count": len(rows), "details": []}
        for r in rows:
            new_bytes = 0 if mode == "retry-from-zero" else r["downloaded_bytes"]
            rj_result["details"].append({"id": r["id"], "track_title": r["track_title"], "old_status": r["status"],
                "new_status": TARGET_STATUS, "old_downloaded_bytes": r["downloaded_bytes"],
                "new_downloaded_bytes": new_bytes, "old_error": r["error"], "new_error": None})
        total += len(rows); results["would_update"].append(rj_result)
    results["totals"] = {"rjs": len(rj_ids), "total_rows": total, "target_status": TARGET_STATUS, "mode": mode}
    conn.close()
    return results


def execute(rj_ids, mode="retry-from-zero"):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(".local_backups") / f"backlog_reenable_{ts}"
    os.makedirs(backup_dir, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row
    integrity_before = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity_before.lower() != "ok":
        conn.close(); print(f"FATAL: integrity={integrity_before}"); sys.exit(1)

    issues = safety_checks(conn, rj_ids, force_large=True, allow_large_queue=True)
    if issues:
        for i in issues: print(f"WARN: {i}")

    # Backup
    shutil.copy2(DB_PATH, backup_dir / "history.before_reenable.db")
    for ext in [".db-shm", ".db-wal"]:
        p = Path(str(DB_PATH) + ext)
        if p.exists(): shutil.copy2(p, backup_dir / p.name)

    temp_dir = Path(os.environ.get("TEMP", ".local_backups"))
    temp_backup = temp_dir / f"arsm_backlog_reenable_{ts}.db"
    dst = sqlite3.connect(str(temp_backup)); conn.backup(dst); dst.close()
    ib = sqlite3.connect(str(temp_backup)); backup_ok = ib.execute("PRAGMA integrity_check").fetchone()[0]; ib.close()

    # Preimage
    placeholders = ",".join("?" * len(rj_ids))
    rows = conn.execute(f"SELECT id,rj_id,track_title,status,downloaded_bytes,total_bytes,error,updated_at,local_path FROM downloads WHERE rj_id IN ({placeholders}) AND status IN ('stale','ignored')", rj_ids).fetchall()
    preimage_rows = [{"id": r["id"], "rj_id": r["rj_id"], "track_title": r["track_title"],
        "status": r["status"], "downloaded_bytes": r["downloaded_bytes"], "total_bytes": r["total_bytes"],
        "error": r["error"], "updated_at": str(r["updated_at"]), "local_path": r["local_path"]} for r in rows]
    (backup_dir / "backlog_reenable_preimage.json").write_text(json.dumps({"rows": preimage_rows, "count": len(rows), "backup_integrity": backup_ok}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # Rollback
    with open(backup_dir / "backlog_reenable_rollback.sql", "w", encoding="utf-8") as f:
        f.write("-- Rollback SQL\nBEGIN;\n")
        for r in rows:
            e = repr(r["error"]); rid = r["id"].replace("'", "''")
            f.write(f"UPDATE downloads SET status='{r['status']}', downloaded_bytes={r['downloaded_bytes']}, error={e}, updated_at='{r['updated_at']}' WHERE id='{rid}';\n")
        f.write("COMMIT;\n")

    # Before counts
    bc = {"stale": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='stale'").fetchone()[0],
          "ignored": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='ignored'").fetchone()[0],
          "completed": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='completed'").fetchone()[0],
          "queued": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='queued'").fetchone()[0],
          "works": dict(conn.execute("SELECT status, COUNT(*) FROM works GROUP BY status").fetchall())}

    # Execute
    try:
        conn.execute("BEGIN"); now = datetime.now().isoformat(timespec="seconds")
        if mode == "retry-from-zero":
            cur = conn.execute(f"UPDATE downloads SET status=?, downloaded_bytes=0, error=NULL, updated_at=? WHERE rj_id IN ({placeholders}) AND status IN ('stale','ignored')", [TARGET_STATUS, now] + rj_ids)
        else:
            cur = conn.execute(f"UPDATE downloads SET status=?, error=NULL, updated_at=? WHERE rj_id IN ({placeholders}) AND status IN ('stale','ignored')", [TARGET_STATUS, now] + rj_ids)
        updated = cur.rowcount; conn.commit()
    except Exception as e:
        conn.rollback(); conn.close(); print(f"FATAL: {e}"); sys.exit(1)

    # After counts
    ac = {"stale": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='stale'").fetchone()[0],
          "ignored": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='ignored'").fetchone()[0],
          "completed": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='completed'").fetchone()[0],
          "queued": conn.execute("SELECT COUNT(*) FROM downloads WHERE status='queued'").fetchone()[0],
          "works": dict(conn.execute("SELECT status, COUNT(*) FROM works GROUP BY status").fetchall())}
    integrity_after = conn.execute("PRAGMA integrity_check").fetchone()[0]; conn.close()

    actual = {"timestamp": now, "rj_count": len(rj_ids), "mode": mode, "updated_rows": updated,
              "integrity_before": integrity_before, "integrity_after": integrity_after,
              "counts_before": bc, "counts_after": ac,
              "completed_unchanged": bc["completed"] == ac["completed"],
              "works_unchanged": bc["works"] == ac["works"],
              "backup_dir": str(backup_dir), "sqlite_backup": str(temp_backup)}
    (backup_dir / "backlog_reenable_actual_summary.json").write_text(json.dumps(actual, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (backup_dir / "backlog_reenable_post_verify.json").write_text(json.dumps({"integrity": integrity_after, "completed_ok": actual["completed_unchanged"], "works_ok": actual["works_unchanged"], "verdict": "OK" if integrity_after == "ok" and actual["completed_unchanged"] and actual["works_unchanged"] else "FAIL"}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Updated: {updated} rows ({len(rj_ids)} RJs)")
    print(f"Integrity: {integrity_before} -> {integrity_after}")
    print(f"Completed: {bc['completed']} -> {ac['completed']} (ok={actual['completed_unchanged']})")
    print(f"Works: ok={actual['works_unchanged']}")
    return actual


def main():
    p = argparse.ArgumentParser(description="Backlog re-enable tool")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--rj", nargs="+", help="RJ IDs to re-enable")
    g.add_argument("--from-file", type=str, help="File with RJ IDs (one per line)")
    p.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default)")
    p.add_argument("--execute", action="store_true", help="Actually write to DB")
    p.add_argument("--mode", choices=["retry-from-zero","continue"], default="retry-from-zero")
    p.add_argument("--force-large-batch", action="store_true", help=f"Allow >{MAX_BATCH_RJS} RJs")
    p.add_argument("--allow-large-existing-queue", action="store_true", help=f"Allow >{MAX_EXISTING_QUEUED} queued rows")
    args = p.parse_args()

    if args.from_file:
        rj_ids = load_rj_ids_from_file(args.from_file)
    else:
        rj_ids = args.rj or []

    if args.execute:
        conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row
        issues = safety_checks(conn, rj_ids, args.force_large_batch, args.allow_large_existing_queue)
        conn.close()
        if issues:
            for i in issues: print(f"BLOCKED: {i}")
            sys.exit(1)
        print(f"EXECUTING: {len(rj_ids)} RJs (mode={args.mode})")
        execute(rj_ids, mode=args.mode)
    else:
        results = dry_run(rj_ids, mode=args.mode)
        print(f"DRY-RUN: {len(rj_ids)} RJs, {results['totals']['total_rows']} rows")
        for r in results["would_update"][:5]:
            print(f"  {r['rj_id']}: {r['count']} rows {r['details'][0]['old_status']}->{r['details'][0]['new_status']}" if r['details'] else f"  {r['rj_id']}: 0 rows")
        if len(results["would_update"]) > 5:
            print(f"  ... and {len(results)-5} more RJs")


if __name__ == "__main__":
    main()
