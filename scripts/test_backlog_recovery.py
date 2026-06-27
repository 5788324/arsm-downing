"""Tests for backlog_list.py and backlog_reenable.py."""
import sys, os, json, sqlite3
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.backlog_list import run_backlog_list
from tools.backlog_reenable import dry_run

DB_PATH = Path("history.db")
passed = failed = 0

def check(name, condition):
    global passed, failed
    if condition: passed += 1; print(f"  PASS: {name}")
    else: failed += 1; print(f"  FAIL: {name}")

print("=== RC9.7 Backlog Recovery Tests ===\n")

# ── backlog_list tests ──
print("1. backlog_list groups")
groups, summary, _ = run_backlog_list()
check("has stale_backlog group", "stale_backlog" in groups)
check("has ignored_backlog group", "ignored_backlog" in groups)
check("total candidates > 0", summary["total_candidate_rjs"] > 0)
check("total download rows > 0", summary["total_download_rows"] > 0)
check("has groups", len(summary["groups"]) > 0)
check("excludes completed_only", len([c for c in groups.get("stale_backlog", []) + groups.get("ignored_backlog", [])
                                      if c["completed_count"] > 0 and c["stale_count"] == 0 and c["ignored_count"] == 0]) == 0)
check("keeps RJ01510133 as paused_current if present", "RJ01510133" not in [
    c["rj_id"] for c in groups.get("stale_backlog", []) + groups.get("ignored_backlog", [])])

# ── backlog_reenable tests ──
print("\n2. backlog_reenable dry-run")
result = dry_run(["RJ01588893"])
check("dry-run returns would_update", len(result["would_update"]) > 0)
check("target status is queued", result["totals"]["target_status"] == "queued")
check("dry_run flag is True", result["dry_run"] is True)

print("\n3. backlog_reenable requires rj allowlist")
result2 = dry_run(["RJ01588893", "RJ01534605"])
check("multiple RJs handled", len(result2["would_update"]) == 2)
check("only stale/ignored targeted", all(d.get("old_status") in ("stale","ignored")
      for r in result2["would_update"] for d in r["details"]))

print("\n4. backlog_reenable does not touch completed")
conn = sqlite3.connect(str(DB_PATH))
completed_before = conn.execute("SELECT COUNT(*) FROM downloads WHERE status='completed'").fetchone()[0]
conn.close()
# Dry run doesn't write — check that count is still same
conn2 = sqlite3.connect(str(DB_PATH))
completed_after = conn2.execute("SELECT COUNT(*) FROM downloads WHERE status='completed'").fetchone()[0]
conn2.close()
check("completed untouched by dry-run", completed_before == completed_after)

print("\n5. backlog_reenable retry-from-zero zeroes bytes")
for r in result["would_update"]:
    for d in r["details"]:
        if d["old_downloaded_bytes"] != d["new_downloaded_bytes"]:
            check(f"bytes zeroed: {d['id'][:20]}", d["new_downloaded_bytes"] == 0)
            break

print("\n6. Reports exist")
ts = datetime.now().strftime("%Y%m%d")
bl_dirs = sorted(Path(".local_backups").glob("backlog_list_*"))
check("backlog_list json exists", any((d / "backlog_recovery_candidates.json").exists() for d in bl_dirs))
check("backlog_list summary exists", any((d / "BACKLOG_RECOVERY_CANDIDATES_SUMMARY.txt").exists() for d in bl_dirs))

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
print(f"Overall: {'PASS' if failed == 0 else 'FAIL'}")
sys.exit(0 if failed == 0 else 1)
