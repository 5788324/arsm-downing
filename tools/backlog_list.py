"""Backlog list: scan stale/ignored downloads into recovery candidates.
Supports --source, --limit, --sort, --exclude-current-paused, --output-selected-rjs.
"""
import sqlite3, json, os, sys, argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

DB_PATH = Path("history.db")
CURRENT_PAUSED_RJ = "RJ01510133"

def run_backlog_list(source="all", limit=0, sort_by="downloads_asc", exclude_current=True, output_selected=None):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = Path(".local_backups") / f"backlog_list_{ts}"
    os.makedirs(report_dir, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    where = "WHERE d.status IN ('stale','ignored')"
    if source == "ignored":
        where += " AND d.status = 'ignored'"
    elif source == "stale":
        where += " AND d.status = 'stale'"

    if exclude_current:
        where += f" AND d.rj_id != '{CURRENT_PAUSED_RJ}'"

    order = "stale_count + ignored_count DESC"
    if sort_by == "downloads_asc":
        order = "downloads_total ASC"
    elif sort_by == "downloads_desc":
        order = "downloads_total DESC"
    elif sort_by == "rj_asc":
        order = "d.rj_id ASC"

    limit_clause = f"LIMIT {int(limit)}" if limit > 0 else ""

    rows = conn.execute(f"""
        SELECT d.rj_id, w.title as work_title, w.status as work_status,
               w.local_path as work_local_path, COUNT(*) as downloads_total,
               SUM(CASE WHEN d.status='stale' THEN 1 ELSE 0 END) as stale_count,
               SUM(CASE WHEN d.status='ignored' THEN 1 ELSE 0 END) as ignored_count,
               SUM(CASE WHEN d.status='completed' THEN 1 ELSE 0 END) as completed_count,
               SUM(CASE WHEN d.status='paused' THEN 1 ELSE 0 END) as paused_count
        FROM downloads d LEFT JOIN works w ON d.rj_id = w.rj_id
        {where} GROUP BY d.rj_id ORDER BY {order} {limit_clause}
    """).fetchall()

    groups = defaultdict(list)
    candidates = []

    for row in rows:
        rj_id = row["rj_id"]
        entry = {"rj_id": rj_id, "work_title": row["work_title"] or "",
                 "work_status": row["work_status"] or "not_in_works",
                 "work_local_path": row["work_local_path"] or "",
                 "downloads_total": row["downloads_total"],
                 "stale_count": row["stale_count"], "ignored_count": row["ignored_count"],
                 "completed_count": row["completed_count"], "paused_count": row["paused_count"]}
        wp = row["work_local_path"]
        entry["has_existing_files"] = os.path.isdir(wp) if wp else False
        entry["has_part_files"] = False
        if entry["has_existing_files"]:
            for f in Path(wp).rglob("*.part"):
                entry["has_part_files"] = True; break

        errors = conn.execute("SELECT error FROM downloads WHERE rj_id=? AND status='stale' AND error IS NOT NULL AND error != '' LIMIT 5", (rj_id,)).fetchall()
        entry["last_error_samples"] = [e["error"][:60] for e in errors]

        if rj_id == CURRENT_PAUSED_RJ:
            group = "paused_current"; entry["recommended_action"] = "paused_current_do_not_recover"
            entry["risk"] = "current download in progress"
        elif row["completed_count"] > 0 and (row["stale_count"] + row["ignored_count"]) > 0:
            group = "mixed_backlog"; entry["recommended_action"] = "partial_work_continue"
            entry["risk"] = "has completed files"
        elif row["ignored_count"] > 0 and row["completed_count"] == 0 and row["stale_count"] == 0:
            group = "ignored_backlog"; entry["recommended_action"] = "requeue_registered_backlog"
            entry["risk"] = "originally registered"
        elif row["stale_count"] > 0 and not entry["has_part_files"]:
            group = "stale_backlog"; entry["recommended_action"] = "retry_from_zero"
            entry["risk"] = "no partial files"
        elif row["stale_count"] > 0 and entry["has_part_files"]:
            group = "stale_backlog"; entry["recommended_action"] = "manual_review_resume_or_retry"
            entry["risk"] = "has .part files"
        else:
            group = "blocked"; entry["recommended_action"] = "manual_review"
            entry["risk"] = "unclassified"

        groups[group].append(entry); candidates.append(entry)

    conn.close()

    summary = {"timestamp": datetime.now().isoformat(), "source": source, "limit": limit,
               "sort": sort_by, "total_candidate_rjs": len(candidates),
               "total_download_rows": sum(c["downloads_total"] for c in candidates),
               "groups": {g: len(items) for g, items in groups.items()}}

    # Write JSON
    json_path = report_dir / "backlog_recovery_candidates.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "groups": {g: items for g, items in groups.items()}}, f, ensure_ascii=False, indent=2, default=str)

    # Write TXT summary
    summary_path = report_dir / "BACKLOG_RECOVERY_CANDIDATES_SUMMARY.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"Backlog Candidates | source={source} limit={limit} sort={sort_by}\n\n")
        f.write(f"Candidate RJs: {len(candidates)}\n")
        for g, cnt in summary["groups"].items():
            f.write(f"  {g}: {cnt}\n")
        f.write(f"\nTotal download rows: {summary['total_download_rows']}\n\n")
        f.write("Top candidates:\n")
        for c in candidates[:20]:
            f.write(f"  {c['rj_id']}: {c['stale_count']}s/{c['ignored_count']}i, {c['downloads_total']} total | {c.get('work_title','')[:40]}\n")

    # Write selected RJs if requested
    if output_selected:
        rj_ids = [c["rj_id"] for c in candidates]
        (report_dir / output_selected).write_text("\n".join(rj_ids), encoding="utf-8")
        print(f"Selected RJs written to: {report_dir / output_selected}")

    print(f"Candidates: {len(candidates)} RJs, {summary['total_download_rows']} downloads")
    for g, cnt in summary["groups"].items():
        print(f"  {g}: {cnt}")
    print(f"Report: {report_dir}")
    return groups, summary, candidates

def main():
    p = argparse.ArgumentParser(description="Backlog recovery candidate scanner")
    p.add_argument("--source", choices=["ignored","stale","all"], default="all")
    p.add_argument("--limit", type=int, default=0, help="Max RJs to return (0 = all)")
    p.add_argument("--sort", choices=["downloads_asc","downloads_desc","rj_asc"], default="downloads_asc")
    p.add_argument("--exclude-current-paused", action="store_true", default=True)
    p.add_argument("--output-selected-rjs", type=str, default="", help="Filename to write selected RJ IDs")
    args = p.parse_args()
    run_backlog_list(source=args.source, limit=args.limit, sort_by=args.sort,
                     exclude_current=args.exclude_current_paused, output_selected=args.output_selected_rjs)

if __name__ == "__main__":
    main()
