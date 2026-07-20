"""Auditable stale/ignored download re-enable utility."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

DB_PATH = Path("history.db")
TARGET_STATUS = "queued"
MAX_BATCH_RJS = 100
RUNTIME_ACTIVE_STATUSES = ('queued', 'downloading', 'resuming', 'paused', 'failed')


def load_rj_ids_from_file(path: str | Path) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    return [
        line.strip()
        for line in file_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _connect(db_path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve(strict=True)
    if read_only:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)
    else:
        conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def safety_checks(
    conn: sqlite3.Connection,
    rj_ids: Iterable[str],
    force_large: bool,
) -> list[str]:
    ids = list(dict.fromkeys(str(item).strip() for item in rj_ids if str(item).strip()))
    issues: list[str] = []
    if len(ids) > MAX_BATCH_RJS and not force_large:
        issues.append(
            f"Refusing batch of {len(ids)} RJs (max {MAX_BATCH_RJS})."
        )
    placeholders = ",".join("?" for _ in RUNTIME_ACTIVE_STATUSES)
    active_rows = int(
        conn.execute(
            f"SELECT COUNT(*) FROM downloads WHERE status IN ({placeholders})",
            RUNTIME_ACTIVE_STATUSES,
        ).fetchone()[0]
    )
    if active_rows:
        issues.append(
            f"Runtime queue is not idle ({active_rows} active/resumable rows). "
            "Backlog re-enable is blocked until queued/downloading/resuming/paused/failed rows are zero."
        )
    if not ids:
        issues.append("No RJ IDs provided.")
    return issues


def _rows_for_ids(conn: sqlite3.Connection, rj_ids: list[str]) -> list[sqlite3.Row]:
    if not rj_ids:
        return []
    placeholders = ",".join("?" for _ in rj_ids)
    return conn.execute(
        f"""SELECT id,rj_id,track_title,status,downloaded_bytes,total_bytes,
                   error,updated_at,local_path
            FROM downloads
            WHERE rj_id IN ({placeholders})
              AND status IN ('stale','ignored')
            ORDER BY rj_id,id""",
        rj_ids,
    ).fetchall()


def dry_run(
    rj_ids: Iterable[str],
    mode: str = "continue",
    *,
    db_path: str | Path = DB_PATH,
) -> dict[str, Any]:
    ids = list(dict.fromkeys(str(item).strip() for item in rj_ids if str(item).strip()))
    conn = _connect(db_path, read_only=True)
    try:
        rows = _rows_for_ids(conn, ids)
    finally:
        conn.close()
    grouped: dict[str, list[dict[str, Any]]] = {rj_id: [] for rj_id in ids}
    for row in rows:
        new_bytes = 0 if mode == "retry-from-zero" else int(row["downloaded_bytes"] or 0)
        grouped.setdefault(str(row["rj_id"]), []).append(
            {
                "id": row["id"],
                "track_title": row["track_title"],
                "old_status": row["status"],
                "new_status": TARGET_STATUS,
                "old_downloaded_bytes": int(row["downloaded_bytes"] or 0),
                "new_downloaded_bytes": new_bytes,
                "old_error": row["error"],
                "new_error": None,
                "local_path": row["local_path"],
            }
        )
    would_update = [
        {"rj_id": rj_id, "count": len(grouped.get(rj_id, [])), "details": grouped.get(rj_id, [])}
        for rj_id in ids
    ]
    return {
        "dry_run": True,
        "rj_ids": ids,
        "mode": mode,
        "would_update": would_update,
        "totals": {
            "rjs": len(ids),
            "total_rows": len(rows),
            "target_status": TARGET_STATUS,
            "mode": mode,
        },
    }


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _write_rollback_sql(path: Path, rows: list[sqlite3.Row]) -> None:
    lines = ["-- Generated rollback SQL", "BEGIN IMMEDIATE;"]
    for row in rows:
        lines.append(
            "UPDATE downloads SET "
            f"status={_sql_literal(row['status'])}, "
            f"downloaded_bytes={_sql_literal(row['downloaded_bytes'])}, "
            f"error={_sql_literal(row['error'])}, "
            f"updated_at={_sql_literal(row['updated_at'])} "
            f"WHERE id={_sql_literal(row['id'])};"
        )
    lines.append("COMMIT;")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _counts(conn: sqlite3.Connection) -> dict[str, Any]:
    statuses = {
        status: int(
            conn.execute("SELECT COUNT(*) FROM downloads WHERE status=?", (status,)).fetchone()[0]
        )
        for status in ("stale", "ignored", "completed", "queued", "paused", "downloading", "resuming")
    }
    statuses["works"] = {
        str(row[0]): int(row[1])
        for row in conn.execute("SELECT status, COUNT(*) FROM works GROUP BY status")
    }
    return statuses


def execute(
    rj_ids: Iterable[str],
    mode: str = "continue",
    *,
    db_path: str | Path = DB_PATH,
    force_large: bool = False,
    backup_root: str | Path = ".local_backups",
) -> dict[str, Any]:
    if mode not in {"continue", "retry-from-zero"}:
        raise ValueError("mode must be continue or retry-from-zero")
    ids = list(dict.fromkeys(str(item).strip() for item in rj_ids if str(item).strip()))
    path = Path(db_path).expanduser().resolve(strict=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir: Path | None = None

    conn = _connect(path, read_only=False)
    try:
        integrity_before = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity_before.lower() != "ok":
            raise RuntimeError(f"database integrity check failed: {integrity_before}")
        issues = safety_checks(conn, ids, force_large)
        if issues:
            raise RuntimeError("; ".join(issues))

        rows = _rows_for_ids(conn, ids)
        if not rows:
            raise RuntimeError("No stale/ignored rows matched the requested RJ IDs.")
        if mode == "retry-from-zero":
            part_paths = []
            for row in rows:
                local_path = str(row["local_path"] or "")
                if local_path and Path(local_path + ".part").exists():
                    part_paths.append(local_path + ".part")
            if part_paths:
                raise RuntimeError(
                    "retry-from-zero is blocked while .part files exist; use continue"
                )

        backup_dir = Path(backup_root) / f"backlog_reenable_{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup_db = backup_dir / "history.before_reenable.db"
        backup_conn = sqlite3.connect(backup_db)
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()
        with closing(sqlite3.connect(backup_db)) as verify_conn:
            backup_integrity = str(verify_conn.execute("PRAGMA integrity_check").fetchone()[0])
        if backup_integrity.lower() != "ok":
            raise RuntimeError(f"backup integrity check failed: {backup_integrity}")

        preimage = [dict(row) for row in rows]
        (backup_dir / "backlog_reenable_preimage.json").write_text(
            json.dumps(
                {"rows": preimage, "count": len(rows), "backup_integrity": backup_integrity},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        _write_rollback_sql(backup_dir / "backlog_reenable_rollback.sql", rows)

        before = _counts(conn)
        placeholders = ",".join("?" for _ in ids)
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("BEGIN IMMEDIATE")
        try:
            locked_issues = safety_checks(conn, ids, force_large)
            if locked_issues:
                raise RuntimeError("; ".join(locked_issues))
            locked_rows = _rows_for_ids(conn, ids)
            if [dict(row) for row in locked_rows] != preimage:
                raise RuntimeError(
                    "Backlog rows changed after preview/backup; no update was applied."
                )
            if mode == "retry-from-zero":
                cursor = conn.execute(
                    f"""UPDATE downloads
                        SET status=?, downloaded_bytes=0, error=NULL, updated_at=?
                        WHERE rj_id IN ({placeholders})
                          AND status IN ('stale','ignored')""",
                    (TARGET_STATUS, now, *ids),
                )
            else:
                cursor = conn.execute(
                    f"""UPDATE downloads
                        SET status=?, error=NULL, updated_at=?
                        WHERE rj_id IN ({placeholders})
                          AND status IN ('stale','ignored')""",
                    (TARGET_STATUS, now, *ids),
                )
            updated = max(0, int(cursor.rowcount))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        after = _counts(conn)
        integrity_after = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        actual = {
            "timestamp": now,
            "rj_count": len(ids),
            "mode": mode,
            "updated_rows": updated,
            "integrity_before": integrity_before,
            "integrity_after": integrity_after,
            "counts_before": before,
            "counts_after": after,
            "completed_unchanged": before["completed"] == after["completed"],
            "works_unchanged": before["works"] == after["works"],
            "backup_dir": str(backup_dir),
            "sqlite_backup": str(backup_db),
        }
        verdict = (
            integrity_after.lower() == "ok"
            and actual["completed_unchanged"]
            and actual["works_unchanged"]
        )
        (backup_dir / "backlog_reenable_actual_summary.json").write_text(
            json.dumps(actual, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (backup_dir / "backlog_reenable_post_verify.json").write_text(
            json.dumps(
                {
                    "integrity": integrity_after,
                    "completed_ok": actual["completed_unchanged"],
                    "works_ok": actual["works_unchanged"],
                    "verdict": "OK" if verdict else "FAIL",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if not verdict:
            raise RuntimeError("post-update verification failed")
        return actual
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--rj", nargs="+", help="RJ IDs to re-enable")
    group.add_argument("--from-file", help="File with one RJ ID per line")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--mode", choices=["retry-from-zero", "continue"], default="continue")
    parser.add_argument("--force-large-batch", action="store_true")
    args = parser.parse_args()

    try:
        ids = load_rj_ids_from_file(args.from_file) if args.from_file else (args.rj or [])
        if args.execute:
            result = execute(
                ids,
                mode=args.mode,
                db_path=args.db,
                force_large=args.force_large_batch,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            result = dry_run(ids, mode=args.mode, db_path=args.db)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
