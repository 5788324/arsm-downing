"""Backlog list: scan stale/ignored downloads into recovery candidates.
Read-only. Outputs recovery candidate groups for user decision.
"""
import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

DB_PATH = Path("history.db")

def run_backlog_list():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = Path(".local_backups") / f"backlog_list_{ts}"
    os.makedirs(report_dir, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Query all RJs with stale/ignored downloads
    rows = conn.execute("""
        SELECT d.rj_id,
               w.title as work_title,
               w.status as work_status,
               w.local_path as work_local_path,
               COUNT(*) as downloads_total,
               SUM(CASE WHEN d.status='stale' THEN 1 ELSE 0 END) as stale_count,
               SUM(CASE WHEN d.status='ignored' THEN 1 ELSE 0 END) as ignored_count,
               SUM(CASE WHEN d.status='completed' THEN 1 ELSE 0 END) as completed_count,
               SUM(CASE WHEN d.status='paused' THEN 1 ELSE 0 END) as paused_count
        FROM downloads d
        LEFT JOIN works w ON d.rj_id = w.rj_id
        WHERE d.status IN ('stale', 'ignored')
        GROUP BY d.rj_id
        ORDER BY stale_count + ignored_count DESC
    """).fetchall()

    groups = defaultdict(list)
    candidates = []

    for row in rows:
        rj_id = row["rj_id"]
        entry = {
            "rj_id": rj_id,
            "work_title": row["work_title"] or "",
            "work_status": row["work_status"] or "not_in_works",
            "work_local_path": row["work_local_path"] or "",
            "downloads_total": row["downloads_total"],
            "stale_count": row["stale_count"],
            "ignored_count": row["ignored_count"],
            "completed_count": row["completed_count"],
            "paused_count": row["paused_count"],
        }

        # Check filesystem
        wp = row["work_local_path"]
        has_existing_files = os.path.isdir(wp) if wp else False
        has_part_files = False
        if has_existing_files:
            for f in Path(wp).rglob("*.part"):
                has_part_files = True
                break
        entry["has_existing_files"] = has_existing_files
        entry["has_part_files"] = has_part_files

        # Error samples
        errors = conn.execute("""
            SELECT error FROM downloads
            WHERE rj_id=? AND status='stale' AND error IS NOT NULL AND error != ''
            LIMIT 5
        """, (rj_id,)).fetchall()
        entry["last_error_samples"] = [e["error"][:60] for e in errors]

        # Classification
        if rj_id == "RJ01510133":
            group = "paused_current"
            entry["recommended_action"] = "paused_current_do_not_recover"
            entry["risk"] = "current download in progress"
        elif row["completed_count"] > 0 and (row["stale_count"] + row["ignored_count"]) > 0:
            group = "mixed_backlog"
            entry["recommended_action"] = "partial_work_continue"
            entry["risk"] = "has completed files — only re-enable stale/ignored, not completed"
        elif row["ignored_count"] > 0 and row["completed_count"] == 0 and row["stale_count"] == 0:
            group = "ignored_backlog"
            entry["recommended_action"] = "requeue_registered_backlog"
            entry["risk"] = "originally registered — no download history, safe to retry"
        elif row["stale_count"] > 0 and not has_part_files:
            group = "stale_backlog"
            entry["recommended_action"] = "retry_from_zero"
            entry["risk"] = "no partial files — retry from zero is safe"
        elif row["stale_count"] > 0 and has_part_files:
            group = "stale_backlog"
            entry["recommended_action"] = "manual_review_resume_or_retry"
            entry["risk"] = "has .part files — may be resumable, user must decide"
        else:
            group = "blocked"
            entry["recommended_action"] = "manual_review"
            entry["risk"] = "unclassified"

        groups[group].append(entry)
        candidates.append(entry)

    conn.close()

    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_candidate_rjs": len(candidates),
        "total_stale_downloads": sum(c["stale_count"] for c in candidates),
        "total_ignored_downloads": sum(c["ignored_count"] for c in candidates),
        "groups": {g: len(items) for g, items in groups.items()},
    }

    # Write JSON
    json_path = report_dir / "backlog_recovery_candidates.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "groups": {g: items for g, items in groups.items()}, "all": candidates},
                  f, ensure_ascii=False, indent=2, default=str)

    # Write summary
    summary_path = report_dir / "BACKLOG_RECOVERY_CANDIDATES_SUMMARY.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("Backlog Recovery Candidates\n")
        f.write(f"Timestamp: {summary['timestamp']}\n\n")
        f.write(f"Total candidate RJs: {summary['total_candidate_rjs']}\n")
        f.write(f"Total stale downloads: {summary['total_stale_downloads']}\n")
        f.write(f"Total ignored downloads: {summary['total_ignored_downloads']}\n\n")

        for group_name, items in sorted(groups.items()):
            f.write(f"\n{'='*50}\n{group_name} ({len(items)} RJs)\n{'='*50}\n")
            for entry in items:
                f.write(f"\n  {entry['rj_id']}: {entry['work_status']}\n")
                if entry['work_title']:
                    f.write(f"    title: {entry['work_title'][:80]}\n")
                f.write(f"    stale={entry['stale_count']} ignored={entry['ignored_count']} "
                       f"completed={entry['completed_count']} paused={entry['paused_count']}\n")
                f.write(f"    has_files={entry['has_existing_files']} has_part={entry['has_part_files']}\n")
                f.write(f"    action: {entry['recommended_action']}\n")
                f.write(f"    risk: {entry['risk']}\n")

    print(f"Candidates: {summary['total_candidate_rjs']} RJs, {summary['total_stale_downloads'] + summary['total_ignored_downloads']} downloads")
    for g, cnt in summary["groups"].items():
        print(f"  {g}: {cnt}")
    print(f"Report: {report_dir}")
    return groups, summary

if __name__ == "__main__":
    run_backlog_list()
