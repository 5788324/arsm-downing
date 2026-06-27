#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.unfinished_closeout import build_unfinished_closeout_plan
from scripts.rc9_1_closeout_testlib import make_temp_closeout_db


def main():
    db_path, conn = make_temp_closeout_db()
    conn.execute("INSERT INTO works (rj_id, status, local_path) VALUES (?,?,?)", ("RJ99110013", "partial", "/tmp/RJ99110013"))
    conn.execute("INSERT INTO downloads (id, rj_id, track_title, local_path, status, total_bytes) VALUES (?,?,?,?,?,?)", ("RJ99110013:t1", "RJ99110013", "t1", "/tmp/does_not_exist.mp3", "failed", 100))
    conn.commit(); conn.close()
    plan = build_unfinished_closeout_plan(db_path)
    rows = plan["categories"]["failed_to_stale"]
    assert len(rows) == 1, rows
    assert rows[0]["suggested_status"] == "stale", rows[0]
    print("PASS failed_without_file_can_be_stale_candidate")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
