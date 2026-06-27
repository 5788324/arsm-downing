#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.unfinished_closeout import build_unfinished_closeout_plan, render_sql_preview
from scripts.rc9_1_closeout_testlib import make_temp_closeout_db


def main():
    db_path, conn = make_temp_closeout_db()
    conn.execute("INSERT INTO works (rj_id, status, local_path) VALUES (?,?,?)", ("RJ99110011", "prepared", "/tmp/RJ99110011"))
    conn.execute("INSERT INTO downloads (id, rj_id, track_title, local_path, status) VALUES (?,?,?,?,?)", ("RJ99110011:t1", "RJ99110011", "t1", "/tmp/RJ99110011/t1.mp3", "registered"))
    conn.commit(); conn.close()
    plan = build_unfinished_closeout_plan(db_path)
    rows = plan["categories"]["registered_to_ignored"]
    assert len(rows) == 1, rows
    assert rows[0]["suggested_status"] == "ignored", rows[0]
    preview = render_sql_preview(plan)
    assert "PREVIEW ONLY -- NO DB WRITES AUTHORIZED" in preview
    assert "UPDATE downloads SET status='ignored'" in preview
    print("PASS registered_to_ignored_preview_only")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
