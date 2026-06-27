#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.unfinished_closeout import build_unfinished_closeout_plan
from scripts.rc9_1_closeout_testlib import make_temp_closeout_db


def main():
    db_path, conn = make_temp_closeout_db()
    conn.execute("INSERT INTO works (rj_id, status, local_path) VALUES (?,?,?)", ("RJ99110008", "completed", "/tmp/RJ99110008"))
    conn.execute("INSERT INTO downloads (id, rj_id, track_title, local_path, status) VALUES (?,?,?,?,?)", ("RJ99110008:t1", "RJ99110008", "t1", "/tmp/RJ99110008/t1.mp3", "completed"))
    conn.commit(); conn.close()
    plan = build_unfinished_closeout_plan(db_path)
    assert plan["counts"]["completed_skipped"] == 1, plan["counts"]
    all_ids = {entry["id"] for bucket in plan["categories"].values() for entry in bucket}
    assert "RJ99110008:t1" not in all_ids, all_ids
    print("PASS completed_downloads_never_marked_stale")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
