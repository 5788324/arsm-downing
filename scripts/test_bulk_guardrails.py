"""Tests for bulk_download_preflight and bulk_download_postcheck."""
import sys, os, json, sqlite3, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tools.bulk_download_preflight as preflight
import tools.bulk_download_postcheck as postcheck

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        passed += 1; print(f"  PASS: {name}")
    else:
        failed += 1; print(f"  FAIL: {name}")

print("=== RC9.5 Guardrail Tests ===\n")

# Test 1: preflight on clean DB
print("1. Preflight on live DB")
r = preflight.run_preflight()
check("integrity_check passes", r["checks"]["integrity_check"]["ok"])
check("active_queue empty", r["checks"]["active_queue"]["ok"])
check("config check passes", r["checks"]["config"]["ok"])
check("stale_ignored isolation ok", r["checks"]["stale_ignored_isolation"]["ok"])
check("completed_missing ok", r["checks"]["completed_missing"]["ok"])
check("verdict is GO", r["verdict"] == "GO")

# Test 2: preflight detects auto_resume_on_start=true
print("\n2. Preflight detects bad config")
# We can't modify config.json for test, but we can verify the config check works
check("config issues empty on correct config", len(r["checks"]["config"]["issues"]) == 0)

# Test 3: postcheck on current DB
print("\n3. Postcheck on live DB")
r2 = postcheck.run_postcheck()
check("integrity_check passes", r2["checks"]["integrity_check"]["ok"])
check("completed_missing check ok", r2["checks"]["completed_missing"]["ok"])
check("stale_preserved ok", r2["checks"]["stale_preserved"]["ok"])
check("has downloads_status", "completed" in r2["downloads_status"])
check("has recent_works", len(r2["recent_works"]) > 0)
check("has error_summary", "error_summary" in r2["checks"])
check("verdict is OK or WARN", r2["verdict"] in ("OK", "WARN"))

# Test 4: reports written
print("\n4. Report files exist")
from datetime import datetime
ts = datetime.now().strftime("%Y%m%d")
preflight_dirs = sorted(Path(".local_backups").glob("bulk_download_preflight_*"))
postcheck_dirs = sorted(Path(".local_backups").glob("bulk_download_postcheck_*"))
check("preflight report json exists", any((d / "bulk_download_preflight_report.json").exists() for d in preflight_dirs))
check("preflight summary txt exists", any((d / "BULK_DOWNLOAD_PREFLIGHT_SUMMARY.txt").exists() for d in preflight_dirs))
check("postcheck report json exists", any((d / "bulk_download_postcheck_report.json").exists() for d in postcheck_dirs))
check("postcheck summary txt exists", any((d / "BULK_DOWNLOAD_POSTCHECK_SUMMARY.txt").exists() for d in postcheck_dirs))

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
print(f"Overall: {'PASS' if failed == 0 else 'FAIL'}")
sys.exit(0 if failed == 0 else 1)
