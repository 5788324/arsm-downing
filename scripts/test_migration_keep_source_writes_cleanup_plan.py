#!/usr/bin/env python3
import json, os, sqlite3, sys, shutil
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.migration import MigrationEngine

def fake_rename(src, dst):
    src_p = Path(src)
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    if src_p.is_dir():
        shutil.copytree(src_p, dst_p, dirs_exist_ok=True)
        shutil.rmtree(src_p, ignore_errors=True)
    else:
        shutil.copy2(src_p, dst_p)
        src_p.unlink()


class FakeDB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE works (rj_id TEXT PRIMARY KEY, title TEXT, local_path TEXT, status TEXT, size_bytes INTEGER)")
        self.conn.execute("CREATE TABLE downloads (id TEXT PRIMARY KEY, rj_id TEXT, local_path TEXT, status TEXT)")
        self.conn.execute("CREATE TABLE library_index (rj_id TEXT, library_path TEXT, work_dir TEXT, status TEXT)")
    def get_safe_migratable_works(self):
        return [dict(x) for x in self.conn.execute("SELECT rj_id, title, local_path, status, size_bytes FROM works").fetchall()]
    def move_work_to_path(self, rj_id, old_path, new_path):
        self.conn.execute("UPDATE works SET local_path=? WHERE rj_id=?", (new_path, rj_id))
        self.conn.execute("UPDATE library_index SET work_dir=?, library_path=? WHERE rj_id=?", (new_path, str(Path(new_path).parent), rj_id))
        self.conn.commit()
        return {'success': True, 'updated': 1, 'error': ''}

root = Path(f'tmp_test_cleanup_plan_{uuid4().hex}').resolve()
shutil.rmtree(root, ignore_errors=True)
root.mkdir(parents=True, exist_ok=True)
orig_cleanup = MigrationEngine.CLEANUP_PLAN_FILE
orig_rename = os.rename
MigrationEngine.CLEANUP_PLAN_FILE = root / 'migration_cleanup_plan.jsonl'
os.rename = fake_rename
try:
    src = root / 'src' / 'RJTEST2'
    dst = root / 'dst' / 'RJTEST2'
    src.mkdir(parents=True, exist_ok=True)
    (src / 'a.bin').write_bytes(b'x')
    db = FakeDB()
    db.conn.execute("INSERT INTO works VALUES (?,?,?,?,?)", ('RJTEST2', 'T', str(src), 'completed', 1))
    db.conn.execute("INSERT INTO library_index VALUES (?,?,?,?)", ('RJTEST2', str(src.parent), str(src), 'found'))
    db.conn.commit()
    res = MigrationEngine(db).migrate_one('RJTEST2', str(src), str(dst), delete_source=False, target_base=str(root / 'dst'))
    assert res['success']
    entry = json.loads(MigrationEngine.CLEANUP_PLAN_FILE.read_text(encoding='utf-8').strip().splitlines()[-1])
    assert entry['rj_id'] == 'RJTEST2'
    assert entry['status'] == 'source_preserved'
    print('OK cleanup plan written')
finally:
    os.rename = orig_rename
    MigrationEngine.CLEANUP_PLAN_FILE = orig_cleanup
    shutil.rmtree(root, ignore_errors=True)
