#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.unfinished_closeout import build_unfinished_closeout_plan
from scripts.rc9_1_closeout_testlib import make_temp_closeout_db


def main():
    temp_root = Path(".local_backups") / "rc9_1_part_test"
    temp_root.mkdir(parents=True, exist_ok=True)
    target = temp_root / "track.mp3"
    part = Path(str(target) + ".part")
    part.write_bytes(b"123")
    db_path, conn = make_temp_closeout_db()
    conn.execute("INSERT INTO works (rj_id, status, local_path) VALUES (?,?,?)", ("RJ99110012", "prepared", str(temp_root / 'work')))
    conn.execute("INSERT INTO downloads (id, rj_id, track_title, local_path, status) VALUES (?,?,?,?,?)", ("RJ99110012:t1", "RJ99110012", "t1", str(target), "paused"))
    conn.commit(); conn.close()
    plan = build_unfinished_closeout_plan(db_path)
    rows = plan["categories"]["paused_resumable_needs_user_decision"]
    assert len(rows) == 1, rows
    assert rows[0]["has_part_file"] is True, rows[0]
    print("PASS paused_with_part_file_requires_user_decision")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
