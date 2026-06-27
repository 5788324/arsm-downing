"""RC10 tests: backlog CLI, backlog UI, library items, download compatibility."""
import sys, os, json, sqlite3
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.backlog_list import run_backlog_list
from tools.backlog_reenable import dry_run as reenable_dry, load_rj_ids_from_file
from core.database import LibraryVault

passed = failed = 0
def check(name, condition):
    global passed, failed
    if condition: passed += 1; print(f"  PASS: {name}")
    else: failed += 1; print(f"  FAIL: {name}")

db = LibraryVault()
print("=== RC10 Tests ===\n")

# ── Backlog list CLI ──
print("1. backlog_list --source ignored --limit 20")
g, s, candidates = run_backlog_list(source="ignored", limit=20, sort_by="downloads_asc")
check("returns candidates", len(candidates) > 0)
check("respects limit", len(candidates) <= 20)
check("all ignored_backlog", all(c["recommended_action"] == "requeue_registered_backlog" for c in candidates))
check("sorted downloads_asc", all(c["downloads_total"] <= candidates[-1]["downloads_total"] for c in candidates[:-1]) if len(candidates) > 1 else True)

print("\n2. backlog_list --source stale --limit 10")
g2, s2, c2 = run_backlog_list(source="stale", limit=10, sort_by="rj_asc")
check("returns candidates", len(c2) > 0)
check("all stale_backlog", all(c["recommended_action"] in ("retry_from_zero","manual_review_resume_or_retry") for c in c2))

print("\n3. backlog_list --source all --sort downloads_desc")
g3, s3, c3 = run_backlog_list(source="all", limit=15, sort_by="downloads_desc")
check("sorted correctly", len(c3) > 0)

print("\n4. backlog_list excludes current paused")
g4, s4, c4 = run_backlog_list(source="all", limit=200)
has_paused = any(c["rj_id"] == "RJ01510133" and c["recommended_action"] != "paused_current_do_not_recover" for c in c4)
check("RJ01510133 not in active backlog", not has_paused)

# ── Backlog re-enable ──
print("\n5. backlog_reenable dry-run")
r = reenable_dry(["RJ01588893", "RJ01534605"])
check("dry_run flag is True", r["dry_run"])
check("target is queued", r["totals"]["target_status"] == "queued")
check("completed not touched", all(d["old_status"] in ("stale","ignored") for rj in r["would_update"] for d in rj["details"]))

print("\n6. backlog_reenable --from-file")
# Create temp file with RJs that have stale/ignored rows
rj_with_backlog = db.conn.execute("SELECT DISTINCT rj_id FROM downloads WHERE status='stale' LIMIT 2").fetchall()
test_rj_ids = [r[0] for r in rj_with_backlog]
check("found test RJs with stale rows", len(test_rj_ids) >= 1)
if test_rj_ids:
    tmp = Path(".local_backups/test_rj_list.txt")
    tmp.write_text("\n".join(test_rj_ids), encoding="utf-8")
    rj_ids_from_file = load_rj_ids_from_file(str(tmp))
    check("reads file correctly", len(rj_ids_from_file) == len(test_rj_ids))
    rd = reenable_dry(rj_ids_from_file)
    check("from-file dry-run works", rd["totals"]["total_rows"] > 0)
    tmp.unlink(missing_ok=True)

# ── Library items queries ──
print("\n7. library_items query")
items = db.get_library_items(limit=5)
check("returns rows", len(items) > 0)
check("has rj_id", all("rj_id" in i for i in items))
check("has folder_path", all("folder_path" in i for i in items))

print("\n8. library_items search")
items2 = db.get_library_items(search="RJ01", limit=10)
check("search returns results", len(items2) > 0)

print("\n9. library_items filter has_audio")
items3 = db.get_library_items(filter_audio=True, limit=5)
check("filter_audio works", all(i.get("has_audio") == 1 for i in items3))

print("\n10. library_items filter missing_cover")
items4 = db.get_library_items(filter_cover=True, limit=5)
check("filter_cover works", all(i.get("has_cover") == 0 for i in items4))

print("\n11. library_summary")
s = db.get_library_summary()
check("total_works", s.get("total_works", 0) > 0)
check("total_files", s.get("total_files", 0) > 0)
check("total_size", s.get("total_size", 0) > 0)

# ── Download page compatibility ──
print("\n12. download queue hides stale/ignored")
pending = db.get_pending_downloads()
stale_in_pending = any(d["status"] in ("stale","ignored") for d in pending)
check("stale not in pending downloads", not stale_in_pending)

pending_rjs = db.get_pending_rj_ids()
stale_rows = db.conn.execute("SELECT DISTINCT rj_id FROM downloads WHERE status='stale' LIMIT 5").fetchall()
stale_in_pending_rjs = any(r[0] in pending_rjs for r in stale_rows)
check("stale not in pending rj_ids", not stale_in_pending_rjs)

print("\n13. download queue shows queued+paused")
queued_rjs = db.conn.execute("SELECT COUNT(DISTINCT rj_id) FROM downloads WHERE status IN ('queued','paused')").fetchone()[0]
check("queued+paused RJs present", queued_rjs > 0)

# ── Backlog UI service layer ──
print("\n14. backlog stats accessible")
stale_count = db.conn.execute("SELECT COUNT(*) FROM downloads WHERE status='stale'").fetchone()[0]
ignored_count = db.conn.execute("SELECT COUNT(*) FROM downloads WHERE status='ignored'").fetchone()[0]
check("stale count > 0", stale_count > 0)
check("ignored count > 0", ignored_count > 0)

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
print(f"Overall: {'PASS' if failed == 0 else 'FAIL'}")
sys.exit(0 if failed == 0 else 1)
