#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.unfinished_closeout import build_unfinished_closeout_plan
from scripts.rc9_1_closeout_testlib import make_temp_closeout_db


def main():
    db_path, conn = make_temp_closeout_db()
    conn.execute("INSERT INTO works (rj_id, status, local_path) VALUES (?,?,?)", ("RJ99110009", "completed", "/tmp/RJ99110009"))
    conn.execute("INSERT INTO downloads (id, rj_id, track_title, local_path, status) VALUES (?,?,?,?,?)", ("RJ99110009:t1", "RJ99110009", "t1", "/tmp/RJ99110009/t1.mp3", "completed"))
    conn.execute("INSERT INTO works (rj_id, status, local_path) VALUES (?,?,?)", ("RJ99110010", "prepared", "/tmp/RJ99110010"))
    conn.execute("INSERT INTO downloads (id, rj_id, track_title, local_path, status) VALUES (?,?,?,?,?)", ("RJ99110010:t1", "RJ99110010", "t1", "/tmp/RJ99110010/t1.mp3", "registered"))
    conn.commit(); conn.close()
    plan = build_unfinished_closeout_plan(db_path)
    assert plan["counts"]["completed_included"] is False
    assert len(plan["categories"]["registered_to_ignored"]) == 1
    print("PASS closeout_plan_does_not_include_completed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
