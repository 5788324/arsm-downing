"""Backlog batch: chain list + dry-run + execute in one command.
Usage:
  python tools/backlog_batch.py --source ignored --limit 30 --sort downloads_asc --dry-run
  python tools/backlog_batch.py --source ignored --limit 30 --sort downloads_asc --execute
"""
import sqlite3, json, os, sys, argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.backlog_list import run_backlog_list
from tools.backlog_reenable import dry_run as reenable_dry, execute as reenable_exec

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass


def main():
    p = argparse.ArgumentParser(description="Backlog batch recovery")
    p.add_argument("--source", choices=["ignored","stale","all"], default="ignored")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--sort", choices=["downloads_asc","downloads_desc","rj_asc"], default="downloads_asc")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--mode", choices=["retry-from-zero","continue"], default="retry-from-zero")
    p.add_argument("--force-large-batch", action="store_true")
    args = p.parse_args()

    if not args.execute:
        args.dry_run = True

    # Step 1: List
    print("="*60 + "\nSTEP 1: List candidates\n" + "="*60)
    groups, summary, candidates = run_backlog_list(source=args.source, limit=args.limit, sort_by=args.sort)
    if not candidates:
        print("No candidates found."); return

    # Step 2: Print summary
    rj_ids_from_list = [c["rj_id"] for c in candidates]

    # Re-count actual rows that would be updated (stale+ignored, not just filtered type)
    conn = sqlite3.connect("history.db")
    if rj_ids_from_list:
        ph = ",".join("?" * len(rj_ids_from_list))
        actual_count = conn.execute(f"SELECT COUNT(*) FROM downloads WHERE rj_id IN ({ph}) AND status IN ('stale','ignored')", rj_ids_from_list).fetchone()[0]
    else:
        actual_count = 0
    conn.close()

    total_rows = actual_count

    # Step 2: Print summary
    print(f"\nBatch: {len(rj_ids_from_list)} RJs, {total_rows} download rows")
    for c in candidates[:5]:
        print(f"  {c['rj_id']}: {c['ignored_count']}i/{c['stale_count']}s, {c['downloads_total']} total")
    if len(candidates) > 5:
        print(f"  ... and {len(candidates)-5} more")

    # Step 3: Dry-run re-enable
    print(f"\n{'='*60}\nSTEP 2: Dry-run re-enable\n{'='*60}")
    dr = reenable_dry(rj_ids_from_list, mode=args.mode)
    print(f"Would update: {dr['totals']['total_rows']} rows across {dr['totals']['rjs']} RJs")
    for r in dr["would_update"][:3]:
        print(f"  {r['rj_id']}: {r['count']} rows")

    # Step 4: Execute if requested
    if args.execute:
        print(f"\n{'='*60}\nSTEP 3: Execute\n{'='*60}")
        actual = reenable_exec(rj_ids_from_list, mode=args.mode)
        print(f"\nResult: {actual['updated_rows']} rows updated")
        print(f"Backup: {actual['backup_dir']}")
        print(f"Verdict: {'OK' if actual['completed_unchanged'] and actual['works_unchanged'] else 'CHECK'}")
    else:
        print(f"\nDry-run complete. Use --execute to apply.")
        print(f"Command: python tools/backlog_batch.py --source {args.source} --limit {args.limit} --sort {args.sort} --execute")


if __name__ == "__main__":
    main()
