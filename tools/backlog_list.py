"""Read-only stale/ignored backlog candidate scanner."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

DB_PATH = Path("history.db")


def _connect_read_only(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve(strict=True)
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def run_backlog_list(
    source: str = "all",
    limit: int = 0,
    sort_by: str = "downloads_asc",
    exclude_current: bool = False,
    output_selected: str | None = None,
    *,
    db_path: str | Path = DB_PATH,
    exclude_rj_ids: Iterable[str] | None = None,
    report_root: str | Path = ".local_backups",
):
    """Return grouped backlog candidates without mutating SQLite.

    ``exclude_current`` remains as a compatibility argument but no longer hides
    a product-specific RJ.  Callers must pass explicit ``exclude_rj_ids``.
    """
    del exclude_current
    if source not in {"ignored", "stale", "all"}:
        raise ValueError("source must be ignored, stale, or all")
    if sort_by not in {"downloads_asc", "downloads_desc", "rj_asc"}:
        raise ValueError("unsupported sort")

    excluded = sorted({str(item).strip() for item in (exclude_rj_ids or []) if str(item).strip()})
    filters = ["status IN ('stale','ignored')"]
    params: list[object] = []
    if source in {"ignored", "stale"}:
        filters.append("status = ?")
        params.append(source)
    if excluded:
        placeholders = ",".join("?" for _ in excluded)
        filters.append(f"rj_id NOT IN ({placeholders})")
        params.extend(excluded)
    where = " AND ".join(filters)

    selected_order = "selected_count ASC, rj_id ASC"
    if sort_by == "downloads_desc":
        selected_order = "selected_count DESC, rj_id ASC"
    elif sort_by == "rj_asc":
        selected_order = "rj_id ASC"
    limit_sql = " LIMIT ?" if int(limit) > 0 else ""
    if int(limit) > 0:
        params.append(max(1, int(limit)))

    query = f"""
        WITH selected AS (
            SELECT rj_id, COUNT(*) AS selected_count
            FROM downloads
            WHERE {where}
            GROUP BY rj_id
            ORDER BY {selected_order}
            {limit_sql}
        )
        SELECT d.rj_id,
               w.title AS work_title,
               w.status AS work_status,
               w.local_path AS work_local_path,
               COUNT(*) AS downloads_total,
               SUM(CASE WHEN d.status='stale' THEN 1 ELSE 0 END) AS stale_count,
               SUM(CASE WHEN d.status='ignored' THEN 1 ELSE 0 END) AS ignored_count,
               SUM(CASE WHEN d.status='completed' THEN 1 ELSE 0 END) AS completed_count,
               SUM(CASE WHEN d.status='paused' THEN 1 ELSE 0 END) AS paused_count
        FROM selected s
        JOIN downloads d ON d.rj_id=s.rj_id
        LEFT JOIN works w ON w.rj_id=d.rj_id
        GROUP BY d.rj_id
    """
    final_order = "downloads_total ASC, d.rj_id ASC"
    if sort_by == "downloads_desc":
        final_order = "downloads_total DESC, d.rj_id ASC"
    elif sort_by == "rj_asc":
        final_order = "d.rj_id ASC"
    query += f" ORDER BY {final_order}"

    conn = _connect_read_only(db_path)
    try:
        rows = conn.execute(query, params).fetchall()
        groups: dict[str, list[dict]] = defaultdict(list)
        candidates: list[dict] = []
        for row in rows:
            rj_id = str(row["rj_id"])
            entry = {
                "rj_id": rj_id,
                "work_title": row["work_title"] or "",
                "work_status": row["work_status"] or "not_in_works",
                "work_local_path": row["work_local_path"] or "",
                "downloads_total": int(row["downloads_total"] or 0),
                "stale_count": int(row["stale_count"] or 0),
                "ignored_count": int(row["ignored_count"] or 0),
                "completed_count": int(row["completed_count"] or 0),
                "paused_count": int(row["paused_count"] or 0),
            }
            work_path = entry["work_local_path"]
            entry["has_existing_files"] = bool(work_path and os.path.isdir(work_path))
            entry["has_part_files"] = bool(
                entry["has_existing_files"]
                and any(Path(work_path).rglob("*.part"))
            )
            error_rows = conn.execute(
                """SELECT error FROM downloads
                   WHERE rj_id=? AND status='stale'
                     AND error IS NOT NULL AND error!=''
                   ORDER BY updated_at DESC LIMIT 5""",
                (rj_id,),
            ).fetchall()
            entry["last_error_samples"] = [str(item["error"])[:60] for item in error_rows]

            if entry["paused_count"] > 0:
                group = "runtime_review"
                entry["recommended_action"] = "wait_until_runtime_idle"
                entry["risk"] = "paused rows coexist with backlog"
            elif entry["completed_count"] > 0:
                group = "mixed_backlog"
                entry["recommended_action"] = "partial_work_continue"
                entry["risk"] = "has completed files"
            elif entry["ignored_count"] > 0 and entry["stale_count"] == 0:
                group = "ignored_backlog"
                entry["recommended_action"] = "requeue_registered_backlog"
                entry["risk"] = "originally registered"
            elif entry["stale_count"] > 0 and entry["has_part_files"]:
                group = "stale_backlog"
                entry["recommended_action"] = "continue_or_manual_review"
                entry["risk"] = "has .part files"
            elif entry["stale_count"] > 0:
                group = "stale_backlog"
                entry["recommended_action"] = "continue"
                entry["risk"] = "no partial file found"
            else:
                group = "blocked"
                entry["recommended_action"] = "manual_review"
                entry["risk"] = "unclassified"
            groups[group].append(entry)
            candidates.append(entry)
    finally:
        conn.close()

    timestamp = datetime.now().isoformat(timespec="seconds")
    summary = {
        "timestamp": timestamp,
        "source": source,
        "limit": int(limit),
        "sort": sort_by,
        "excluded_rj_ids": excluded,
        "total_candidate_rjs": len(candidates),
        "total_download_rows": sum(item["downloads_total"] for item in candidates),
        "groups": {name: len(items) for name, items in groups.items()},
    }

    report_dir = Path(report_root) / f"backlog_list_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    report_dir.mkdir(parents=True, exist_ok=False)
    (report_dir / "backlog_recovery_candidates.json").write_text(
        json.dumps(
            {"summary": summary, "groups": dict(groups)},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    lines = [
        f"Backlog Candidates | source={source} limit={limit} sort={sort_by}",
        "",
        f"Candidate RJs: {len(candidates)}",
    ]
    lines.extend(f"  {name}: {count}" for name, count in summary["groups"].items())
    lines.extend(["", f"Total download rows: {summary['total_download_rows']}", "", "Top candidates:"])
    lines.extend(
        f"  {item['rj_id']}: {item['stale_count']}s/{item['ignored_count']}i, "
        f"{item['downloads_total']} total | {item['work_title'][:40]}"
        for item in candidates[:20]
    )
    (report_dir / "BACKLOG_RECOVERY_CANDIDATES_SUMMARY.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    if output_selected:
        (report_dir / output_selected).write_text(
            "\n".join(item["rj_id"] for item in candidates), encoding="utf-8"
        )
    summary["report_dir"] = str(report_dir)
    return groups, summary, candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--source", choices=["ignored", "stale", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sort", choices=["downloads_asc", "downloads_desc", "rj_asc"], default="downloads_asc")
    parser.add_argument("--exclude-rj", action="append", default=[])
    parser.add_argument("--output-selected-rjs", default="")
    parser.add_argument("--report-root", default=".local_backups")
    args = parser.parse_args()
    try:
        groups, summary, _ = run_backlog_list(
            source=args.source,
            limit=args.limit,
            sort_by=args.sort,
            output_selected=args.output_selected_rjs or None,
            db_path=args.db,
            exclude_rj_ids=args.exclude_rj,
            report_root=args.report_root,
        )
        print(json.dumps({"summary": summary, "groups": {key: len(value) for key, value in groups.items()}}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
